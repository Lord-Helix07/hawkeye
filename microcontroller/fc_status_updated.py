import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import serial
from pymavlink import mavutil


DEFAULT_CONNECTION = "/dev/ttyACM0"
DEFAULT_BAUD_RATE = 115200
DEFAULT_BACKEND_URL = (
    "http://127.0.0.1:8000/flight-controller/status"
)

HEARTBEAT_TIMEOUT = 5
RECONNECT_DELAY = 2

#gets timestamp
def timestamp():
    """Return the current UTC time."""
    return datetime.now(timezone.utc).isoformat()


def base_status():
    """Create a consistent status format."""
    return {
        "drone_id": os.getenv("DRONE_ID", "drone-01"),
        "connected": False,
        "status": "unknown",
        "flight_mode": "UNKNOWN",
        "custom_mode": None,
        "armed": None,
        "system_status": "UNKNOWN",
        "last_heartbeat": None,
        "stale": True,
        "error": None,
    }

#Sets default values to test without physical access to the Pi
def mock_status():
    """Create fake FC status for local testing."""
    status = base_status()

    status.update({
        "connected": True,
        "status": "connected",
        "flight_mode": "STABILIZE",
        "custom_mode": 0,
        "armed": False,
        "system_status": "STANDBY",
        "last_heartbeat": timestamp(),
        "stale": False,
    })

    return status

#If the program runs into an issue reading the FC, it calls this function
def failure_status(status_name, error_message):
    """Create a consistent failure response."""
    status = base_status()
    status["status"] = status_name
    status["error"] = error_message
    return status


def system_status_name(status_number):
    """Convert ArduPilot's numeric status into readable text."""
    statuses = {
        mavutil.mavlink.MAV_STATE_UNINIT: "UNINIT",
        mavutil.mavlink.MAV_STATE_BOOT: "BOOT",
        mavutil.mavlink.MAV_STATE_CALIBRATING: "CALIBRATING",
        mavutil.mavlink.MAV_STATE_STANDBY: "STANDBY",
        mavutil.mavlink.MAV_STATE_ACTIVE: "ACTIVE",
        mavutil.mavlink.MAV_STATE_CRITICAL: "CRITICAL",
        mavutil.mavlink.MAV_STATE_EMERGENCY: "EMERGENCY",
        mavutil.mavlink.MAV_STATE_POWEROFF: "POWEROFF",
    }

    return statuses.get(status_number, "UNKNOWN")


def heartbeat_to_status(heartbeat, last_heartbeat_time):
    """Convert a MAVLink heartbeat into backend-ready JSON."""
    armed_flag = mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED

    status = base_status()

    status.update({
        "connected": True,
        "status": "connected",
        "flight_mode": mavutil.mode_string_v10(heartbeat),
        "custom_mode": int(heartbeat.custom_mode),
        "armed": bool(heartbeat.base_mode & armed_flag),
        "system_status": system_status_name(
            heartbeat.system_status
        ),
        "last_heartbeat": last_heartbeat_time,
        "stale": False,
    })

    return status

