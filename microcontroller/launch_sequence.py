import time
from pymavlink import mavutil
from flight_controller import fc_config
from flight_controller import fc_connection
from flight_controller import fc_status
from flight_controller import fc_utils

TARGET_ALTITUDE = 9.144  # meters relative to home (30 feet)
ALTITUDE_TOLERANCE = 0.5
MODE_TIMEOUT = 10
ARM_TIMEOUT = 15
ALTITUDE_TIMEOUT = 45
PROGRESS_TIMEOUT = 12
MIN_PROGRESS = 0.25
READINESS_TIMEOUT = 15
ARM = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
TAKEOFF = mavutil.mavlink.MAV_CMD_NAV_TAKEOFF


#this function is used to return the details of the launch
# (state, drone_id, arm_requested, takeoff_requested, handoff)
def _result(state, drone_id, **extra):
    result = {
        "state": state,
        "drone_id": drone_id,
        "arm_requested": False,
        "takeoff_requested": False,
        "handoff": None,
    }
    result.update(extra)
    return result


def _finish(progress, result):
    fc_utils.emit_progress(progress, result["state"], result)
    return result


def _failed(progress, drone_id, state, reason, **extra):
    """Finish one failed launch result. Defaults stay those of _result."""
    result = _result(
        state,
        drone_id,
        reason=reason,
        reasons=[reason],
        **extra,
    )
    return _finish(progress, result)


def _state_is(cache, mode, armed, now):
    shot = fc_status.snapshot(cache, now)
    return shot["mode"] == mode and shot["armed"] is armed


# follows the drone's height until it reaches the target or something goes wrong
def confirm_climb(cache, target_altitude, altitude_timeout, progress_timeout, stop=None, pump=None):
    #set the deadline for the climb, time out if it takes too long (should have leeway with this timeout)
    deadline = time.monotonic() + altitude_timeout
    #set the time it started, and the last time it progressed
    started = last_progress = time.monotonic()
    last_position_at = None
    best_altitude = None
    pending_altitude = None
    pending_at = None
    fc_connection.mark_operation(cache)

    #pre timeout corner
    while time.monotonic() < deadline:
        message = fc_connection.read(cache, 0.2)
        if pump is not None:
            pump()
        if stop is not None and stop():
            raise RuntimeError("Launch cancelled before the next command")
        now = time.monotonic()

        #set position anchor to started, AT THE BEGINING, or set it to the last position if we are on a non-initial loop
        position_anchor = started if last_position_at is None else last_position_at
        #if we dont get a message, or the message is bad data edge check
        if message is None or message.get_type() == "BAD_DATA":
            if now - position_anchor > fc_config.FRESH_SECONDS:
                raise RuntimeError("Altitude telemetry missing or stale")
            continue

        #get the type of the message (same logic as wait_for_aircraft)
        kind = message.get_type()
        if (
            kind == "COMMAND_ACK"
            and cache.get("ack_at") is not None
            and cache["ack_at"] >= started
            and fc_utils.rejected_command(message, TAKEOFF)
        ):
            raise RuntimeError("ArduPilot rejected the takeoff command")
        if kind == "HEARTBEAT":
            shot = fc_status.snapshot(cache, now)
            if shot["mode"] != "GUIDED" or shot["armed"] is not True:
                raise RuntimeError("Flight controller left GUIDED or disarmed")
            if (
                pending_altitude is not None
                and pending_at is not None
                and now - pending_at <= fc_config.FRESH_SECONDS
                and pending_altitude >= target_altitude - ALTITUDE_TOLERANCE
            ):
                return pending_altitude
            if now - position_anchor > fc_config.FRESH_SECONDS:
                raise RuntimeError("Altitude telemetry missing or stale")
            continue
        if kind != "GLOBAL_POSITION_INT":
            if now - position_anchor > fc_config.FRESH_SECONDS:
                raise RuntimeError("Altitude telemetry missing or stale")
            continue
        last_position_at = now
        #unlike wait_for_aircraft, we are waiting for the altitude to reach the target, so check that and check progress
        altitude = message.relative_alt / 1000.0
        #if no best alt or the altitude is better than the best alt + MIN_PROGRESS, set the best alt to the altitude
        if best_altitude is None or altitude >= best_altitude + MIN_PROGRESS:
            best_altitude = altitude
            last_progress = now
        # A frame queued behind this position still belongs to the same burst.
        fc_connection.drain(cache)
        now = time.monotonic()
        ack = cache.get("ack")
        ack_at = cache.get("ack_at")
        if (
            ack is not None
            and ack_at is not None
            and ack_at >= started
            and fc_utils.rejected_command(ack, TAKEOFF)
        ):
            raise RuntimeError("ArduPilot rejected the takeoff command")
        shot = fc_status.snapshot(cache, now)
        if shot["communication_confirmed"] and (
            shot["mode"] != "GUIDED" or shot["armed"] is not True
        ):
            raise RuntimeError("Flight controller left GUIDED or disarmed")
        if shot["mode"] != "GUIDED" or shot["armed"] is not True:
            pending_altitude = altitude
            pending_at = last_position_at
            continue
        #if the altitude is within the tolerance we are alloting for, we can confirm the climb, also send the altitude
        if altitude >= target_altitude - ALTITUDE_TOLERANCE:
            return altitude
        #if the last progress is more than the progress timeout, raise an error, continue within the loop
        if now - last_progress > progress_timeout:
            raise RuntimeError("No altitude progress")
    #we in da timeout corner --> cant confirm the climb
    raise RuntimeError("Target altitude timeout")


