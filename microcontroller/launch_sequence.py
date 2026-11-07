from pymavlink import mavutil
import argparse
import queue
import threading
import time


# default connection for the Pi and Kakute
DEFAULT_CONNECTION = "/dev/ttyACM0"
DEFAULT_BAUD_RATE = 115200

# SITL can use tcp:127.0.0.1:5760

# 30 ft in meters
TARGET_ALTITUDE = 9.144

# gives some room for altitude readings
ALTITUDE_TOLERANCE = 0.5

# minimum voltage before launch, still needs testing
MIN_LAUNCH_VOLTAGE = 22.2

# how old telemetry can be before we don't trust it
HEARTBEAT_MAX_AGE = 3.0
TELEMETRY_MAX_AGE = 5.0

# time limits for each part of launch
INITIAL_HEARTBEAT_TIMEOUT = 10
READINESS_TIMEOUT = 10
CONFIRMATION_TIMEOUT = 30
MODE_TIMEOUT = 10
ARM_TIMEOUT = 15
COMMAND_ACK_TIMEOUT = 5
ALTITUDE_TIMEOUT = 30


def make_status(state, reason=None, reasons=None, **extra):
    # makes a status that can eventually be sent to backend
    result = {
        "state": state,
        "reason": reason,
    }

    if reasons is not None:
        result["reasons"] = reasons

    result.update(extra)

    return result


def report_status(status):
    # prints for now, backend can use this later
    print(status)


def connect(connection_address, baud_rate):
    # connect to ArduPilot and make sure we get a heartbeat
    print(
        f"Connecting to flight controller at "
        f"{connection_address}..."
    )

    connection = mavutil.mavlink_connection(
        connection_address,
        baud=baud_rate
    )

    heartbeat = connection.wait_heartbeat(
        timeout=INITIAL_HEARTBEAT_TIMEOUT
    )

    if heartbeat is None:
        raise RuntimeError(
            "No initial heartbeat received from "
            "the flight controller."
        )

    print("Flight controller connected.")

    return connection


class TelemetryCache:
    # saves the newest MAVLink messages so we don't use old data

    def __init__(self, connection):
        self.connection = connection
        self.messages = {}
        self.last_heartbeat_time = None
        self.prearm_messages = []

    def update(self, timeout=0.2):
        message = self.connection.recv_match(
            blocking=True,
            timeout=timeout
        )

        if message is None:
            return

        message_type = message.get_type()
        now = time.monotonic()

        self.messages[message_type] = (
            message,
            now
        )

        # keep track of the newest heartbeat
        if message_type == "HEARTBEAT":
            self.last_heartbeat_time = now

        # save any pre-arm errors ArduPilot sends
        if message_type == "STATUSTEXT":
            text = str(
                getattr(message, "text", "")
            )

            if "PreArm:" in text:
                self.prearm_messages.append(text)

                # only keep the latest 5
                self.prearm_messages = (
                    self.prearm_messages[-5:]
                )

    def get_fresh(
        self,
        message_type,
        max_age=TELEMETRY_MAX_AGE
    ):
        # only return the message if it is recent
        stored = self.messages.get(
            message_type
        )

        if stored is None:
            return None

        message, received_time = stored

        age = (
            time.monotonic()
            - received_time
        )

        if age > max_age:
            return None

        return message

    def heartbeat_is_recent(self):
        if self.last_heartbeat_time is None:
            return False

        age = (
            time.monotonic()
            - self.last_heartbeat_time
        )

        return age <= HEARTBEAT_MAX_AGE


def collect_telemetry(cache, duration=3):
    # collect some data before checking if the drone is ready
    deadline = (
        time.monotonic()
        + duration
    )

    while time.monotonic() < deadline:
        cache.update(timeout=0.2)


