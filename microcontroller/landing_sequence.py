from pymavlink import mavutil
import argparse
import time


# default connection for the Pi and Kakute
DEFAULT_CONNECTION = "/dev/ttyACM0"
DEFAULT_BAUD_RATE = 115200

# SITL can use tcp:127.0.0.1:5760

# time limits
INITIAL_HEARTBEAT_TIMEOUT = 10
HEARTBEAT_MAX_AGE = 3.0
LAND_MODE_TIMEOUT = 10
LANDING_TIMEOUT = 90
TELEMETRY_MAX_AGE = 5.0

# used to tell when we're getting close to the ground
NEAR_GROUND_ALTITUDE = 0.5


def make_status(state, reason=None, **extra):
    # makes a status that backend can eventually use
    result = {
        "state": state,
        "reason": reason,
    }

    result.update(extra)

    return result


def report_status(status):
    # prints for now, backend can connect to this later
    print(status)


def connect(connection_address, baud_rate):
    # connect to the Kakute and wait for ArduPilot
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
            "No heartbeat received from flight controller."
        )

    print("Flight controller connected.")

    return connection


def get_heartbeat(connection, timeout=1):
    # get the newest heartbeat from ArduPilot
    return connection.recv_match(
        type="HEARTBEAT",
        blocking=True,
        timeout=timeout
    )


def is_armed(heartbeat):
    # check if the heartbeat says the drone is armed
    return bool(
        heartbeat.base_mode
        & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
    )


def check_communication(connection):
    # make sure the Pi can still talk to the Kakute
    heartbeat = get_heartbeat(
        connection,
        timeout=HEARTBEAT_MAX_AGE
    )

    if heartbeat is None:
        raise RuntimeError(
            "Flight controller heartbeat is missing."
        )

    return heartbeat


def request_land_mode(connection):
    # ask ArduPilot to start landing
    print("Requesting LAND mode...")

    mode_id = (
        connection
        .mode_mapping()
        .get("LAND")
    )

    if mode_id is None:
        raise RuntimeError(
            "LAND mode is not available."
        )

    connection.set_mode(mode_id)

    deadline = (
        time.monotonic()
        + LAND_MODE_TIMEOUT
    )

    # make sure ArduPilot actually switches to LAND
    while time.monotonic() < deadline:

        heartbeat = get_heartbeat(
            connection,
            timeout=1
        )

        if heartbeat is None:
            continue

        current_mode = (
            mavutil.mode_string_v10(
                heartbeat
            )
        )

        if current_mode == "LAND":
            print("LAND mode confirmed.")
            return

    raise RuntimeError(
        "Timed out waiting for LAND mode."
    )


def monitor_landing(connection):
    # watch altitude and armed state while the drone comes down
    print("Landing started. Monitoring descent...")

    deadline = (
        time.monotonic()
        + LANDING_TIMEOUT
    )

    last_altitude_time = time.monotonic()
    last_heartbeat_time = time.monotonic()

    current_altitude = None

    while time.monotonic() < deadline:

        message = connection.recv_match(
            type=[
                "GLOBAL_POSITION_INT",
                "HEARTBEAT"
            ],
            blocking=True,
            timeout=1
        )

        now = time.monotonic()

        if message is None:

            # stop trusting the connection if heartbeat disappears
            if (
                now - last_heartbeat_time
                > HEARTBEAT_MAX_AGE
            ):
                raise RuntimeError(
                    "Lost flight controller communication "
                    "during landing."
                )

            continue

        message_type = message.get_type()

        if message_type == "HEARTBEAT":

            last_heartbeat_time = now

            # ArduPilot should disarm after the drone lands
            if not is_armed(message):

                print("Drone is disarmed.")

                return make_status(
                    "LANDED",
                    reason=(
                        "Landing completed and "
                        "the drone is disarmed."
                    ),
                    altitude_m=current_altitude
                )

        elif message_type == "GLOBAL_POSITION_INT":

            last_altitude_time = now

            # relative_alt comes in millimeters
            current_altitude = (
                message.relative_alt
                / 1000.0
            )

            print(
                f"Current altitude: "
                f"{current_altitude:.2f} meters"
            )

            if (
                current_altitude
                <= NEAR_GROUND_ALTITUDE
            ):
                print(
                    "Drone is near the ground. "
                    "Waiting for disarm..."
                )

        # don't keep landing with old altitude data
        if (
            now - last_altitude_time
            > TELEMETRY_MAX_AGE
        ):
            raise RuntimeError(
                "Altitude telemetry was lost during landing."
            )

    raise RuntimeError(
        "Landing did not finish before timeout."
    )


def run_landing(
    connection_address,
    baud_rate,
    execute_landing=False,
    allow_hardware_landing=False
):
    # backend will call this after the officer clicks Land Drone
    connection = None
    landing_started = False

    try:

        # land request received from frontend/backend
        report_status(
            make_status(
                "LANDING_REQUEST_RECEIVED",
                reason=(
                    "Land Drone request received."
                )
            )
        )

        # connect to the Kakute
        connection = connect(
            connection_address,
            baud_rate
        )

        # make sure communication is working
        heartbeat = check_communication(
            connection
        )

        # if it's already disarmed there is nothing to land
        if not is_armed(heartbeat):

            status = make_status(
                "LANDING_NOT_REQUIRED",
                reason=(
                    "Drone is already disarmed."
                )
            )

            report_status(status)

            return status

        # landing is disabled unless specifically enabled
        if not execute_landing:

            status = make_status(
                "LANDING_DISABLED",
                reason=(
                    "Land Drone request received, "
                    "but landing execution is disabled."
                )
            )

            report_status(status)

            return status

        # check if we're using SITL
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
            and not allow_hardware_landing
        ):

            status = make_status(
                "HARDWARE_LANDING_BLOCKED",
                reason=(
                    "Real hardware landing requires "
                    "explicit approval."
                )
            )

            report_status(status)

            return status

        # clicking Land Drone is already the operator command
        # so there is no second confirmation step here

        # tell ArduPilot to land where the drone currently is
        request_land_mode(
            connection
        )

        # LAND mode is confirmed so the drone should be descending
        landing_started = True

        report_status(
            make_status(
                "LANDING",
                reason=(
                    "LAND mode confirmed. "
                    "Drone is descending."
                )
            )
        )

        # monitor until the drone lands and disarms
        status = monitor_landing(
            connection
        )

        report_status(status)

        return status

    except Exception as error:

        # landing command never successfully started
        if not landing_started:

            status = make_status(
                "LANDING_FAILED_TO_START",
                reason=str(error)
            )

        # LAND already started so the drone may be descending
        else:

            status = make_status(
                "LANDING_FAILURE",
                reason=str(error)
            )

        report_status(status)

        return status

    finally:

        # always close the MAVLink connection when we're done
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
            "HawkEye landing sequence"
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
        default=DEFAULT_BAUD_RATE
    )

    parser.add_argument(
        "--execute-landing",
        action="store_true",
        help=(
            "Enable landing. "
            "Disabled by default."
        )
    )

    parser.add_argument(
        "--allow-hardware-landing",
        action="store_true",
        help=(
            "Extra opt-in required for "
            "real hardware landing."
        )
    )

    return parser.parse_args()


def main():

    args = parse_args()

    run_landing(
        connection_address=(
            args.connection
        ),
        baud_rate=(
            args.baud
        ),
        execute_landing=(
            args.execute_landing
        ),
        allow_hardware_landing=(
            args.allow_hardware_landing
        )
    )


if __name__ == "__main__":
    main()