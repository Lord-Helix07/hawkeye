#File Purpose:
#1. Opening one MAVLink connection to the Kakute.
#2. Reading messages from ArduPilot.
#3. Caching the newest message of each type.
#4. Rejecting old telemetry data.
#5. Decoding flight-controller status.
#6. Decoding position, speed, altitude, GPS, and battery data.
#7. Publishing combined telemetry to the backend.

#Only one process should read from the Kakute serial port.
#Launch, landing, and backend publishing should use this shared cache.

from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Optional, Tuple

from pymavlink import mavutil


DEFAULT_CONNECTION = os.getenv("MAVLINK_CONNECTION", "/dev/ttyACM0")
DEFAULT_BAUD_RATE = int(os.getenv("MAVLINK_BAUD_RATE", "115200"))
DEFAULT_BACKEND_URL = os.getenv(
    "BACKEND_TELEMETRY_URL",
    "http://127.0.0.1:8000/telemetry",
)

HEARTBEAT_TIMEOUT_SECONDS = 5.0
MESSAGE_HISTORY_SIZE = 200
DEFAULT_FRAME_MATCH_WINDOW_SECONDS = 2.0

MessageRecord = Tuple[Any, int, str]


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp for logs and backend payloads."""
    return datetime.now(timezone.utc).isoformat()


def timestamp() -> str:
    """Backward-compatible alias used by the other microcontroller files."""
    return utc_timestamp()


def _finite_float(value: Any) -> Optional[float]:
    """Convert a number to a JSON-safe float, or return None."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _finite_int(value: Any) -> Optional[int]:
    """Convert a number to a JSON-safe integer, or return None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _message_time_usec(message: Any) -> Optional[int]:
    """Return a MAVLink message's onboard timestamp in microseconds."""
    time_usec = getattr(message, "time_usec", None)
    if time_usec is not None:
        return _finite_int(time_usec)

    time_boot_ms = getattr(message, "time_boot_ms", None)
    if time_boot_ms is not None:
        value = _finite_int(time_boot_ms)
        return value * 1000 if value is not None else None

    return None


def base_status() -> Dict[str, Any]:
    """Create the common flight-controller status shape."""
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


def mock_status() -> Dict[str, Any]:
    """Return a deterministic status for development without hardware."""
    status = base_status()
    now = utc_timestamp()
    status.update(
        {
            "connected": True,
            "status": "connected",
            "flight_mode": "STABILIZE",
            "custom_mode": 0,
            "armed": False,
            "system_status": "STANDBY",
            "last_heartbeat": now,
            "stale": False,
        }
    )
    return status