def get_battery_voltage(battery):
    # get battery voltage from BATTERY_STATUS
    if battery is None:
        return None

    voltages = getattr(
        battery,
        "voltages",
        None
    )

    if not voltages:
        return None

    # ignore values that mean voltage wasn't provided
    valid_voltages = [
        voltage
        for voltage in voltages
        if voltage not in (0, 65535)
    ]

    if not valid_voltages:
        return None

    voltage_mv = valid_voltages[0]

    # convert millivolts to volts
    return voltage_mv / 1000.0


def check_readiness(cache):
    reasons = []

    # check communication
    if not cache.heartbeat_is_recent():
        reasons.append(
            "Heartbeat is missing or stale."
        )

    # check ArduPilot pre-arm status and sensors
    sys_status = cache.get_fresh(
        "SYS_STATUS"
    )

    if sys_status is None:
        reasons.append(
            "SYS_STATUS telemetry is missing or stale."
        )

    else:
        prearm_bit = (
            mavutil.mavlink
            .MAV_SYS_STATUS_PREARM_CHECK
        )

        prearm_enabled = bool(
            sys_status
            .onboard_control_sensors_enabled
            & prearm_bit
        )

        prearm_healthy = bool(
            sys_status
            .onboard_control_sensors_health
            & prearm_bit
        )

        if not prearm_enabled:
            reasons.append(
                "ArduPilot pre-arm status is not available."
            )

        elif not prearm_healthy:
            reasons.append(
                "ArduPilot pre-arm checks are not passing."
            )

            # add the pre-arm error messages if we have them
            reasons.extend(
                cache.prearm_messages[-3:]
            )

        # check the important sensors that are enabled
        sensor_mask = (
            mavutil.mavlink
            .MAV_SYS_STATUS_SENSOR_3D_GYRO
            |
            mavutil.mavlink
            .MAV_SYS_STATUS_SENSOR_3D_ACCEL
            |
            mavutil.mavlink
            .MAV_SYS_STATUS_SENSOR_3D_MAG
            |
            mavutil.mavlink
            .MAV_SYS_STATUS_SENSOR_ABSOLUTE_PRESSURE
            |
            mavutil.mavlink
            .MAV_SYS_STATUS_SENSOR_GPS
        )

        enabled_sensors = (
            sys_status
            .onboard_control_sensors_enabled
            & sensor_mask
        )

        healthy_sensors = (
            sys_status
            .onboard_control_sensors_health
            & sensor_mask
        )

        unhealthy_sensors = (
            enabled_sensors
            & ~healthy_sensors
        )

        if unhealthy_sensors:
            reasons.append(
                "One or more enabled flight sensors "
                "are unhealthy."
            )

    # check main battery
    battery = cache.get_fresh(
        "BATTERY_STATUS"
    )

    if battery is None:
        reasons.append(
            "Battery telemetry is missing or stale."
        )

    else:
        battery_voltage = get_battery_voltage(
            battery
        )

        if battery_voltage is None:
            reasons.append(
                "Main battery voltage is unavailable."
            )

        elif battery_voltage < MIN_LAUNCH_VOLTAGE:
            reasons.append(
                f"Main battery voltage is too low: "
                f"{battery_voltage:.2f} V. "
                f"Minimum launch voltage is "
                f"{MIN_LAUNCH_VOLTAGE:.2f} V."
            )

    # check GPS
    gps = cache.get_fresh(
        "GPS_RAW_INT"
    )

    if gps is None:
        reasons.append(
            "GPS telemetry is missing or stale."
        )

    elif gps.fix_type < 3:
        reasons.append(
            f"GPS does not have a 3D fix. "
            f"fix_type={gps.fix_type}"
        )

    # make sure we have a position
    position = cache.get_fresh(
        "GLOBAL_POSITION_INT"
    )

    if position is None:
        reasons.append(
            "Position estimate is missing or stale."
        )

    # anything in reasons means we aren't ready
    if reasons:
        return False, reasons

    return True, []


