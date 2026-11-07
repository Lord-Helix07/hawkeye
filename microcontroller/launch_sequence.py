
from pymavlink import mavutil
import argparse
import queue
import threading
import time
import json
import math


# Pi and Kakute connection
DEFAULT_CONNECTION = "/dev/ttyACM0"
DEFAULT_BAUD_RATE = 115200

# 30 feet in meters
TARGET_ALTITUDE = 9.144
ALTITUDE_TOLERANCE = 0.5

# battery settings must be confirmed by EE
DEFAULT_BATTERY_ID = None
DEFAULT_BATTERY_FORMAT = None
DEFAULT_MIN_VOLTAGE = None

HEARTBEAT_MAX_AGE = 3.0
TELEMETRY_MAX_AGE = 5.0

INITIAL_HEARTBEAT_TIMEOUT = 10
READINESS_TIMEOUT = 15
CONFIRMATION_TIMEOUT = 30
MODE_TIMEOUT = 10
ARM_TIMEOUT = 15
COMMAND_ACK_TIMEOUT = 5
ALTITUDE_TIMEOUT = 45
PROGRESS_TIMEOUT = 12
RECOVERY_TIMEOUT = 10

GROUND_ALTITUDE = 0.3
AIRBORNE_ALTITUDE = 0.8
MIN_PROGRESS = 0.25


def make_status(state, reason=None, **extra):
    result = {"state": state, "reason": reason}
    result.update(extra)
    return result


def report_status(status):
    print(json.dumps(status, default=str))


def is_armed(heartbeat):
    return bool(
        heartbeat.base_mode
        & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
    )


def connect(address, baud):
    # open the connection and wait for ArduPilot
    connection = mavutil.mavlink_connection(
        address, baud=baud
    )

    try:
        heartbeat = connection.wait_heartbeat(
            timeout=INITIAL_HEARTBEAT_TIMEOUT
        )

        if heartbeat is None:
            raise RuntimeError("Initial heartbeat timeout")

        return connection

    except Exception:
        connection.close()
        raise


class TelemetryCache:
    # save recent messages so we don't use old data

    def __init__(self, connection):
        self.connection = connection
        self.messages = {}
        self.batteries = {}
        self.acks = []
        self.faults = []

    def update(self, timeout=0.2):
        message = self.connection.recv_match(
            blocking=True, timeout=timeout
        )

        if message is None:
            return None

        kind = message.get_type()
        now = time.monotonic()

        if kind == "BAD_DATA":
            return None

        self.messages[kind] = (message, now)

        if kind == "BATTERY_STATUS":
            self.batteries[message.id] = (message, now)

        if kind == "COMMAND_ACK":
            self.acks.append((message, now))

        if kind == "STATUSTEXT":
            text = str(getattr(message, "text", ""))
            severity = getattr(message, "severity", 6)

            if severity <= 3:
                self.faults.append((text, now))

        return message

    def fresh(self, kind, max_age=TELEMETRY_MAX_AGE):
        item = self.messages.get(kind)

        if item is None:
            return None

        message, received = item

        if time.monotonic() - received > max_age:
            return None

        return message

    def battery(self, battery_id):
        item = self.batteries.get(battery_id)

        if item is None:
            return None

        message, received = item

        if time.monotonic() - received > TELEMETRY_MAX_AGE:
            return None

        return message

    def heartbeat(self):
        return self.fresh(
            "HEARTBEAT", HEARTBEAT_MAX_AGE
        )

    def recent_faults(self):
        now = time.monotonic()

        return [
            text for text, received in self.faults
            if now - received <= TELEMETRY_MAX_AGE
        ]


def get_battery_voltage(battery, voltage_format):
    # ArduPilot may report pack voltage or cell voltages
    if battery is None:
        return None

    values = list(getattr(battery, "voltages", []))
    values += list(
        getattr(battery, "voltages_ext", [])
    )

    valid = [
        value for value in values
        if isinstance(value, (int, float))
        and 0 < value < 65535
    ]

    if voltage_format == "pack":
        if len(valid) != 1:
            return None
        return valid[0] / 1000.0

    if voltage_format == "cells":
        if len(valid) != 6:
            return None
        return sum(valid) / 1000.0

    return None


