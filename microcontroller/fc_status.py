import json
import time
from datetime import datetime, timezone

from pymavlink import mavutil


MOCK_MODE = False
FC_PORT = "/dev/ttyACM0"
BAUD_RATE = 115200
HEARTBEAT_TIMEOUT = 5


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def mock_status():
    return {
        "connected": True,
        "status": "connected",
        "flight_mode": "STABILIZE",
        "armed": False,
        "system_status": "STANDBY",
        "last_heartbeat": timestamp(),
        "stale": False,
    }


def get_status_from_fc():
    connection = mavutil.mavlink_connection(
        FC_PORT,
        baud=BAUD_RATE,
    )

    print("Waiting for flight-controller heartbeat...")

    heartbeat = connection.wait_heartbeat(timeout=10)

    if heartbeat is None:
        return {
            "connected": False,
            "status": "initial_heartbeat_timeout",
            "flight_mode": "UNKNOWN",
            "armed": None,
            "system_status": "UNKNOWN",
            "stale": True,
        }

    last_heartbeat = time.monotonic()
    last_heartbeat_time = timestamp()

    while True:
        heartbeat = connection.recv_match(
            type="HEARTBEAT",
            blocking=True,
            timeout=1,
        )

        if heartbeat is not None:
            last_heartbeat = time.monotonic()
            last_heartbeat_time = timestamp()

            armed_flag = mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
            armed = bool(heartbeat.base_mode & armed_flag)

            return {
                "connected": True,
                "status": "connected",
                "flight_mode": mavutil.mode_string_v10(heartbeat),
                "custom_mode": heartbeat.custom_mode,
                "armed": armed,
                "system_status": heartbeat.system_status,
                "last_heartbeat": last_heartbeat_time,
                "stale": False,
            }

        if time.monotonic() - last_heartbeat > HEARTBEAT_TIMEOUT:
            return {
                "connected": False,
                "status": "heartbeat_timeout",
                "flight_mode": "UNKNOWN",
                "armed": None,
                "system_status": "UNKNOWN",
                "last_heartbeat": last_heartbeat_time,
                "stale": True,
            }


def main():
    if MOCK_MODE:
        status = mock_status()
    else:
        status = get_status_from_fc()

    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