def wait_for_readiness(cache):
    # give the drone time to become ready but don't wait forever
    deadline = (
        time.monotonic()
        + READINESS_TIMEOUT
    )

    while time.monotonic() < deadline:
        cache.update(
            timeout=0.2
        )

        ready, reasons = check_readiness(
            cache
        )

        if ready:
            return True, []

    return check_readiness(cache)


class OperatorInput:
    # temporary terminal input until backend confirmation is connected

    def __init__(self):
        self.responses = queue.Queue()

        # read CONFIRM or CANCEL without stopping telemetry checks
        thread = threading.Thread(
            target=self._read_input,
            daemon=True
        )

        thread.start()

    def _read_input(self):
        while True:
            try:
                response = (
                    input()
                    .strip()
                    .upper()
                )

                self.responses.put(
                    response
                )

            except EOFError:
                return

    def get_response(self):
        try:
            return (
                self.responses
                .get_nowait()
            )

        except queue.Empty:
            return None


def wait_for_operator_confirmation(
    cache,
    operator_input
):
    print("Drone is READY.")

    print(
        "Type CONFIRM to continue "
        "or CANCEL to stop."
    )

    deadline = (
        time.monotonic()
        + CONFIRMATION_TIMEOUT
    )

    while time.monotonic() < deadline:

        # update MAVLink data while we wait
        cache.update(
            timeout=0.2
        )

        # if something changes the drone isn't ready anymore
        ready, reasons = check_readiness(
            cache
        )

        if not ready:
            return make_status(
                "NOT_READY",
                reason=(
                    "Readiness was lost while "
                    "waiting for operator confirmation."
                ),
                reasons=reasons
            )

        response = (
            operator_input
            .get_response()
        )

        if response == "CANCEL":
            return make_status(
                "CANCELLED",
                reason=(
                    "Operator cancelled launch."
                )
            )

        if response == "CONFIRM":
            return make_status(
                "CONFIRMED",
                reason=(
                    "Operator confirmed launch."
                )
            )

    return make_status(
        "CONFIRMATION_EXPIRED",
        reason=(
            "Operator confirmation expired."
        )
    )


def set_guided_mode(
    connection,
    cache
):
    # request GUIDED mode
    print(
        "Requesting GUIDED mode..."
    )

    mode_id = (
        connection
        .mode_mapping()
        .get("GUIDED")
    )

    if mode_id is None:
        raise RuntimeError(
            "GUIDED mode is not available."
        )

    connection.set_mode(
        mode_id
    )

    deadline = (
        time.monotonic()
        + MODE_TIMEOUT
    )

    # wait until ArduPilot actually reports GUIDED
    while time.monotonic() < deadline:
        cache.update(
            timeout=0.2
        )

        heartbeat = cache.get_fresh(
            "HEARTBEAT"
        )

        if heartbeat is None:
            continue

        mode = (
            mavutil
            .mode_string_v10(
                heartbeat
            )
        )

        if mode == "GUIDED":
            print(
                "GUIDED mode confirmed."
            )

            return

    raise RuntimeError(
        "Timed out waiting for GUIDED mode."
    )


def wait_for_command_ack(
    connection,
    command
):
    # make sure ArduPilot actually accepted the command
    deadline = (
        time.monotonic()
        + COMMAND_ACK_TIMEOUT
    )

    while time.monotonic() < deadline:
        ack = connection.recv_match(
            type="COMMAND_ACK",
            blocking=True,
            timeout=1
        )

        if ack is None:
            continue

        # this ACK was for a different command
        if ack.command != command:
            continue

        if (
            ack.result
            == mavutil.mavlink.MAV_RESULT_ACCEPTED
        ):
            return

        raise RuntimeError(
            f"Command {command} was rejected. "
            f"MAVLink result={ack.result}"
        )

    raise RuntimeError(
        f"Timed out waiting for acknowledgement "
        f"of command {command}."
    )