def check_readiness(cache, config):
    reasons = []

    heartbeat = cache.heartbeat()

    if heartbeat is None:
        reasons.append("Heartbeat missing or stale")

    elif is_armed(heartbeat):
        reasons.append("Drone is already armed")

    sys_status = cache.fresh("SYS_STATUS")

    if sys_status is None:
        reasons.append("SYS_STATUS missing or stale")

    else:
        prearm = mavutil.mavlink.MAV_SYS_STATUS_PREARM_CHECK

        enabled = sys_status.onboard_control_sensors_enabled
        healthy = sys_status.onboard_control_sensors_health

        if not enabled & prearm:
            reasons.append("Pre-arm status unavailable")

        elif not healthy & prearm:
            reasons.append("ArduPilot pre-arm checks failed")

        sensor_mask = (
            mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_GYRO
            | mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_ACCEL
            | mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_MAG
            | mavutil.mavlink.MAV_SYS_STATUS_SENSOR_ABSOLUTE_PRESSURE
            | mavutil.mavlink.MAV_SYS_STATUS_SENSOR_GPS
        )

        if enabled & sensor_mask & ~healthy:
            reasons.append("Enabled flight sensor unhealthy")

    # check the selected main battery
    battery_id = config["battery_id"]
    voltage_format = config["battery_format"]
    minimum = config["min_voltage"]

    if (
        battery_id is None
        or voltage_format not in ("pack", "cells")
        or minimum is None
    ):
        reasons.append("Main battery configuration not confirmed")

    else:
        battery = cache.battery(battery_id)

        if battery is None:
            reasons.append("Main battery telemetry missing")

        else:
            voltage = get_battery_voltage(
                battery, voltage_format
            )

            if voltage is None:
                reasons.append("Main battery voltage unavailable")

            elif voltage < minimum:
                reasons.append(
                    f"Battery {voltage:.2f} V below "
                    f"{minimum:.2f} V minimum"
                )

            charge_state = getattr(battery, "charge_state", 0)

            bad_states = {
                mavutil.mavlink.MAV_BATTERY_CHARGE_STATE_LOW,
                mavutil.mavlink.MAV_BATTERY_CHARGE_STATE_CRITICAL,
                mavutil.mavlink.MAV_BATTERY_CHARGE_STATE_EMERGENCY,
                mavutil.mavlink.MAV_BATTERY_CHARGE_STATE_FAILED,
                mavutil.mavlink.MAV_BATTERY_CHARGE_STATE_UNHEALTHY,
            }

            if charge_state in bad_states:
                reasons.append("Battery reports unhealthy charge state")

    gps = cache.fresh("GPS_RAW_INT")

    if gps is None:
        reasons.append("GPS telemetry missing")

    elif gps.fix_type < 3:
        reasons.append("GPS does not have a 3D fix")

    if cache.fresh("GLOBAL_POSITION_INT") is None:
        reasons.append("Position estimate missing")

    if cache.recent_faults():
        reasons.extend(cache.recent_faults())

    return len(reasons) == 0, reasons


def wait_for_readiness(cache, config):
    deadline = time.monotonic() + READINESS_TIMEOUT

    while time.monotonic() < deadline:
        cache.update()
        ready, reasons = check_readiness(cache, config)

        if ready:
            return True, []

    return check_readiness(cache, config)


class OperatorInput:
    # terminal confirmation for now

    def __init__(self):
        self.responses = queue.Queue()

        threading.Thread(
            target=self.read_input,
            daemon=True
        ).start()

    def read_input(self):
        while True:
            try:
                response = input().strip().upper()
                self.responses.put(response)
            except EOFError:
                return

    def get_response(self):
        try:
            return self.responses.get_nowait()
        except queue.Empty:
            return None


def wait_for_confirmation(cache, config, operator):
    deadline = time.monotonic() + CONFIRMATION_TIMEOUT

    print("READY - type CONFIRM or CANCEL")

    while time.monotonic() < deadline:
        cache.update()

        ready, reasons = check_readiness(cache, config)

        if not ready:
            return make_status(
                "NOT_READY",
                "Readiness lost while waiting",
                reasons=reasons
            )

        response = operator.get_response()

        if response == "CANCEL":
            return make_status("CANCELLED")

        if response == "CONFIRM":
            return make_status("CONFIRMED")

    return make_status("CONFIRMATION_EXPIRED")


def wait_for_mode(connection, cache, expected, timeout):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        cache.update()

        heartbeat = cache.heartbeat()

        if heartbeat is None:
            continue

        mode = mavutil.mode_string_v10(heartbeat)

        if mode == expected:
            return

    raise RuntimeError(f"{expected} mode not confirmed")


def set_guided_mode(connection, cache):
    mode_id = connection.mode_mapping().get("GUIDED")

    if mode_id is None:
        raise RuntimeError("GUIDED mode unavailable")

    connection.set_mode(mode_id)

    wait_for_mode(
        connection, cache, "GUIDED", MODE_TIMEOUT
    )


