
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


def make_status(state, reason=None, **extra):
    result = {
        "state": state,
        "reason": reason,
    }
    result.update(extra)
    return result


def report_status(status):
    # backend can use these statuses later
    print(json.dumps(status, default=str))


def connect(connection_address, baud_rate):
    # connect to the Kakute and wait for heartbeat
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
        # keep the original error if close also fails
        try:
            connection.close()
        except Exception:
            pass
        raise


def is_armed(heartbeat):
    return bool(
        heartbeat.base_mode
        & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
    )


class LandingTelemetry:
    # save recent messages and when they arrived

    def __init__(self, connection):
        self.connection = connection
        self.messages = {}
        self.acks = []
        self.sequence = 0

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

        self.sequence += 1
        now = time.monotonic()

        self.messages[message_type] = (
            message,
            now,
            self.sequence
        )

        if message_type == "COMMAND_ACK":
            self.acks.append(
                (message, self.sequence)
            )
            self.acks = self.acks[-50:]

        return message

    def fresh(
        self,
        message_type,
        max_age=TELEMETRY_MAX_AGE
    ):
        stored = self.messages.get(message_type)

        if stored is None:
            return None

        message, received_at, _ = stored

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

        # relative altitude is only for monitoring
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
    # check freshness every loop
    if cache.heartbeat() is None:
        return "Heartbeat missing or stale"

    if cache.fresh("GLOBAL_POSITION_INT") is None:
        return "Altitude telemetry missing or stale"

    if cache.fresh("EXTENDED_SYS_STATE") is None:
        return "Landed-state telemetry missing or stale"

    return None


def prepare_mode_request(cache):
    # clear already buffered ACKs before sending
    deadline = time.monotonic() + 0.3

    while time.monotonic() < deadline:
        message = cache.update(timeout=0)

        if message is None:
            break

    cache.acks.clear()
    return cache.sequence


def request_land_mode(connection, cache):
    # check if LAND is available
    mode_map = connection.mode_mapping()

    if not mode_map or "LAND" not in mode_map:
        return make_status(
            "LANDING_NOT_AVAILABLE",
            "LAND mode mapping is unavailable.",
            request_attempted=False,
            request_sent=False,
            write_completed=False,
            land_confirmed=False
        )

    mode_id = mode_map["LAND"]

    if mode_id is None:
        return make_status(
            "LANDING_NOT_AVAILABLE",
            "LAND mode is unavailable.",
            request_attempted=False,
            request_sent=False,
            write_completed=False,
            land_confirmed=False
        )

    start_sequence = prepare_mode_request(cache)

    # keep track of whether the write finished
    request_attempted = True
    write_completed = False

    try:
        connection.set_mode(mode_id)
        write_completed = True

    except Exception as error:
        # a write error doesn't prove nothing was transmitted
        return make_status(
            "LANDING_OUTCOME_UNKNOWN",
            "LAND write outcome uncertain: " + str(error),
            request_attempted=request_attempted,
            request_sent=None,
            write_completed=False,
            land_confirmed=False
        )

    deadline = time.monotonic() + LAND_MODE_TIMEOUT
    ack_sequence = start_sequence
    interim_ack = False

    mode_command = (
        mavutil.mavlink.MAV_CMD_DO_SET_MODE
    )

    while time.monotonic() < deadline:
        try:
            cache.update(timeout=0.2)

        except Exception as error:
            return make_status(
                "LANDING_OUTCOME_UNKNOWN",
                "Telemetry error after LAND request: "
                + str(error),
                request_attempted=True,
                request_sent=True,
                write_completed=True,
                land_confirmed=False
            )

        heartbeat = cache.heartbeat()

        # heartbeat is the final check for actual mode
        if heartbeat is not None:
            current_mode = mavutil.mode_string_v10(
                heartbeat
            )

            if current_mode == "LAND":
                return make_status(
                    "LAND_CONFIRMED",
                    "ArduPilot reports LAND mode.",
                    request_attempted=True,
                    request_sent=True,
                    write_completed=True,
                    land_confirmed=True
                )

        # check any new ACKs for the mode command
        for ack, sequence in cache.acks:
            if sequence <= ack_sequence:
                continue

            ack_sequence = sequence

            if ack.command != mode_command:
                continue

            if (
                ack.result
                == mavutil.mavlink.MAV_RESULT_IN_PROGRESS
            ):
                interim_ack = True
                continue

            if (
                ack.result
                == mavutil.mavlink.MAV_RESULT_ACCEPTED
            ):
                # accepted still needs LAND telemetry
                continue

            return make_status(
                "LANDING_REJECTED",
                f"ArduPilot rejected LAND mode: "
                f"MAVLink result {ack.result}",
                request_attempted=True,
                request_sent=True,
                write_completed=True,
                land_confirmed=False
            )

    # silence doesn't prove LAND failed
    return make_status(
        "LANDING_OUTCOME_UNKNOWN",
        "LAND request completed but mode was not confirmed.",
        request_attempted=True,
        request_sent=True,
        write_completed=True,
        land_confirmed=False,
        interim_ack=interim_ack
    )