def arm(
    connection,
    cache
):
    # request normal arming, don't force arm
    print(
        "Requesting arm..."
    )

    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,

        mavutil.mavlink
        .MAV_CMD_COMPONENT_ARM_DISARM,

        0,

        1,  # arm
        0,  # normal arm, don't bypass checks

        0,
        0,
        0,
        0,
        0
    )

    # make sure ArduPilot accepted it
    wait_for_command_ack(
        connection,
        mavutil.mavlink
        .MAV_CMD_COMPONENT_ARM_DISARM
    )

    deadline = (
        time.monotonic()
        + ARM_TIMEOUT
    )

    # then make sure the heartbeat actually says we're armed
    while time.monotonic() < deadline:
        cache.update(
            timeout=0.2
        )

        heartbeat = cache.get_fresh(
            "HEARTBEAT"
        )

        if heartbeat is None:
            continue

        armed = bool(
            heartbeat.base_mode
            & mavutil.mavlink
            .MAV_MODE_FLAG_SAFETY_ARMED
        )

        if armed:
            print(
                "Drone armed."
            )

            return

    raise RuntimeError(
        "Arm command was accepted, "
        "but armed state was not confirmed."
    )


def takeoff(connection):
    # send the takeoff command with our target altitude
    print(
        f"Requesting takeoff to "
        f"{TARGET_ALTITUDE:.2f} meters "
        f"(30 feet)..."
    )

    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,

        mavutil.mavlink
        .MAV_CMD_NAV_TAKEOFF,

        0,
        0,
        0,
        0,
        0,
        0,
        0,

        TARGET_ALTITUDE
    )

    # make sure ArduPilot accepted the takeoff command
    wait_for_command_ack(
        connection,
        mavutil.mavlink
        .MAV_CMD_NAV_TAKEOFF
    )

    print(
        "Takeoff command accepted."
    )


def wait_for_target_altitude(
    connection
):
    # keep checking altitude until we reach 30 ft or time out
    print(
        "Monitoring altitude..."
    )

    deadline = (
        time.monotonic()
        + ALTITUDE_TIMEOUT
    )

    last_altitude_time = (
        time.monotonic()
    )

    while time.monotonic() < deadline:
        message = connection.recv_match(
            type="GLOBAL_POSITION_INT",
            blocking=True,
            timeout=1
        )

        if message is None:

            # don't fail from one missed message
            if (
                time.monotonic()
                - last_altitude_time
                > TELEMETRY_MAX_AGE
            ):
                raise RuntimeError(
                    "Altitude telemetry was lost "
                    "during takeoff."
                )

            continue

        last_altitude_time = (
            time.monotonic()
        )

        # relative_alt comes in millimeters so convert it to meters
        current_altitude = (
            message.relative_alt
            / 1000.0
        )

        print(
            f"Current altitude: "
            f"{current_altitude:.2f} meters"
        )

        if current_altitude >= (
            TARGET_ALTITUDE
            - ALTITUDE_TOLERANCE
        ):
            print(
                f"Target altitude reached: "
                f"{current_altitude:.2f} meters"
            )

            return current_altitude

    raise RuntimeError(
        "Timed out waiting to reach "
        "the target altitude."
    )