def wait_for_ack(cache, command, sent_at):
    deadline = time.monotonic() + COMMAND_ACK_TIMEOUT

    while time.monotonic() < deadline:
        cache.update()

        for ack, received in cache.acks:
            if received < sent_at or ack.command != command:
                continue

            if ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
                return "ACCEPTED"

            if ack.result == mavutil.mavlink.MAV_RESULT_IN_PROGRESS:
                return "IN_PROGRESS"

            return "REJECTED"

    return "UNKNOWN"


def arm(connection, cache):
    # normal arm request, never force arm
    command = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM

    sent_at = time.monotonic()

    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        command,
        0,
        1, 0, 0, 0, 0, 0, 0
    )

    ack = wait_for_ack(cache, command, sent_at)

    if ack == "REJECTED":
        raise RuntimeError("Arming rejected by ArduPilot")

    deadline = time.monotonic() + ARM_TIMEOUT

    while time.monotonic() < deadline:
        cache.update()

        heartbeat = cache.heartbeat()

        if heartbeat is not None and is_armed(heartbeat):
            return

    raise RuntimeError(
        f"Armed state not confirmed (ACK: {ack})"
    )


def takeoff(connection, cache):
    command = mavutil.mavlink.MAV_CMD_NAV_TAKEOFF

    sent_at = time.monotonic()

    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        command,
        0,
        0, 0, 0, 0, 0, 0,
        TARGET_ALTITUDE
    )

    return wait_for_ack(cache, command, sent_at)


def get_aircraft_state(cache, takeoff_requested=False):
    heartbeat = cache.heartbeat()
    position = cache.fresh("GLOBAL_POSITION_INT")

    armed = None
    altitude = None
    mode = None

    if heartbeat is not None:
        armed = is_armed(heartbeat)
        mode = mavutil.mode_string_v10(heartbeat)

    if position is not None:
        altitude = position.relative_alt / 1000.0

    if armed is False and not takeoff_requested:
        state = "GROUNDED"

    elif armed and altitude is not None and altitude >= AIRBORNE_ALTITUDE:
        state = "CONFIRMED_AIRBORNE"

    elif armed or takeoff_requested:
        state = "POSSIBLY_AIRBORNE"

    else:
        state = "UNKNOWN"

    return {
        "state": state,
        "armed": armed,
        "altitude_m": altitude,
        "mode": mode,
    }


def monitor_climb(cache):
    deadline = time.monotonic() + ALTITUDE_TIMEOUT

    last_progress = time.monotonic()
    best_altitude = None

    while time.monotonic() < deadline:
        cache.update()

        state = get_aircraft_state(
            cache, takeoff_requested=True
        )

        if cache.heartbeat() is None:
            raise RuntimeError("Heartbeat lost during climb")

        if state["mode"] != "GUIDED":
            raise RuntimeError(
                "Flight mode changed during climb"
            )

        if state["armed"] is False:
            raise RuntimeError(
                "Drone disarmed during climb"
            )

        if cache.recent_faults():
            raise RuntimeError(
                "Autopilot fault during climb"
            )

        altitude = state["altitude_m"]

        if altitude is None:
            raise RuntimeError("Altitude telemetry missing")

        if (
            best_altitude is None
            or altitude >= best_altitude + MIN_PROGRESS
        ):
            best_altitude = altitude
            last_progress = time.monotonic()

        if altitude >= TARGET_ALTITUDE - ALTITUDE_TOLERANCE:
            return altitude

        if time.monotonic() - last_progress > PROGRESS_TIMEOUT:
            raise RuntimeError("No altitude progress")

    raise RuntimeError("Target altitude timeout")


def automatic_recovery(connection, cache):
    # only request LAND if we know it's safe to do so
    state = get_aircraft_state(
        cache, takeoff_requested=True
    )

    if state["state"] != "CONFIRMED_AIRBORNE":
        return make_status(
            "RECOVERY_HANDOFF_REQUIRED",
            "Aircraft state is uncertain",
            aircraft=state
        )

    if state["mode"] != "GUIDED":
        return make_status(
            "RECOVERY_HANDOFF_REQUIRED",
            "Mode changed; manual control or failsafe may be active",
            aircraft=state
        )

    if cache.recent_faults():
        return make_status(
            "RECOVERY_HANDOFF_REQUIRED",
            "Autopilot fault detected",
            aircraft=state
        )

    mode_id = connection.mode_mapping().get("LAND")

    if mode_id is None:
        return make_status(
            "RECOVERY_HANDOFF_REQUIRED",
            "LAND mode unavailable",
            aircraft=state
        )

    connection.set_mode(mode_id)

    try:
        wait_for_mode(
            connection, cache, "LAND", RECOVERY_TIMEOUT
        )

        return make_status(
            "RECOVERY_LANDING",
            "LAND mode confirmed; touchdown not yet verified",
            aircraft=state
        )

    except Exception as error:
        return make_status(
            "RECOVERY_HANDOFF_REQUIRED",
            str(error),
            aircraft=state
        )