def monitor_landing(connection, cache):
    # monitor landing without changing motor commands
    deadline = time.monotonic() + LANDING_TIMEOUT

    on_ground = (
        mavutil.mavlink.MAV_LANDED_STATE_ON_GROUND
    )

    while time.monotonic() < deadline:
        try:
            cache.update(timeout=0.2)

        except Exception as error:
            return make_status(
                "LANDING_OUTCOME_UNKNOWN",
                "Telemetry error during landing: "
                + str(error),
                aircraft=get_aircraft_status(cache)
            )

        # check ages even when other messages arrive
        telemetry_error = check_telemetry(cache)

        if telemetry_error:
            return make_status(
                "LANDING_OUTCOME_UNKNOWN",
                telemetry_error,
                aircraft=get_aircraft_status(cache)
            )

        aircraft = get_aircraft_status(cache)

        # both disarmed and ON_GROUND are required
        if (
            aircraft["armed"] is False
            and aircraft["landed_state"] == on_ground
        ):
            return make_status(
                "LANDED",
                "On-ground state and disarming confirmed.",
                aircraft=aircraft
            )

        # don't override manual takeover or failsafe
        if aircraft["mode"] != "LAND":
            return make_status(
                "LANDING_CONTROL_CHANGED",
                "ArduPilot left LAND mode. No new command sent.",
                aircraft=aircraft
            )

    return make_status(
        "LANDING_OUTCOME_UNKNOWN",
        "Landing monitoring timed out. "
        "Aircraft may still be landing.",
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

    request_attempted = False
    write_completed = False

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

        # collect the first telemetry messages
        deadline = (
            time.monotonic() + TELEMETRY_MAX_AGE
        )

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
                "Current armed state is unknown.",
                request_sent=False
            )

        # disarmed alone doesn't prove landed
        if aircraft["armed"] is False:
            if (
                aircraft["landed_state"]
                == mavutil.mavlink.MAV_LANDED_STATE_ON_GROUND
            ):
                return make_status(
                    "LANDING_NOT_REQUIRED",
                    "Aircraft is already on ground and disarmed.",
                    request_sent=False
                )

            return make_status(
                "LANDING_OUTCOME_UNKNOWN",
                "Aircraft is disarmed, but ground state is not confirmed.",
                request_sent=False
            )

        if not execute_landing:
            return make_status(
                "LANDING_DISABLED",
                "Landing execution is disabled.",
                request_sent=False
            )

        # transport type doesn't prove it's SITL
        if simulation_confirmed == allow_hardware_landing:
            return make_status(
                "AUTHORIZATION_REQUIRED",
                "Select exactly one verified execution environment.",
                request_sent=False
            )

        telemetry_error = check_telemetry(cache)

        if telemetry_error:
            return make_status(
                "LANDING_OUTCOME_UNKNOWN",
                telemetry_error,
                request_sent=False
            )

        # the frontend button is already the operator request
        result = request_land_mode(
            connection,
            cache
        )

        request_attempted = result.get(
            "request_attempted", False
        )

        write_completed = result.get(
            "write_completed", False
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

        status = monitor_landing(
            connection,
            cache
        )

        return status

    except Exception as error:
        if request_attempted:
            return make_status(
                "LANDING_OUTCOME_UNKNOWN",
                str(error),
                request_attempted=True,
                request_sent=(
                    True if write_completed else None
                ),
                write_completed=write_completed
            )

        return make_status(
            "LANDING_FAILED_TO_START",
            str(error),
            request_attempted=False,
            request_sent=False
        )

    finally:
        # close the connection even if something fails
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