def run_launch(
    connection_address,
    baud_rate,
    execute_flight=False,
    allow_hardware_flight=False
):
    connection = None

    # keeps track of if takeoff already started
    airborne = False

    try:

        # launch request received
        report_status(
            make_status(
                "LAUNCH_REQUEST_RECEIVED"
            )
        )

        # connect to the Kakute
        connection = connect(
            connection_address,
            baud_rate
        )

        cache = TelemetryCache(
            connection
        )

        # get enough telemetry for the readiness check
        collect_telemetry(
            cache,
            duration=3
        )

        # check if we're ready
        ready, reasons = wait_for_readiness(
            cache
        )

        if not ready:
            status = make_status(
                "NOT_READY",
                reason=(
                    "Vehicle failed readiness checks."
                ),
                reasons=reasons
            )

            report_status(status)

            return status

        status = make_status(
            "READY",
            reason=(
                "Vehicle passed readiness checks."
            )
        )

        report_status(status)

        # wait for operator confirmation
        operator_input = OperatorInput()

        confirmation = (
            wait_for_operator_confirmation(
                cache,
                operator_input
            )
        )

        report_status(
            confirmation
        )

        if (
            confirmation["state"]
            != "CONFIRMED"
        ):
            return confirmation

        # check readiness again before doing anything
        ready, reasons = check_readiness(
            cache
        )

        if not ready:
            status = make_status(
                "NOT_READY",
                reason=(
                    "Readiness changed before launch."
                ),
                reasons=reasons
            )

            report_status(status)

            return status

        # don't actually fly unless it was specifically enabled
        if not execute_flight:
            status = make_status(
                "FLIGHT_DISABLED",
                reason=(
                    "Pre-launch checks passed, "
                    "but flight execution is disabled."
                )
            )

            report_status(status)

            return status

        # check if we're running SITL
        is_sitl = (
            connection_address.startswith(
                (
                    "tcp:",
                    "udp:",
                    "udpin:",
                    "udpout:"
                )
            )
        )

        # real hardware needs another explicit flag
        if (
            not is_sitl
            and not allow_hardware_flight
        ):
            status = make_status(
                "HARDWARE_FLIGHT_BLOCKED",
                reason=(
                    "Real hardware flight requires "
                    "explicit approval."
                )
            )

            report_status(status)

            return status

        # switch to GUIDED
        set_guided_mode(
            connection,
            cache
        )

        # arm
        arm(
            connection,
            cache
        )

        # send takeoff command
        takeoff(
            connection
        )

        # after this the drone could be in the air
        airborne = True

        # wait until we reach 30 ft
        altitude = wait_for_target_altitude(
            connection
        )

        # launch finished
        status = make_status(
            "LAUNCH_SUCCEEDED",
            reason=(
                "Target altitude reached."
            ),
            altitude_m=altitude
        )

        report_status(status)

        return status

    except Exception as error:

        # failure before takeoff
        if not airborne:
            status = make_status(
                "LAUNCH_FAILED",
                reason=str(error),
                airborne=False
            )

        # different status if takeoff already started
        else:
            status = make_status(
                "AIRBORNE_FAILURE",
                reason=str(error),
                airborne=True
            )

        report_status(status)

        return status

    finally:

        # always close the connection when we're done
        if connection is not None:
            try:
                connection.close()

                print(
                    "Flight controller "
                    "connection closed."
                )

            except Exception:
                pass


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "HawkEye Raspberry Pi launch sequence"
        )
    )

    parser.add_argument(
        "--connection",
        default=DEFAULT_CONNECTION,
        help=(
            "MAVLink connection. "
            "Pi: /dev/ttyACM0 "
            "SITL: tcp:127.0.0.1:5760"
        )
    )

    parser.add_argument(
        "--baud",
        type=int,
        default=DEFAULT_BAUD_RATE,
        help=(
            "Serial baud rate. "
            "Default: 115200"
        )
    )

    parser.add_argument(
        "--execute-flight",
        action="store_true",
        help=(
            "Enable arming and takeoff. "
            "Flight is disabled by default."
        )
    )

    parser.add_argument(
        "--allow-hardware-flight",
        action="store_true",
        help=(
            "Additional explicit opt-in required "
            "for real hardware flight."
        )
    )

    return parser.parse_args()


def main():
    args = parse_args()

    run_launch(
        connection_address=(
            args.connection
        ),
        baud_rate=(
            args.baud
        ),
        execute_flight=(
            args.execute_flight
        ),
        allow_hardware_flight=(
            args.allow_hardware_flight
        )
    )


if __name__ == "__main__":
    main()