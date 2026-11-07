
from pymavlink import mavutil
import argparse
import time
import json


# default connection for the Pi and Kakute
DEFAULT_CONNECTION = "/dev/ttyACM0"
DEFAULT_BAUD_RATE = 115200

# time limits
INITIAL_HEARTBEAT_TIMEOUT = 10
HEARTBEAT_MAX_AGE = 3.0
TELEMETRY_MAX_AGE = 5.0
LAND_MODE_TIMEOUT = 10
LANDING_TIMEOUT = 90

# flight commands are disabled unless specifically enabled


def make_status(state, reason=None, **extra):
    result = {
        "state": state,
        "reason": reason,
    }
    result.update(extra)
    return result


def report_status(status):
    # prints for now, backend can connect this later
    print(json.dumps(status, default=str))


def connect(connection_address, baud_rate):
    # connect to ArduPilot and wait for the first heartbeat
    connection = mavutil.mavlink_connection(
        connection_address,
        baud=baud_rate
    )

    try:
        heartbeat = connection.wait_heartbeat(
            timeout=INITIAL_HEARTBEAT_TIMEOUT
        )

        if heartbeat is None:
            raise RuntimeError(
                "No initial heartbeat received."
            )

        return connection

    except Exception:
        connection.close()
        raise


def is_armed(heartbeat):
    return bool(
        heartbeat.base_mode
        & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
    )


class LandingTelemetry:
    # stores the newest messages and when they arrived

    def __init__(self, connection):
        self.connection = connection
        self.messages = {}

    def update(self, timeout=0.2):
        message = self.connection.recv_match(
            blocking=True,
            timeout=timeout
        )

        if message is None:
            return None

        message_type = message.get_type()

        if message_type == "BAD_DATA":
            return None

        self.messages[message_type] = (
            message,
            time.monotonic()
        )

        return message

    def fresh(self, message_type, max_age=TELEMETRY_MAX_AGE):
        stored = self.messages.get(message_type)

        if stored is None:
            return None

        message, received_at = stored

        if time.monotonic() - received_at > max_age:
            return None

        return message

    def heartbeat(self):
        return self.fresh(
            "HEARTBEAT",
            HEARTBEAT_MAX_AGE
        )

    def altitude(self):
        position = self.fresh("GLOBAL_POSITION_INT")

        if position is None:
            return None

        # relative altitude is in millimeters
        return position.relative_alt / 1000.0

    def landed_state(self):
        message = self.fresh("EXTENDED_SYS_STATE")

        if message is None:
            return None

        return message.landed_state


def get_aircraft_status(cache):
    heartbeat = cache.heartbeat()

    if heartbeat is None:
        return {
            "armed": None,
            "mode": None,
            "altitude_m": cache.altitude(),
            "landed_state": cache.landed_state(),
        }

    return {
        "armed": is_armed(heartbeat),
        "mode": mavutil.mode_string_v10(heartbeat),
        "altitude_m": cache.altitude(),
        "landed_state": cache.landed_state(),
    }


def check_telemetry(cache):
    # check freshness even if other messages keep arriving
    if cache.heartbeat() is None:
        return "Heartbeat missing or stale"

    if cache.fresh("GLOBAL_POSITION_INT") is None:
        return "Altitude telemetry missing or stale"

    if cache.fresh("EXTENDED_SYS_STATE") is None:
        return "Landed-state telemetry missing or stale"

    return None


def request_land_mode(connection, cache):
    # ask ArduPilot to land at the current location
    mode_id = connection.mode_mapping().get("LAND")

    if mode_id is None:
        return make_status(
            "LANDING_NOT_AVAILABLE",
            "LAND mode is unavailable."
        )

    connection.set_mode(mode_id)

    deadline = time.monotonic() + LAND_MODE_TIMEOUT

    while time.monotonic() < deadline:
        cache.update()

        heartbeat = cache.heartbeat()

        if heartbeat is None:
            continue

        current_mode = mavutil.mode_string_v10(
            heartbeat
        )

        if current_mode == "LAND":
            return make_status(
                "LAND_CONFIRMED",
                "ArduPilot reports LAND mode."
            )

    # no confirmation does not mean the command failed
    return make_status(
        "LANDING_OUTCOME_UNKNOWN",
        "LAND was requested, but mode change was not confirmed.",
        request_sent=True
    )


