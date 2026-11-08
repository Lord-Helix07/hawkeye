"""Launch from a Dynamo request, then hand off at 30 feet above home.

The Drones row is the go signal. This file checks the Kakute, sends
GUIDED, arm, and takeoff, and confirms the climb from relative altitude.
It does not read command replies. Autonomous following starts after this
returns. Landing stays in landing_sequence.py.
"""

import time

from pymavlink import mavutil

TARGET_ALTITUDE = 9.144  # meters relative to home (30 feet)
ALTITUDE_TOLERANCE = 0.5
MODE_TIMEOUT = 10
ARM_TIMEOUT = 15
ALTITUDE_TIMEOUT = 45
PROGRESS_TIMEOUT = 12
MIN_PROGRESS = 0.25
READINESS_TIMEOUT = 15
# Seconds. A heartbeat or position older than this is not current.
FRESH_SECONDS = 5
FC_PORT = "/dev/ttyACM0"
BAUD_RATE = 115200

LAUNCH_REQUESTED = "LAUNCH_REQUESTED"
ARM = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
TAKEOFF = mavutil.mavlink.MAV_CMD_NAV_TAKEOFF
PREARM = mavutil.mavlink.MAV_SYS_STATUS_PREARM_CHECK
ARMED = mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED


def drones_table():
    """Return the Dynamo Drones table. The caller has to configure AWS."""
    import boto3

    return boto3.resource("dynamodb").Table("Drones")


def find_launch_request(table, drone_id):
    """Return this drone's row when launch_status is LAUNCH_REQUESTED, or None.

    drone_id is the Drones table key, and the Pi already has its own id.
    The website writes launch_status and mission_id on that row.
    Does not touch the Kakute.
    """
    response = table.get_item(Key={"drone_id": drone_id})
    item = response.get("Item")
    if not item or item.get("launch_status") != LAUNCH_REQUESTED:
        return None
    return item


def _armed(heartbeat):
    return bool(heartbeat.base_mode & ARMED)


def _fresh(seen_at, now):
    return seen_at is not None and now - seen_at <= FRESH_SECONDS


def _readiness_reasons(heartbeat, heartbeat_at, gps, gps_at, status, status_at, now):
    """Blocking reasons from the latest heartbeat, GPS, and pre-arm sample."""
    reasons = []
    if not _fresh(heartbeat_at, now):
        reasons.append("Heartbeat missing or stale")
    elif _armed(heartbeat):
        reasons.append("Flight controller is already armed")
    if not _fresh(gps_at, now):
        reasons.append("GPS telemetry missing or stale")
    elif gps.fix_type < 3:
        reasons.append("GPS fix is not 3D")
    if not _fresh(status_at, now):
        reasons.append("Pre-arm status missing or stale")
    elif (status.onboard_control_sensors_health & PREARM) == 0:
        reasons.append("Pre-arm checks have not passed")
    return reasons


def ready_for_launch(link, timeout=READINESS_TIMEOUT):
    """Read the Kakute until it is fit to launch, or the wait ends.

    A fresh heartbeat must be disarmed, GPS must have a 3D fix, and the
    pre-arm bit must be set. A missing sample is not treated as healthy.
    Reads telemetry. Does not send commands or read command replies.
    Returns (ready, reasons).
    """
    deadline = time.monotonic() + timeout
    heartbeat = gps = status = None
    heartbeat_at = gps_at = status_at = None
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        message = link.recv_match(blocking=True, timeout=min(0.2, remaining))
        now = time.monotonic()
        if message is not None and message.get_type() != "BAD_DATA":
            kind = message.get_type()
            if kind == "HEARTBEAT":
                heartbeat, heartbeat_at = message, now
            elif kind == "GPS_RAW_INT":
                gps, gps_at = message, now
            elif kind == "SYS_STATUS":
                status, status_at = message, now
        if heartbeat is not None and gps is not None and status is not None:
            reasons = _readiness_reasons(
                heartbeat, heartbeat_at, gps, gps_at, status, status_at, now
            )
            if all(
                _fresh(seen_at, now)
                for seen_at in (heartbeat_at, gps_at, status_at)
            ):
                return not reasons, reasons
    now = time.monotonic()
    return False, _readiness_reasons(
        heartbeat, heartbeat_at, gps, gps_at, status, status_at, now
    )


