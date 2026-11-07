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


import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from pymavlink import mavutil



# Default configuration


DEFAULT_CONNECTION = "/dev/ttyACM0"
DEFAULT_BAUD_RATE = 115200

DEFAULT_BACKEND_URL = (
    "http://127.0.0.1:8000/flight-controller/status"
)

# Maximum acceptable age for different MAVLink messages.
HEARTBEAT_MAX_AGE = 5.0
TELEMETRY_MAX_AGE = 5.0

# How often the combined telemetry is published.
DEFAULT_PUBLISH_INTERVAL = 1.0



# Utility functions


def utc_timestamp():
    """Return the current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def system_status_name(status_number):
    """Convert MAVLink system status numbers into readable text."""
    statuses = {
        mavutil.mavlink.MAV_STATE_UNINIT: "UNINIT",
        mavutil.mavlink.MAV_STATE_BOOT: "BOOT",
        mavutil.mavlink.MAV_STATE_CALIBRATING: "CALIBRATING",
        mavutil.mavlink.MAV_STATE_STANDBY: "STANDBY",
        mavutil.mavlink.MAV_STATE_ACTIVE: "ACTIVE",
        mavutil.mavlink.MAV_STATE_CRITICAL: "CRITICAL",
        mavutil.mavlink.MAV_STATE_EMERGENCY: "EMERGENCY",
        mavutil.mavlink.MAV_STATE_POWEROFF: "POWEROFF",
        mavutil.mavlink.MAV_STATE_FLIGHT_TERMINATION:
            "FLIGHT_TERMINATION",
    }

    return statuses.get(status_number, "UNKNOWN")


def battery_voltage_from_message(message):
    """
    Get battery voltage in volts.

    BATTERY_STATUS.voltages uses millivolts.
    Values 0 and 65535 mean that voltage is unavailable.
    """
    if message is None:
        return None

    voltages = getattr(message, "voltages", None)

    if voltages:
        valid_voltages = [
            voltage
            for voltage in voltages
            if voltage not in (0, 65535)
        ]

        if valid_voltages:
            return valid_voltages[0] / 1000.0

    # Fallback for SYS_STATUS.
    voltage_battery = getattr(
        message,
        "voltage_battery",
        None,
    )

    if voltage_battery not in (None, 0, 65535):
        return voltage_battery / 1000.0

    return None


def battery_current_from_message(message):
    """
    Get battery current in amps.

    MAVLink battery current is normally centiamps.
    """
    if message is None:
        return None

    current = getattr(
        message,
        "current_battery",
        None,
    )

    if current in (None, -1, 65535):
        return None

    return current / 100.0

# Shared telemetry cache


class TelemetryCache:
    """
    Reads and stores the newest MAVLink messages.

    Launch and landing code can use this same object instead
    of opening separate connections to the Kakute.
    """

    def __init__(
        self,
        connection,
        drone_id="drone-01",
    ):
        self.connection = connection
        self.drone_id = drone_id

        # Stores:
        #     "HEARTBEAT": (message, receive_time),
        #     "GPS_RAW_INT": (message, receive_time)

        self.messages = {}

        self.last_heartbeat_time = None
        self.last_heartbeat_timestamp = None

        # Recent ArduPilot pre-arm messages.
        self.prearm_messages = []

    def record_message(self, message):
        """Store one MAVLink message in the cache."""
        if message is None:
            return

        message_type = message.get_type()
        receive_time = time.monotonic()

        self.messages[message_type] = (
            message,
            receive_time,
        )

        if message_type == "HEARTBEAT":
            self.last_heartbeat_time = receive_time
            self.last_heartbeat_timestamp = utc_timestamp()

        if message_type == "STATUSTEXT":
            raw_text = getattr(message, "text", "")

            if isinstance(raw_text, bytes):
                text = raw_text.decode(
                    "utf-8",
                    errors="replace",
                )
            else:
                text = str(raw_text)

            if "PreArm:" in text:
                self.prearm_messages.append(text)

                # Keep only the latest five messages.
                self.prearm_messages = (
                    self.prearm_messages[-5:]
                )

    def update(self, timeout=0.2):
        """
        Read one MAVLink message from the connection.

        Returns the message if one was received.
        Returns None if the read timed out.
        """
        message = self.connection.recv_match(
            blocking=True,
            timeout=timeout,
        )

        if message is not None:
            self.record_message(message)

        return message

    def collect(self, duration=3.0):
        """Collect messages for a specified amount of time."""
        deadline = time.monotonic() + duration

        while time.monotonic() < deadline:
            self.update(timeout=0.2)

    def get_fresh(
        self,
        message_type,
        max_age=TELEMETRY_MAX_AGE,
    ):
        """
        Return a message only if it is recent enough.

        Returning None prevents the system from using old telemetry.
        """
        stored = self.messages.get(message_type)

        if stored is None:
            return None

        message, received_time = stored

        age = time.monotonic() - received_time

        if age > max_age:
            return None

        return message

    def message_age(self, message_type):
        """Return the age of a cached message in seconds."""
        stored = self.messages.get(message_type)

        if stored is None:
            return None

        _, received_time = stored
        return time.monotonic() - received_time

    def heartbeat_is_recent(self):
        """Return whether the FC heartbeat is still recent."""
        if self.last_heartbeat_time is None:
            return False

        age = time.monotonic() - self.last_heartbeat_time

        return age <= HEARTBEAT_MAX_AGE


    # Flight-controller status


    def get_flight_controller_status(self):
        """
        Decode heartbeat information.

        This produces the status needed by fc_status_updated.py.
        """
        heartbeat = self.get_fresh(
            "HEARTBEAT",
            HEARTBEAT_MAX_AGE,
        )

        if heartbeat is None:
            status = "heartbeat_timeout"

            if self.last_heartbeat_time is None:
                status = "initial_heartbeat_timeout"

            return {
                "drone_id": self.drone_id,
                "connected": False,
                "status": status,
                "flight_mode": "UNKNOWN",
                "custom_mode": None,
                "armed": None,
                "system_status": "UNKNOWN",
                "last_heartbeat": (
                    self.last_heartbeat_timestamp
                ),
                "stale": True,
                "error": "Heartbeat is missing or stale.",
            }

        armed_flag = (
            mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        )

        return {
            "drone_id": self.drone_id,
            "connected": True,
            "status": "connected",
            "flight_mode": mavutil.mode_string_v10(
                heartbeat
            ),
            "custom_mode": int(
                heartbeat.custom_mode
            ),
            "armed": bool(
                heartbeat.base_mode & armed_flag
            ),
            "system_status": system_status_name(
                heartbeat.system_status
            ),
            "last_heartbeat": (
                self.last_heartbeat_timestamp
            ),
            "stale": False,
            "error": None,
        }


    # Battery telemetry

    def get_battery_telemetry(self):
        """
        Decode battery information from BATTERY_STATUS.

        Falls back to SYS_STATUS if necessary.
        """
        battery = self.get_fresh(
            "BATTERY_STATUS"
        )

        if battery is None:
            battery = self.get_fresh(
                "SYS_STATUS"
            )

        if battery is None:
            return {
                "battery_pct": None,
                "battery_voltage": None,
                "battery_current": None,
            }

        battery_percentage = getattr(
            battery,
            "battery_remaining",
            None,
        )

        if battery_percentage in (-1, 255):
            battery_percentage = None

        return {
            "battery_pct": battery_percentage,
            "battery_voltage": (
                battery_voltage_from_message(battery)
            ),
            "battery_current": (
                battery_current_from_message(battery)
            ),
        }


    # GPS and position telemetry


    def get_position_telemetry(self):
        """
        Decode GPS and position data.

        GLOBAL_POSITION_INT:
        - lat/lon are scaled by 1e7
        - relative_alt is millimeters
        - vx/vy are centimeters per second
        """
        position = self.get_fresh(
            "GLOBAL_POSITION_INT"
        )

        gps = self.get_fresh(
            "GPS_RAW_INT"
        )

        result = {
            "latitude": None,
            "longitude": None,
            "altitude_m": None,
            "speed_mps": None,
            "heading_deg": None,
            "gps_fix_type": None,
            "satellites_visible": None,
        }

        if position is not None:
            result["latitude"] = position.lat / 1e7
            result["longitude"] = position.lon / 1e7
            result["altitude_m"] = (
                position.relative_alt / 1000.0
            )

            vx = getattr(position, "vx", None)
            vy = getattr(position, "vy", None)

            if vx is not None and vy is not None:
                horizontal_speed_cm_s = math.sqrt(
                    (vx * vx) + (vy * vy)
                )

                result["speed_mps"] = (
                    horizontal_speed_cm_s / 100.0
                )

            heading = getattr(
                position,
                "hdg",
                None,
            )

            if heading not in (None, 65535):
                result["heading_deg"] = heading / 100.0

        if gps is not None:
            result["gps_fix_type"] = gps.fix_type

            satellites = getattr(
                gps,
                "satellites_visible",
                None,
            )

            if satellites != 255:
                result["satellites_visible"] = satellites

        # VFR_HUD can provide a better speed/heading value.
        vfr_hud = self.get_fresh("VFR_HUD")

        if vfr_hud is not None:
            if getattr(vfr_hud, "groundspeed", None) is not None:
                result["speed_mps"] = (
                    vfr_hud.groundspeed
                )

            if getattr(vfr_hud, "heading", None) is not None:
                result["heading_deg"] = (
                    vfr_hud.heading
                )

            if result["altitude_m"] is None:
                result["altitude_m"] = (
                    vfr_hud.alt
                )

        return result


    # Sensor and readiness information


    def get_sensor_status(self):
        """
        Decode ArduPilot sensor health from SYS_STATUS.
        """
        system_status = self.get_fresh(
            "SYS_STATUS"
        )

        if system_status is None:
            return {
                "available": False,
                "healthy": False,
                "sensors": {},
            }

        sensor_flags = {
            "gyro": (
                mavutil.mavlink
                .MAV_SYS_STATUS_SENSOR_3D_GYRO
            ),
            "accelerometer": (
                mavutil.mavlink
                .MAV_SYS_STATUS_SENSOR_3D_ACCEL
            ),
            "magnetometer": (
                mavutil.mavlink
                .MAV_SYS_STATUS_SENSOR_3D_MAG
            ),
            "barometer": (
                mavutil.mavlink
                .MAV_SYS_STATUS_SENSOR_ABSOLUTE_PRESSURE
            ),
            "gps": (
                mavutil.mavlink
                .MAV_SYS_STATUS_SENSOR_GPS
            ),
        }

        sensor_results = {}

        for name, flag in sensor_flags.items():
            enabled = bool(
                system_status
                .onboard_control_sensors_enabled
                & flag
            )

            healthy = bool(
                system_status
                .onboard_control_sensors_health
                & flag
            )

            sensor_results[name] = {
                "enabled": enabled,
                "healthy": healthy,
            }

        prearm_flag = (
            mavutil.mavlink.MAV_SYS_STATUS_PREARM_CHECK
        )

        prearm_enabled = bool(
            system_status
            .onboard_control_sensors_enabled
            & prearm_flag
        )

        prearm_healthy = bool(
            system_status
            .onboard_control_sensors_health
            & prearm_flag
        )

        return {
            "available": True,
            "healthy": all(
                sensor["healthy"]
                for sensor in sensor_results.values()
                if sensor["enabled"]
            ),
            "prearm_enabled": prearm_enabled,
            "prearm_healthy": prearm_healthy,
            "sensors": sensor_results,
            "prearm_messages": (
                self.prearm_messages[-3:]
            ),
        }

    def get_readiness(self):
        """
        Return basic readiness information.

        This does not arm or launch the drone.
        The launch sequence can add operator confirmation
        and project-specific safety checks.
        """
        reasons = []

        fc_status = (
            self.get_flight_controller_status()
        )

        telemetry = (
            self.get_telemetry_snapshot()
        )

        sensors = (
            self.get_sensor_status()
        )

        if not fc_status["connected"]:
            reasons.append(
                "Flight-controller heartbeat is missing."
            )

        if telemetry["battery_pct"] is None:
            reasons.append(
                "Battery percentage is unavailable."
            )

        if telemetry["battery_voltage"] is None:
            reasons.append(
                "Battery voltage is unavailable."
            )

        if telemetry["gps_fix_type"] is None:
            reasons.append(
                "GPS telemetry is unavailable."
            )
        elif telemetry["gps_fix_type"] < 3:
            reasons.append(
                "GPS does not have a 3D fix."
            )

        if telemetry["latitude"] is None:
            reasons.append(
                "Position telemetry is unavailable."
            )

        if not sensors["available"]:
            reasons.append(
                "Sensor status is unavailable."
            )
        elif not sensors["healthy"]:
            reasons.append(
                "One or more sensors are unhealthy."
            )

        if sensors.get("prearm_enabled") and not sensors.get(
            "prearm_healthy"
        ):
            reasons.append(
                "ArduPilot pre-arm checks are not passing."
            )

        return {
            "ready_for_launch": len(reasons) == 0,
            "reasons": reasons,
        }

    # Combined backend payload


    def get_telemetry_snapshot(self):
        """
        Build the telemetry section sent to the backend.
        """
        position = self.get_position_telemetry()
        battery = self.get_battery_telemetry()

        return {
            **position,
            **battery,
            "timestamp": utc_timestamp(),
        }

    def build_backend_payload(
        self,
        mission_id=None,
    ):
        """
        Build one complete payload for the backend.
        """
        return {
            "drone_id": self.drone_id,
            "mission_id": mission_id,
            "flight_controller": (
                self.get_flight_controller_status()
            ),
            "telemetry": (
                self.get_telemetry_snapshot()
            ),
            "readiness": (
                self.get_readiness()
            ),
        }

    def close(self):
        """Safely close the MAVLink connection."""
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass



# Connection and publishing


def connect_telemetry(
    connection_address=DEFAULT_CONNECTION,
    baud_rate=DEFAULT_BAUD_RATE,
    drone_id=None,
    heartbeat_timeout=10,
):
    """
    Open one connection and wait for the first heartbeat.

    Returns a TelemetryCache that owns the connection.
    """
    if drone_id is None:
        drone_id = os.getenv(
            "DRONE_ID",
            "drone-01",
        )

    print(
        f"Connecting to flight controller at "
        f"{connection_address}..."
    )

    connection = None

    try:
        connection = mavutil.mavlink_connection(
            connection_address,
            baud=baud_rate,
        )

        heartbeat = connection.wait_heartbeat(
            timeout=heartbeat_timeout
        )

        if heartbeat is None:
            raise RuntimeError(
                "No initial heartbeat received."
            )

        cache = TelemetryCache(
            connection=connection,
            drone_id=drone_id,
        )

        # Store the heartbeat that was received while connecting.
        cache.record_message(heartbeat)

        print("Flight controller connected.")

        return cache

    except Exception:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

        raise


def publish_payload(backend_url, payload):
    """
    POST one telemetry payload to the backend.

    Backend failures are logged but do not crash
    the telemetry reader.
    """
    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        backend_url,
        data=data,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=3,
        ) as response:
            print(
                f"Telemetry published: HTTP "
                f"{response.status}"
            )

        return True

    except urllib.error.HTTPError as error:
        print(
            f"Backend rejected telemetry: "
            f"HTTP {error.code}"
        )

    except urllib.error.URLError as error:
        print(
            f"Could not reach telemetry backend: "
            f"{error}"
        )

    return False


def run_telemetry_publisher(
    cache,
    backend_url=DEFAULT_BACKEND_URL,
    mission_id=None,
    publish_interval=DEFAULT_PUBLISH_INTERVAL,
):
    """
    Continuously read MAVLink and publish snapshots.

    Use this only when this process owns the MAVLink connection.
    If launch or landing is already reading from the cache,
    they should call build_backend_payload() themselves.
    """
    next_publish_time = time.monotonic()

    try:
        while True:
            # Read one MAVLink message.
            # Repeating this keeps the cache current.
            cache.update(timeout=0.2)

            now = time.monotonic()

            if now >= next_publish_time:
                payload = cache.build_backend_payload(
                    mission_id=mission_id
                )

                print(json.dumps(payload, indent=2))

                publish_payload(
                    backend_url,
                    payload,
                )

                next_publish_time = (
                    now + publish_interval
                )

    except KeyboardInterrupt:
        print("Telemetry publisher stopped.")

    finally:
        cache.close()



# Standalone command-line use


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="HawkEye MAVLink telemetry service"
    )

    parser.add_argument(
        "--connection",
        default=os.getenv(
            "MAVLINK_CONNECTION",
            DEFAULT_CONNECTION,
        ),
        help=(
            "Examples: /dev/ttyACM0, "
            "tcp:127.0.0.1:5760, "
            "udp:127.0.0.1:14550"
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
        "--drone-id",
        default=os.getenv(
            "DRONE_ID",
            "drone-01",
        ),
    )

    parser.add_argument(
        "--mission-id",
        default=None,
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_PUBLISH_INTERVAL,
        help="Backend publishing interval in seconds",
    )

    return parser.parse_args()


def main():
    args = parse_arguments()

    cache = None

    try:
        cache = connect_telemetry(
            connection_address=args.connection,
            baud_rate=args.baud,
            drone_id=args.drone_id,
        )

        run_telemetry_publisher(
            cache=cache,
            backend_url=args.backend_url,
            mission_id=args.mission_id,
            publish_interval=args.interval,
        )

    except Exception as error:
        print(f"Telemetry service failed: {error}")

        if cache is not None:
            cache.close()


if __name__ == "__main__":
    main()