def run_launch(
    connection_address,
    baud_rate,
    config,
    execute_flight=False,
    simulation_confirmed=False,
    allow_hardware_flight=False,
    auto_recovery_land=False,
):
    connection = None
    cache = None
    takeoff_requested = False

    try:
        report_status(make_status("LAUNCH_REQUEST_RECEIVED"))

        connection = connect(connection_address, baud_rate)
        cache = TelemetryCache(connection)

        ready, reasons = wait_for_readiness(cache, config)

        if not ready:
            return make_status(
                "NOT_READY",
                reasons=reasons
            )

        report_status(make_status("READY"))

        confirmation = wait_for_confirmation(
            cache, config, OperatorInput()
        )

        if confirmation["state"] != "CONFIRMED":
            return confirmation

        cache.update()
        ready, reasons = check_readiness(cache, config)

        if not ready:
            return make_status(
                "NOT_READY",
                "Readiness changed after confirmation",
                reasons=reasons
            )

        if not execute_flight:
            return make_status("FLIGHT_DISABLED")

        if simulation_confirmed == allow_hardware_flight:
            return make_status(
                "AUTHORIZATION_REQUIRED",
                "Select exactly one verified execution environment"
            )

        set_guided_mode(connection, cache)

        # check again right before arming
        cache.update()
        ready, reasons = check_readiness(cache, config)

        if not ready:
            return make_status(
                "NOT_READY",
                "Readiness changed after GUIDED mode",
                reasons=reasons
            )

        arm(connection, cache)

        takeoff_requested = True
        ack = takeoff(connection, cache)

        if ack == "REJECTED":
            raise RuntimeError(
                "Takeoff command rejected; aircraft state must be verified"
            )

        altitude = monitor_climb(cache)

        return make_status(
            "LAUNCH_SUCCEEDED",
            "Target altitude reached",
            altitude_m=altitude,
            takeoff_ack=ack
        )

    except Exception as error:
        if cache is None:
            return make_status(
                "LAUNCH_FAILED",
                str(error)
            )

        # collect fresh telemetry before deciding recovery
        end = time.monotonic() + 2

        while time.monotonic() < end:
            cache.update()

        state = get_aircraft_state(
            cache, takeoff_requested=takeoff_requested
        )

        if state["state"] == "GROUNDED":
            return make_status(
                "LAUNCH_FAILED",
                str(error),
                aircraft=state
            )

        if auto_recovery_land and connection is not None:
            recovery = automatic_recovery(connection, cache)

            return make_status(
                "LAUNCH_INTERRUPTED",
                str(error),
                aircraft=state,
                recovery=recovery
            )

        return make_status(
            "RECOVERY_HANDOFF_REQUIRED",
            str(error),
            aircraft=state
        )

    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--connection",
        default=DEFAULT_CONNECTION
    )

    parser.add_argument(
        "--baud",
        type=int,
        default=DEFAULT_BAUD_RATE
    )

    parser.add_argument(
        "--battery-id",
        type=int,
        default=DEFAULT_BATTERY_ID
    )

    parser.add_argument(
        "--battery-format",
        choices=["pack", "cells"],
        default=DEFAULT_BATTERY_FORMAT
    )

    parser.add_argument(
        "--min-launch-voltage",
        type=float,
        default=DEFAULT_MIN_VOLTAGE
    )

    parser.add_argument(
        "--execute-flight",
        action="store_true"
    )

    parser.add_argument(
        "--simulation-confirmed",
        action="store_true"
    )

    parser.add_argument(
        "--allow-hardware-flight",
        action="store_true"
    )

    parser.add_argument(
        "--auto-recovery-land",
        action="store_true"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    config = {
        "battery_id": args.battery_id,
        "battery_format": args.battery_format,
        "min_voltage": args.min_launch_voltage,
    }

    result = run_launch(
        connection_address=args.connection,
        baud_rate=args.baud,
        config=config,
        execute_flight=args.execute_flight,
        simulation_confirmed=args.simulation_confirmed,
        allow_hardware_flight=args.allow_hardware_flight,
        auto_recovery_land=args.auto_recovery_land,
    )

    report_status(result)


if __name__ == "__main__":
    main()