def wait_for_aircraft(link, mode, armed, timeout):
    """Wait until a fresh heartbeat shows this mode and armed state.

    Reads heartbeats. Does not send commands or read command replies.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        message = link.recv_match(
            type="HEARTBEAT", blocking=True, timeout=min(0.2, remaining)
        )
        if message is None or message.get_type() != "HEARTBEAT":
            continue
        seen_armed = _armed(message)
        if mavutil.mode_string_v10(message) == mode and seen_armed == armed:
            return
    raise RuntimeError(f"timed out waiting for {mode} armed={armed}")


def _command(link, command, *parameters):
    link.mav.command_long_send(
        link.target_system,
        link.target_component,
        command,
        0,
        *parameters,
    )


# follows the drone's height until it reaches the target or something goes wrong
def confirm_climb(link):
    """Wait until relative altitude reaches the target above home.

    relative_alt is millimetres above home, not raw GPS altitude above
    sea level. A sample older than FRESH_SECONDS does not count. The
    heartbeat must stay GUIDED and armed. Reads telemetry. Does not send.
    Returns metres above home.
    """
    deadline = time.monotonic() + ALTITUDE_TIMEOUT
    started = last_progress = time.monotonic()
    last_position_at = None
    last_heartbeat = None
    best_altitude = None
    while time.monotonic() < deadline:
        message = link.recv_match(blocking=True, timeout=0.2)
        now = time.monotonic()
        position_anchor = started if last_position_at is None else last_position_at
        if message is None or message.get_type() == "BAD_DATA":
            if now - position_anchor > FRESH_SECONDS:
                raise RuntimeError("Altitude telemetry missing or stale")
            continue
        kind = message.get_type()
        if kind == "HEARTBEAT":
            if mavutil.mode_string_v10(message) != "GUIDED" or not _armed(message):
                raise RuntimeError("Flight controller left GUIDED or disarmed")
            last_heartbeat = now
            if now - position_anchor > FRESH_SECONDS:
                raise RuntimeError("Altitude telemetry missing or stale")
            continue
        if kind != "GLOBAL_POSITION_INT":
            if now - position_anchor > FRESH_SECONDS:
                raise RuntimeError("Altitude telemetry missing or stale")
            continue
        last_position_at = now
        if not _fresh(last_heartbeat, now):
            continue
        altitude = message.relative_alt / 1000.0
        if best_altitude is None or altitude >= best_altitude + MIN_PROGRESS:
            best_altitude = altitude
            last_progress = now
        if altitude >= TARGET_ALTITUDE - ALTITUDE_TOLERANCE:
            return altitude
        if now - last_progress > PROGRESS_TIMEOUT:
            raise RuntimeError("No altitude progress")
    raise RuntimeError("Target altitude timeout")


def _result(state, mission, drone_id, **extra):
    result = {
        "state": state,
        "mission_id": None if mission is None else mission.get("mission_id"),
        "drone_id": drone_id,
        "arm_requested": False,
        "takeoff_requested": False,
        "handoff": None,
    }
    result.update(extra)
    return result


# runs the launch steps in order when main.py calls this function
def run_launch(
    drone_id,
    table=None,
    connection_address=FC_PORT,
    baud_rate=BAUD_RATE,
):
    """Read this Pi's Drones row, check the Kakute, climb, and hand off.

    The read is one get_item by drone_id. Opens the serial link after
    launch_status is LAUNCH_REQUESTED and closes it before returning.
    A close error is stored as cleanup_error.
    Command replies are not used. The climb is confirmed from relative
    altitude. Returns a status dict. handoff is "autonomous" only after
    the target altitude is reached.
    """
    if table is None:
        table = drones_table()
    mission = find_launch_request(table, drone_id)
    if mission is None:
        return _result("NO_LAUNCH_REQUEST", None, drone_id)

    link = None
    result = None
    arm_requested = False
    takeoff_requested = False
    try:
        link = mavutil.mavlink_connection(connection_address, baud=baud_rate)
        if link.wait_heartbeat(timeout=10) is None:
            result = _result(
                "NOT_READY",
                mission,
                drone_id,
                reason="Flight controller heartbeat missing",
                reasons=["Flight controller heartbeat missing"],
            )
            return result

        ready, reasons = ready_for_launch(link)
        if not ready:
            result = _result(
                "NOT_READY",
                mission,
                drone_id,
                reason="Flight controller is not ready",
                reasons=reasons,
            )
            return result

        guided = (link.mode_mapping() or {}).get("GUIDED")
        if guided is None:
            raise RuntimeError("GUIDED mode unavailable")
        try:
            link.set_mode(guided)
        except Exception as error:
            result = _result(
                "LAUNCH_UNCERTAIN",
                mission,
                drone_id,
                reason=f"GUIDED write outcome uncertain: {error}",
            )
            return result
        wait_for_aircraft(link, "GUIDED", False, MODE_TIMEOUT)

        # Once a command is attempted, a write error can leave its outcome unknown.
        # sends the arm command and lets fc_status confirm the drone is armed
        arm_requested = True
        try:
            _command(link, ARM, 1, 0, 0, 0, 0, 0, 0)
        except Exception as error:
            result = _result(
                "LAUNCH_UNCERTAIN",
                mission,
                drone_id,
                reason=f"Arm write outcome uncertain: {error}",
                arm_requested=True,
            )
            return result
        wait_for_aircraft(link, "GUIDED", True, ARM_TIMEOUT)

        # tells the drone to take off to our target height of 30 feet
        takeoff_requested = True
        try:
            _command(link, TAKEOFF, 0, 0, 0, 0, 0, 0, TARGET_ALTITUDE)
        except Exception as error:
            result = _result(
                "LAUNCH_UNCERTAIN",
                mission,
                drone_id,
                reason=f"Takeoff write outcome uncertain: {error}",
                arm_requested=True,
                takeoff_requested=True,
            )
            return result

        altitude = confirm_climb(link)
        result = _result(
            "LAUNCH_SUCCEEDED",
            mission,
            drone_id,
            altitude_m=altitude,
            handoff="autonomous",
            arm_requested=True,
            takeoff_requested=True,
        )
        return result
    except (RuntimeError, OSError, TimeoutError) as error:
        result = _result(
            "LAUNCH_INTERRUPTED" if arm_requested else "LAUNCH_FAILED",
            mission,
            drone_id,
            reason=str(error),
            arm_requested=arm_requested,
            takeoff_requested=takeoff_requested,
        )
        return result
    finally:
        if link is not None:
            try:
                link.close()
            except Exception as error:
                if result is not None:
                    result["cleanup_error"] = str(error)


# clears old messages so we don't mix up replies to different commands
def prepare_command(cache):
    # Drain frames already waiting before this command.
    # BAD_DATA must not terminate the drain: a malformed frame can
    # sit ahead of an old ACK, and stopping there would let that ACK
    # be read later as the response to the new command. None means
    # the receive had nothing; any other return means keep going,
    # until this deadline.
    deadline = time.monotonic() + 0.3

    while time.monotonic() < deadline:
        message = cache.update(timeout=0)

        if message is None:
            break

    # ignore ACKs already in our cache
    cache.acks.clear()

    return cache.sequence
