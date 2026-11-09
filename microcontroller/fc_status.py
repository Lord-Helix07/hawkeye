import json
import time
from datetime import datetime, timezone

from pymavlink import mavutil


MOCK_MODE = False
FC_PORT = "/dev/ttyACM0"
BAUD_RATE = 115200
HEARTBEAT_TIMEOUT = 5
# Seconds. A heartbeat or position older than this is not current.
FRESH_SECONDS = 5
DRAIN_WINDOW = 0.3


#check if the heartbeat is fresh
def fresh(seen_at, now, limit=None):
    """True when seen_at is inside the shared freshness window."""
    if limit is None:
        limit = FRESH_SECONDS
    return seen_at is not None and now - seen_at <= limit


#check if the drone is armed
def armed(heartbeat):
    """True when this heartbeat has the safety-armed flag set."""
    return bool(heartbeat.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)


def mode_name(heartbeat):
    """ArduPilot mode string from a heartbeat."""
    return mavutil.mode_string_v10(heartbeat)


def mode_number(link, name):
    """Mode id from the flight controller map, or None when it is absent."""
    return (link.mode_mapping() or {}).get(name)


def ack_verdict(message, command):
    """Classify a COMMAND_ACK for this command.

    None means this frame is not that command's reply. IN_PROGRESS is
    not acceptance and not rejection. Any other result is REJECTED.
    """
    if message is None or message.get_type() != "COMMAND_ACK":
        return None
    if message.command != command:
        return None
    result = message.result
    if result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
        return "ACCEPTED"
    if result == mavutil.mavlink.MAV_RESULT_IN_PROGRESS:
        return "IN_PROGRESS"
    return "REJECTED"


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


def _status_timeout(last_heartbeat_time=None):
    status = {
        "connected": False,
        "status": "heartbeat_timeout" if last_heartbeat_time else "initial_heartbeat_timeout",
        "flight_mode": "UNKNOWN",
        "armed": None,
        "system_status": "UNKNOWN",
        "stale": True,
    }
    if last_heartbeat_time:
        status["last_heartbeat"] = last_heartbeat_time
    return status


def get_status_from_fc():
    """Read one status sample through the shared flight-controller cache.

    The first heartbeat still has 10 seconds to arrive. The following
    heartbeat has HEARTBEAT_TIMEOUT. The link is closed before return.
    """
    from flight_controller import fc_connection

    print("Waiting for flight-controller heartbeat...")
    cache = fc_connection.open_link(FC_PORT, BAUD_RATE)
    try:
        deadline = time.monotonic() + 10
        initial = None
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            message = fc_connection.read(cache, min(1, max(0.0, remaining)))
            if message is not None and message.get_type() == "HEARTBEAT":
                initial = message
                break
        if initial is None:
            return _status_timeout()

        last_heartbeat = time.monotonic()
        last_heartbeat_time = timestamp()
        while True:
            if time.monotonic() - last_heartbeat > HEARTBEAT_TIMEOUT:
                return _status_timeout(last_heartbeat_time)
            remaining = HEARTBEAT_TIMEOUT - (time.monotonic() - last_heartbeat)
            message = fc_connection.read(cache, min(1, max(0.0, remaining)))
            if message is None or message.get_type() != "HEARTBEAT":
                continue
            last_heartbeat_time = timestamp()
            return {
                "connected": True,
                "status": "connected",
                "flight_mode": mode_name(message),
                "custom_mode": message.custom_mode,
                "armed": armed(message),
                "system_status": message.system_status,
                "last_heartbeat": last_heartbeat_time,
                "stale": False,
            }
    finally:
        fc_connection.close_link(cache)


def main():
    if MOCK_MODE:
        status = mock_status()
    else:
        status = get_status_from_fc()

    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