def monitor_landing(connection, cache):
    # watch the aircraft until landing is verified or time runs out
    deadline = time.monotonic() + LANDING_TIMEOUT

    on_ground = mavutil.mavlink.MAV_LANDED_STATE_ON_GROUND

    while time.monotonic() < deadline:
        cache.update()

        # check freshness on every loop
        telemetry_error = check_telemetry(cache)

        if telemetry_error:
            return make_status(
                "LANDING_OUTCOME_UNKNOWN",
                telemetry_error,
                aircraft=get_aircraft_status(cache)
            )

        aircraft = get_aircraft_status(cache)

        # both landed state and disarming are required
        if (
            aircraft["armed"] is False
            and aircraft["landed_state"] == on_ground
        ):
            return make_status(
                "LANDED",
                "On-ground state and disarming confirmed.",
                aircraft=aircraft
            )

        # do not override manual control or failsafes
        if aircraft["mode"] != "LAND":
            return make_status(
                "LANDING_CONTROL_CHANGED",
                "ArduPilot left LAND mode. No new command sent.",
                aircraft=aircraft
            )

    return make_status(
        "LANDING_OUTCOME_UNKNOWN",
        "Landing monitoring timed out. Aircraft may still be landing.",
        aircraft=get_aircraft_status(cache)
    )


def run_landing(
    connection_address,
    baud_rate,
    execute_landing=False,
    simulation_confirmed=False,
    allow_hardware_landing=False
):
    connection = None
    cache = None
    request_sent = False

    try:
        report_status(
            make_status(
                "LANDING_REQUEST_RECEIVED",
                "Land Drone request received."
            )
        )

        connection = connect(
            connection_address,
            baud_rate
        )

        cache = LandingTelemetry(connection)

        # collect initial telemetry
        deadline = time.monotonic() + TELEMETRY_MAX_AGE

        while time.monotonic() < deadline:
            cache.update()

            if (
                cache.heartbeat() is not None
                and cache.fresh("GLOBAL_POSITION_INT") is not None
                and cache.fresh("EXTENDED_SYS_STATE") is not None
            ):
                break

        aircraft = get_aircraft_status(cache)

        if aircraft["armed"] is None:
            return make_status(
                "LANDING_OUTCOME_UNKNOWN",
                "Current armed state is unknown."
            )

        # don't assume disarmed automatically means landed
        if aircraft["armed"] is False:
            if (
                aircraft["landed_state"]
                == mavutil.mavlink.MAV_LANDED_STATE_ON_GROUND
            ):
                return make_status(
                    "LANDING_NOT_REQUIRED",
                    "Aircraft is already on ground and disarmed."
                )

            return make_status(
                "LANDING_OUTCOME_UNKNOWN",
                "Aircraft is disarmed, but ground state is not confirmed."
            )

        if not execute_landing:
            return make_status(
                "LANDING_DISABLED",
                "Landing execution is disabled."
            )

        # transport type does not prove simulation
        if simulation_confirmed == allow_hardware_landing:
            return make_status(
                "AUTHORIZATION_REQUIRED",
                "Select exactly one verified execution environment."
            )

        telemetry_error = check_telemetry(cache)

        if telemetry_error:
            return make_status(
                "LANDING_OUTCOME_UNKNOWN",
                telemetry_error
            )

        # clicking Land Drone is already the operator request
        request_sent = True

        result = request_land_mode(
            connection,
            cache
        )

        report_status(result)

        if result["state"] != "LAND_CONFIRMED":
            return result

        report_status(
            make_status(
                "LANDING",
                "LAND mode confirmed. Monitoring landing."
            )
        )

        return monitor_landing(
            connection,
            cache
        )

    except Exception as error:
        if request_sent:
            return make_status(
                "LANDING_OUTCOME_UNKNOWN",
                str(error),
                request_sent=True
            )

        return make_status(
            "LANDING_FAILED_TO_START",
            str(error),
            request_sent=False
        )

    finally:
        # close the connection whether landing succeeds or fails
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def parse_args():
    parser = argparse.ArgumentParser(
        description="Hawkeye landing sequence"
    )

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
        "--execute-landing",
        action="store_true"
    )

    parser.add_argument(
        "--simulation-confirmed",
        action="store_true"
    )

    parser.add_argument(
        "--allow-hardware-landing",
        action="store_true"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    result = run_landing(
        connection_address=args.connection,
        baud_rate=args.baud,
        execute_landing=args.execute_landing,
        simulation_confirmed=args.simulation_confirmed,
        allow_hardware_landing=args.allow_hardware_landing
    )

    report_status(result)


if __name__ == "__main__":
    main()