def _confirm_state(cache, mode, armed, timeout, command, stop=None, pump=None):
    outcome = fc_utils.wait_for_state(
        cache, mode, armed, timeout, command, stop=stop, pump=pump
    )
    if outcome == "aborted":
        return "aborted"
    if outcome == "changed":
        raise RuntimeError("Flight controller left GUIDED or disarmed")
    if outcome == "rejected":
        raise RuntimeError(
            "ArduPilot rejected GUIDED mode."
            if command == fc_utils.SET_MODE
            else "ArduPilot rejected the arm command."
        )
    if outcome != "ready":
        #if we timed out, or not in the mode we want, or not armed, raise an error
        raise RuntimeError(f"timed out waiting for {mode} armed={armed}")


def _cancelled(progress, drone_id, commands_started, arm_requested, takeoff_requested):
    """Stop before the next launch command. No command yet returns None."""
    if not commands_started:
        return None
    state = "LAUNCH_INTERRUPTED" if arm_requested else "LAUNCH_FAILED"
    return _failed(
        progress,
        drone_id,
        state,
        "Launch cancelled before the next command",
        arm_requested=arm_requested,
        takeoff_requested=takeoff_requested,
        commands_started=True,
    )


##OUR LAUNCH CODE ----------------------------------------------------------------
# runs the launch steps in order when main.py calls this function
def run_launch(
    cache,
    drone_id,
    progress=None,
    target_altitude=None,
    mode_timeout=None,
    arm_timeout=None,
    altitude_timeout=None,
    progress_timeout=None,
    stop=None,
    pump=None,
):
    if target_altitude is None:
        target_altitude = TARGET_ALTITUDE
    if mode_timeout is None:
        mode_timeout = MODE_TIMEOUT
    if arm_timeout is None:
        arm_timeout = ARM_TIMEOUT
    if altitude_timeout is None:
        altitude_timeout = ALTITUDE_TIMEOUT
    if progress_timeout is None:
        progress_timeout = PROGRESS_TIMEOUT

    #set the values for everything we use in the other functions
    arm_requested = False
    takeoff_requested = False
    commands_started = False
    #try to launch the drone
    try:
        if cache is None:
            raise RuntimeError("Flight controller link is not connected")
        if stop is not None and stop():
            return None

        # look up the GUIDED mode number. this does not send anything yet
        guided = fc_utils.request_mode(cache, "GUIDED")
        # GUIDED is not in this flight controller's mode list, so no command is sent
        if guided["mode_id"] is None:
            reason = "GUIDED mode unavailable"
            return _failed(
                progress,
                drone_id,
                "NOT_READY",
                reason,
                commands_started=False,
            )
        # send the mode change
        # set_mode only writes the frame locally. An exception means that write failed, so SET_MODE never reached the flight controller.
        if guided["write_completed"] is None:
            reason = f"GUIDED frame was not sent: {guided['error']}"
            cache["commands_started"] = True
            return _failed(
                progress,
                drone_id,
                "LAUNCH_FAILED",
                reason,
                commands_started=True,
                write_completed=None,
            )
        commands_started = True
        cache["commands_started"] = True
        fc_connection.mark_operation(cache)

        # wait until a heartbeat shows GUIDED and still disarmed
        if _confirm_state(
            cache, "GUIDED", False, mode_timeout, fc_utils.SET_MODE, stop=stop, pump=pump
        ) == "aborted":
            return _cancelled(progress, drone_id, commands_started, arm_requested, takeoff_requested)
        if stop is not None and stop():
            return _cancelled(progress, drone_id, commands_started, arm_requested, takeoff_requested)

        # command_long_send only writes the frame. An exception means the arm command was not sent.
        #try to arm the drone
        fc_connection.drain(cache)
        if not _state_is(cache, "GUIDED", False, time.monotonic()):
            raise RuntimeError("Flight controller left GUIDED or disarmed")
        arm = fc_utils.send_command(cache, ARM, 1, 0, 0, 0, 0, 0, 0)
        if arm["write_completed"] is None:
            reason = f"Arm frame was not sent: {arm['error']}"
            return _failed(
                progress,
                drone_id,
                "LAUNCH_FAILED",
                reason,
                commands_started=True,
                write_completed=None,
            )
        arm_requested = True
        fc_connection.mark_operation(cache)
        #wait for the drone to be in the GUIDED mode and armed
        if _confirm_state(
            cache, "GUIDED", True, arm_timeout, ARM, stop=stop, pump=pump
        ) == "aborted":
            return _cancelled(progress, drone_id, commands_started, arm_requested, takeoff_requested)
        if stop is not None and stop():
            return _cancelled(progress, drone_id, commands_started, arm_requested, takeoff_requested)

        fc_connection.drain(cache)
        if not _state_is(cache, "GUIDED", True, time.monotonic()):
            raise RuntimeError("Flight controller left GUIDED or disarmed")
        #READY FOR TAKEOFF----------------------------------------------------------------------------------
        # tells the drone to take off to our target height of 30 feet
        #try to takeoff
        #send the takeoff command --> actually goes into the air to reach the target altitude
        takeoff = fc_utils.send_command(
            cache, TAKEOFF, 0, 0, 0, 0, 0, 0, target_altitude
        )
        if takeoff["write_completed"] is None:
            reason = f"Takeoff frame was not sent: {takeoff['error']}"
            return _failed(
                progress,
                drone_id,
                "LAUNCH_INTERRUPTED",
                reason,
                arm_requested=True,
                commands_started=True,
                write_completed=None,
            )
        takeoff_requested = True

        #confirm the climb
        altitude = confirm_climb(
            cache,
            target_altitude,
            altitude_timeout,
            progress_timeout,
            stop=stop,
            pump=pump,
        )
        #send the result
        result = _result(
            "LAUNCH_SUCCEEDED",
            drone_id,
            reason="Climb confirmed",
            altitude_m=altitude,
            handoff="autonomous",
            arm_requested=True,
            takeoff_requested=True,
            commands_started=True,
        )
        return _finish(progress, result)

    #if we get an error at any point in the try
    except (RuntimeError, OSError, TimeoutError) as error:
        rejected = str(error).startswith("ArduPilot rejected")
        if rejected and not takeoff_requested:
            state = "LAUNCH_FAILED"
        elif commands_started:
            state = "LAUNCH_INTERRUPTED" if arm_requested else "LAUNCH_FAILED"
        else:
            state = "NOT_READY"
        return _failed(
            progress,
            drone_id,
            state,
            str(error),
            arm_requested=arm_requested,
            takeoff_requested=takeoff_requested,
            commands_started=commands_started,
        )