class TelemetryCache:
    """Own one MAVLink connection and retain the newest telemetry messages."""

    def __init__(
        self,
        connection: Any,
        *,
        history_size: int = MESSAGE_HISTORY_SIZE,
        frame_match_window_seconds: float = DEFAULT_FRAME_MATCH_WINDOW_SECONDS,
    ) -> None:
        self.connection = connection
        self.history_size = max(1, int(history_size))
        self.frame_match_window_ns = int(
            max(0.0, float(frame_match_window_seconds)) * 1_000_000_000
        )
        self.messages: Dict[str, Any] = {}
        self.message_history: Dict[str, Deque[MessageRecord]] = defaultdict(
            lambda: deque(maxlen=self.history_size)
        )
        self.message_metadata: Dict[str, Dict[str, Any]] = {}
        self.prearm_messages: Deque[str] = deque(maxlen=20)
        self.last_heartbeat_monotonic_ns: Optional[int] = None
        self.last_heartbeat_time: Optional[str] = None
        self.last_error: Optional[str] = None

    def close(self) -> None:
        """Close the owned MAVLink connection safely."""
        close = getattr(self.connection, "close", None)
        if callable(close):
            close()

    def record_message(self, message: Any) -> None:
        """Store a message and receipt-time metadata."""
        message_type = message.get_type()
        if message_type == "BAD_DATA":
            return

        received_monotonic_ns = time.monotonic_ns()
        received_utc = utc_timestamp()
        source_time_usec = _message_time_usec(message)

        self.messages[message_type] = message
        self.message_history[message_type].append(
            (message, received_monotonic_ns, received_utc)
        )
        self.message_metadata[message_type] = {
            "received_timestamp": received_utc,
            "received_monotonic_ns": received_monotonic_ns,
            "source_time_usec": source_time_usec,
        }

        if message_type == "HEARTBEAT":
            self.last_heartbeat_monotonic_ns = received_monotonic_ns
            self.last_heartbeat_time = received_utc

        if message_type == "STATUSTEXT":
            text = str(getattr(message, "text", "")).rstrip("\x00")
            if text:
                self.prearm_messages.append(text)

    def update(self, timeout: float = 0.2, max_messages: int = 200) -> int:
        """Read available MAVLink messages and update the cache.

        Returns the number of valid messages recorded.  This is the only method
        that should read from the MAVLink connection in the shared architecture.
        """
        count = 0
        deadline = time.monotonic() + max(0.0, float(timeout))

        while count < max(1, int(max_messages)):
            remaining = max(0.0, deadline - time.monotonic())
            message = self.connection.recv_match(
                blocking=count == 0,
                timeout=remaining if count == 0 else 0,
            )
            if message is None:
                break
            self.record_message(message)
            count += 1

            if time.monotonic() >= deadline:
                break

        return count

    def get_message(self, message_type: str) -> Optional[Any]:
        """Return the newest cached message of a type."""
        return self.messages.get(message_type)

    def get_message_at(
        self,
        message_type: str,
        frame_timestamp_ns: Optional[int] = None,
        max_age_seconds: Optional[float] = None,
    ) -> Optional[Any]:
        """Return the message nearest to a camera frame timestamp.

        ``frame_timestamp_ns`` must come from ``time.monotonic_ns()`` on this
        same Raspberry Pi.  Matching uses Pi receipt timestamps, not unrelated
        FC boot clocks.  If no sample is close enough, None is returned.
        """
        record = self.get_message_record_at(
            message_type,
            frame_timestamp_ns,
            max_age_seconds,
        )
        return record[0] if record is not None else None

    def get_message_record_at(
        self,
        message_type: str,
        frame_timestamp_ns: Optional[int] = None,
        max_age_seconds: Optional[float] = None,
    ) -> Optional[MessageRecord]:
        """Return the selected message plus its matching receipt metadata."""
        history = self.message_history.get(message_type)
        if not history:
            return None
        if frame_timestamp_ns is None:
            return history[-1]

        target = int(frame_timestamp_ns)
        record = min(history, key=lambda item: abs(item[1] - target))
        max_age_ns = self.frame_match_window_ns
        if max_age_seconds is not None:
            max_age_ns = int(max(0.0, float(max_age_seconds)) * 1_000_000_000)
        return record if abs(record[1] - target) <= max_age_ns else None

    def get_message_metadata_at(
        self,
        message_type: str,
        frame_timestamp_ns: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return metadata belonging to the sample selected for a frame."""
        record = self.get_message_record_at(message_type, frame_timestamp_ns)
        if record is None:
            return {
                "received_timestamp": None,
                "received_monotonic_ns": None,
                "source_time_usec": None,
            }
        message, received_monotonic_ns, received_utc = record
        return {
            "received_timestamp": received_utc,
            "received_monotonic_ns": received_monotonic_ns,
            "source_time_usec": _message_time_usec(message),
        }

    def get_message_timestamp(self, message_type: str) -> Dict[str, Any]:
        """Return receipt and MAVLink-source timestamps for a message type."""
        metadata = self.message_metadata.get(message_type)
        if metadata is None:
            return {
                "received_timestamp": None,
                "received_monotonic_ns": None,
                "source_time_usec": None,
            }
        return dict(metadata)

    def heartbeat_is_recent(self) -> bool:
        """Return whether a heartbeat arrived within the timeout window."""
        if self.last_heartbeat_monotonic_ns is None:
            return False
        age = (time.monotonic_ns() - self.last_heartbeat_monotonic_ns) / 1e9
        return age <= HEARTBEAT_TIMEOUT_SECONDS

    def get_flight_controller_status(self) -> Dict[str, Any]:
        """Convert the newest HEARTBEAT into backend-ready status."""
        status = base_status()
        heartbeat = self.get_message("HEARTBEAT")
        if heartbeat is None or not self.heartbeat_is_recent():
            status.update(
                {
                    "status": "heartbeat_timeout"
                    if heartbeat is not None
                    else "waiting_for_heartbeat",
                    "last_heartbeat": self.last_heartbeat_time,
                    "error": self.last_error,
                }
            )
            return status

        armed_flag = mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        status.update(
            {
                "connected": True,
                "status": "connected",
                "flight_mode": mavutil.mode_string_v10(heartbeat),
                "custom_mode": _finite_int(getattr(heartbeat, "custom_mode", None)),
                "armed": bool(heartbeat.base_mode & armed_flag),
                "system_status": system_status_name(
                    getattr(heartbeat, "system_status", None)
                ),
                "last_heartbeat": self.last_heartbeat_time,
                "stale": False,
                "error": None,
            }
        )
        return status

    def get_attitude(self, frame_timestamp_ns: Optional[int] = None) -> Dict[str, Any]:
        """Return roll, pitch, and yaw from ATTITUDE in degrees."""
        attitude = self.get_message_at("ATTITUDE", frame_timestamp_ns)
        data = self.get_message_metadata_at("ATTITUDE", frame_timestamp_ns)
        if attitude is None:
            return {
                "roll_deg": None,
                "pitch_deg": None,
                "yaw_deg": None,
                "timestamp": data,
            }
        return {
            "roll_deg": _finite_float(math.degrees(attitude.roll)),
            "pitch_deg": _finite_float(math.degrees(attitude.pitch)),
            "yaw_deg": _finite_float(math.degrees(attitude.yaw)),
            "timestamp": data,
        }

    def get_imu(self, frame_timestamp_ns: Optional[int] = None) -> Dict[str, Any]:
        """Return HIGHRES_IMU acceleration and angular velocity.

        Accelerometer units are m/s^2. Gyroscope units are rad/s. ArduPilot
        may not stream HIGHRES_IMU unless its message rate is configured.
        """
        imu = self.get_message_at("HIGHRES_IMU", frame_timestamp_ns)
        metadata = self.get_message_metadata_at("HIGHRES_IMU", frame_timestamp_ns)
        if imu is None:
            return {
                "accelerometer_mps2": {"x": None, "y": None, "z": None},
                "gyroscope_rads": {"x": None, "y": None, "z": None},
                "timestamp": metadata,
            }
        return {
            "accelerometer_mps2": {
                "x": _finite_float(getattr(imu, "xacc", None)),
                "y": _finite_float(getattr(imu, "yacc", None)),
                "z": _finite_float(getattr(imu, "zacc", None)),
            },
            "gyroscope_rads": {
                "x": _finite_float(getattr(imu, "xgyro", None)),
                "y": _finite_float(getattr(imu, "ygyro", None)),
                "z": _finite_float(getattr(imu, "zgyro", None)),
            },
            "timestamp": metadata,
        }

    def get_telemetry_snapshot(
        self,
        frame_timestamp_ns: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Build a snapshot of position, motion, battery, attitude, and IMU."""
        position = self.get_message_at("GLOBAL_POSITION_INT", frame_timestamp_ns)
        gps = self.get_message_at("GPS_RAW_INT", frame_timestamp_ns)
        hud = self.get_message_at("VFR_HUD", frame_timestamp_ns)
        battery = self.get_message_at("BATTERY_STATUS", frame_timestamp_ns)

        snapshot: Dict[str, Any] = {
            "timestamp": utc_timestamp(),
            "position": {
                "latitude_deg": None,
                "longitude_deg": None,
                "altitude_m": None,
                "relative_altitude_m": None,
                "timestamp": self.get_message_metadata_at(
                    "GLOBAL_POSITION_INT", frame_timestamp_ns
                ),
            },
            "motion": {
                "speed_mps": None,
                "heading_deg": None,
                "timestamp": self.get_message_metadata_at(
                    "GLOBAL_POSITION_INT", frame_timestamp_ns
                ),
            },
            "gps": {
                "fix_type": _finite_int(getattr(gps, "fix_type", None)) if gps else None,
                "satellites_visible": _finite_int(getattr(gps, "satellites_visible", None)) if gps else None,
                "timestamp": self.get_message_metadata_at(
                    "GPS_RAW_INT", frame_timestamp_ns
                ),
            },
            "battery": {
                "percentage": None,
                "voltage_v": None,
                "current_a": None,
                "timestamp": self.get_message_metadata_at(
                    "BATTERY_STATUS", frame_timestamp_ns
                ),
            },
            "attitude": self.get_attitude(frame_timestamp_ns),
            "imu": self.get_imu(frame_timestamp_ns),
        }

        if position is not None:
            snapshot["position"].update(
                {
                    "latitude_deg": _finite_float(position.lat / 1e7),
                    "longitude_deg": _finite_float(position.lon / 1e7),
                    "altitude_m": _finite_float(position.alt / 1000.0),
                    "relative_altitude_m": _finite_float(position.relative_alt / 1000.0),
                }
            )
            vx = _finite_float(getattr(position, "vx", None))
            vy = _finite_float(getattr(position, "vy", None))
            if vx is not None and vy is not None:
                snapshot["motion"]["speed_mps"] = math.hypot(vx, vy) / 100.0
            hdg = _finite_float(getattr(position, "hdg", None))
            if hdg is not None and hdg != 65535:
                snapshot["motion"]["heading_deg"] = hdg / 100.0

        if hud is not None:
            snapshot["motion"]["speed_mps"] = _finite_float(
                getattr(hud, "groundspeed", None)
            )
            snapshot["motion"]["heading_deg"] = _finite_float(
                getattr(hud, "heading", None)
            )

        if battery is not None:
            voltages = getattr(battery, "voltages", []) or []
            valid_voltages = [v for v in voltages if v not in (None, 0, 65535)]
            if valid_voltages:
                snapshot["battery"]["voltage_v"] = _finite_float(
                    sum(valid_voltages) / 1000.0
                )
            current_centiamp = _finite_float(
                getattr(battery, "current_battery", None)
            )
            if current_centiamp is not None and current_centiamp != -1:
                snapshot["battery"]["current_a"] = current_centiamp / 100.0
            remaining = _finite_float(getattr(battery, "battery_remaining", None))
            if remaining is not None and remaining >= 0:
                snapshot["battery"]["percentage"] = remaining

        return snapshot

    def get_readiness(self) -> Dict[str, Any]:
        """Return basic readiness information for launch-sequence callers."""
        status = self.get_flight_controller_status()
        gps = self.get_message("GPS_RAW_INT")
        fix_type = _finite_int(getattr(gps, "fix_type", None)) if gps else None
        return {
            "ready": bool(status["connected"] and not status["armed"] and fix_type and fix_type >= 3),
            "heartbeat_recent": self.heartbeat_is_recent(),
            "gps_fix_type": fix_type,
            "prearm_messages": list(self.prearm_messages),
        }

    def build_backend_payload(
        self,
        *,
        mission_id: Optional[str] = None,
        frame_id: Optional[str] = None,
        frame_timestamp_ns: Optional[int] = None,
        bounding_box: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build the shared payload consumed by the backend and camera system."""
        return {
            "drone_id": os.getenv("DRONE_ID", "drone-01"),
            "mission_id": mission_id,
            "frame": {
                "frame_id": frame_id,
                "frame_timestamp_ns": frame_timestamp_ns,
                "bounding_box": bounding_box,
            },
            "flight_controller": self.get_flight_controller_status(),
            "telemetry": self.get_telemetry_snapshot(frame_timestamp_ns),
            "readiness": self.get_readiness(),
            "published_timestamp": utc_timestamp(),
        }


def system_status_name(status_number: Any) -> str:
    """Convert MAVLink MAV_STATE values to readable names."""
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


def connect_telemetry(connection_address: str, baud_rate: int) -> TelemetryCache:
    """Open one MAVLink connection and return its shared cache."""
    connection = mavutil.mavlink_connection(
        connection_address,
        baud=int(baud_rate),
        autoreconnect=True,
    )
    return TelemetryCache(connection)


def publish_payload(backend_url: str, payload: Dict[str, Any], timeout: float = 3.0) -> bool:
    """POST one JSON payload. Return False when the backend is unavailable."""
    request = urllib.request.Request(
        backend_url,
        data=json.dumps(payload, allow_nan=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            print(f"Telemetry published with HTTP {response.status}")
            return 200 <= response.status < 300
    except urllib.error.HTTPError as error:
        print(f"Backend rejected telemetry: HTTP {error.code}")
    except urllib.error.URLError as error:
        print(f"Could not reach backend: {error}")
    except OSError as error:
        print(f"Telemetry publish failed: {error}")
    return False


def mock_payload() -> Dict[str, Any]:
    """Create a backend-shaped payload without a flight controller."""
    now = utc_timestamp()
    return {
        "drone_id": os.getenv("DRONE_ID", "drone-01"),
        "mission_id": None,
        "frame": {"frame_id": None, "frame_timestamp_ns": None, "bounding_box": None},
        "flight_controller": mock_status(),
        "telemetry": {
            "timestamp": now,
            "position": {
                "latitude_deg": None,
                "longitude_deg": None,
                "altitude_m": None,
                "relative_altitude_m": None,
            },
            "motion": {"speed_mps": 0.0, "heading_deg": 0.0},
            "gps": {"fix_type": None, "satellites_visible": None, "timestamp": {}},
            "battery": {"percentage": None, "voltage_v": None, "current_a": None, "timestamp": {}},
            "attitude": {
                "roll_deg": 0.0,
                "pitch_deg": 0.0,
                "yaw_deg": 0.0,
                "timestamp": {},
            },
            "imu": {
                "accelerometer_mps2": {"x": 0.0, "y": 0.0, "z": 9.81},
                "gyroscope_rads": {"x": 0.0, "y": 0.0, "z": 0.0},
                "timestamp": {},
            },
        },
        "readiness": {"ready": False, "heartbeat_recent": True, "gps_fix_type": None, "prearm_messages": []},
        "published_timestamp": now,
    }


def run_mock_mode(backend_url: str, interval: float) -> None:
    """Continuously print and publish mock telemetry until Ctrl+C."""
    try:
        while True:
            payload = mock_payload()
            print(json.dumps(payload, indent=2))
            publish_payload(backend_url, payload)
            time.sleep(max(0.05, interval))
    except KeyboardInterrupt:
        print("Stopping mock telemetry publisher.")


def run_telemetry_publisher(
    connection_address: str,
    baud_rate: int,
    backend_url: str,
    interval: float = 1.0,
) -> None:
    """Standalone loop that owns the connection and publishes snapshots."""
    cache: Optional[TelemetryCache] = None
    try:
        cache = connect_telemetry(connection_address, baud_rate)
        while True:
            cache.update(timeout=min(0.2, max(0.01, interval)))
            payload = cache.build_backend_payload()
            print(json.dumps(payload, indent=2))
            publish_payload(backend_url, payload)
            time.sleep(max(0.05, interval))
    except KeyboardInterrupt:
        print("Stopping telemetry publisher.")
    except (OSError, ValueError) as error:
        print(f"Telemetry connection failed: {error}")
    finally:
        if cache is not None:
            cache.close()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shared ArduPilot telemetry publisher")
    parser.add_argument("--connection", default=DEFAULT_CONNECTION)
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD_RATE)
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--mock", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    if args.mock:
        run_mock_mode(args.backend_url, args.interval)
    else:
        run_telemetry_publisher(
            args.connection,
            args.baud,
            args.backend_url,
            args.interval,
        )


if __name__ == "__main__":
    main()

    main()