#dyanamoDb
def publish_status(backend_url, status):
    """Send the current status to the FastAPI backend."""
    payload = json.dumps(status).encode("utf-8")

    request = urllib.request.Request(
        backend_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            print(
                f"Status published to backend "
                f"with HTTP {response.status}"
            )

    except urllib.error.HTTPError as error:
        print(
            f"Backend rejected status: "
            f"HTTP {error.code}"
        )

    except urllib.error.URLError as error:
        print(f"Could not reach backend: {error}")

    except Exception as error:
        print(f"Unexpected publishing error: {error}")


def monitor_fc(
    connection_address,
    baud_rate,
    backend_url,
):
    """Continuously monitor the flight controller."""
    while True:
        connection = None

        try:
            print(
                f"Connecting to flight controller at "
                f"{connection_address}..."
            )

            connection = mavutil.mavlink_connection(
                connection_address,
                baud=baud_rate,
            )

            print("Waiting for first heartbeat...")

            heartbeat = connection.wait_heartbeat(
                timeout=10
            )

            if heartbeat is None:
                status = failure_status(
                    "initial_heartbeat_timeout",
                    "No heartbeat received within 10 seconds",
                )

                print(json.dumps(status, indent=2))
                publish_status(backend_url, status)

                time.sleep(RECONNECT_DELAY)
                continue

            print("Flight controller connected.")

            last_heartbeat_received = time.monotonic()
            last_heartbeat_time = timestamp()

            while True:
                heartbeat = connection.recv_match(
                    type="HEARTBEAT",
                    blocking=True,
                    timeout=1,
                )

                if heartbeat is not None:
                    last_heartbeat_received = (
                        time.monotonic()
                    )
                    last_heartbeat_time = timestamp()

                    status = heartbeat_to_status(
                        heartbeat,
                        last_heartbeat_time,
                    )

                    print(json.dumps(status, indent=2))
                    publish_status(backend_url, status)

                elapsed = (
                    time.monotonic()
                    - last_heartbeat_received
                )

                if elapsed > HEARTBEAT_TIMEOUT:
                    status = failure_status(
                        "heartbeat_timeout",
                        "No heartbeat received for 5 seconds",
                    )

                    status["last_heartbeat"] = (
                        last_heartbeat_time
                    )

                    print(json.dumps(status, indent=2))
                    publish_status(backend_url, status)

                    print("Heartbeat lost. Reconnecting...")
                    break

        except FileNotFoundError as error:
            status = failure_status(
                "connection_error",
                f"Connection address not found: {error}",
            )

            print(json.dumps(status, indent=2))
            publish_status(backend_url, status)

        except (serial.SerialException, OSError) as error:
            status = failure_status(
                "connection_error",
                f"Serial communication failed: {error}",
            )

            print(json.dumps(status, indent=2))
            publish_status(backend_url, status)

        except Exception as error:
            status = failure_status(
                "communication_error",
                f"Unexpected MAVLink error: {error}",
            )

            print(json.dumps(status, indent=2))
            publish_status(backend_url, status)

        except KeyboardInterrupt:
            print("Stopping flight-controller monitor.")
            break

        finally:
            if connection is not None:
                try:
                    connection.close()
                    print("Flight-controller connection closed.")
                except Exception:
                    pass

        time.sleep(RECONNECT_DELAY)


def run_mock_mode(backend_url):
    """Continuously publish fake statuses for testing."""
    try:
        while True:
            status = mock_status()

            print(json.dumps(status, indent=2))
            publish_status(backend_url, status)

            time.sleep(1)

    except KeyboardInterrupt:
        print("Stopping mock status publisher.")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Monitor ArduPilot FC status"
    )

    parser.add_argument(
        "--connection",
        default=os.getenv(
            "MAVLINK_CONNECTION",
            DEFAULT_CONNECTION,
        ),
        help=(
            "Connection address, such as "
            "/dev/ttyACM0 or udp:127.0.0.1:14550"
        ),
    )

    parser.add_argument(
        "--baud",
        type=int,
        default=int(
            os.getenv(
                "MAVLINK_BAUD_RATE",
                DEFAULT_BAUD_RATE,
            )
        ),
    )

    parser.add_argument(
        "--backend-url",
        default=os.getenv(
            "BACKEND_STATUS_URL",
            DEFAULT_BACKEND_URL,
        ),
    )

    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use fake status instead of real MAVLink data",
    )

    return parser.parse_args()


def main():
    args = parse_arguments()

    if args.mock:
        run_mock_mode(args.backend_url)
    else:
        monitor_fc(
            connection_address=args.connection,
            baud_rate=args.baud,
            backend_url=args.backend_url,
        )


if __name__ == "__main__":
    main()