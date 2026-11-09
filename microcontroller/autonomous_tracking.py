from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional

if __package__:
    from . import fc_status, heartbeat
else:
    import fc_status
    import heartbeat


# ---------------------------------------------------------------------------
# GPS and camera-ray geometry
# ---------------------------------------------------------------------------


GPSPoint = tuple[float, float]  # (latitude, longitude), degrees.
EARTH_RADIUS_M = 6_371_000.0


def _finite(value: Any) -> Optional[float]:
    """Convert a value to a finite float, or reject it."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _wrap180(angle: float) -> float:
    """Return an angle in the range [-180, 180)."""
    return (angle + 180.0) % 360.0 - 180.0


def distance_m(point_a: GPSPoint, point_b: GPSPoint) -> float:
    """Return the great-circle distance between two GPS points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*point_a, *point_b))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(max(0.0, value)))


def bearing_deg(point_a: GPSPoint, point_b: GPSPoint) -> float:
    """Return the initial compass bearing from point A to point B."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*point_a, *point_b))
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def project_point(origin: GPSPoint, bearing: float, distance: float) -> GPSPoint:
    """Project a GPS point from origin along a bearing for distance metres."""
    lat1, lon1, angle = math.radians(origin[0]), math.radians(origin[1]), math.radians(bearing)
    angular_distance = max(0.0, distance) / EARTH_RADIUS_M
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(angle)
    )
    lon2 = lon1 + math.atan2(
        math.sin(angle) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), (math.degrees(lon2) + 540.0) % 360.0 - 180.0


def _valid_bbox(bbox: Any, image_width: Any, image_height: Any = None) -> bool:
    """Check only the box geometry needed to create a camera ray."""
    if not isinstance(bbox, dict):
        return False
    values = [_finite(bbox.get(key)) for key in ("x1", "y1", "x2", "y2")]
    width = _finite(image_width)
    height = _finite(image_height) if image_height is not None else None
    if any(value is None for value in values) or width is None:
        return False
    x1, y1, x2, y2 = values
    horizontal_valid = width > 0 and 0 <= x1 < x2 <= width
    vertical_valid = height is None or (height > 0 and 0 <= y1 < y2 <= height)
    return horizontal_valid and vertical_valid


def camera_ray_bearing(bbox: dict, image_width: float, drone_heading_deg: float,
                       horizontal_fov_deg: float = 70.0) -> float:
    """Convert a bounding-box ray into a compass bearing.

    The ray passes through the detected vehicle box, not through the image
    center. The box center is used only as the ray's intersection point.
    """
    if not _valid_bbox(bbox, image_width):
        raise ValueError("invalid vehicle bounding box")
    center_x = (float(bbox["x1"]) + float(bbox["x2"])) / 2.0
    image_error = (center_x - float(image_width) / 2.0) / (float(image_width) / 2.0)
    ray_offset = image_error * float(horizontal_fov_deg) / 2.0
    return (float(drone_heading_deg) + ray_offset) % 360.0


def otw_check(
    point_a: GPSPoint,
    point_b: GPSPoint,
    new_bbox: dict | None,
    image_width: float,
    drone_heading_deg: float,
    old_bbox: dict | None = None,
    *,
    direction_threshold_deg: float = 20.0,
    horizontal_fov_deg: float = 70.0,
) -> tuple[GPSPoint, dict[str, Any]]:
    """Redirect B when a new frame shows a substantially different ray.

    If the backend later supplies the vehicle's actual GPS coordinates, those
    coordinates should replace the projected destination returned here.
    """
    route_bearing = bearing_deg(point_a, point_b)
    if not new_bbox:
        return point_b, {"changed": False, "reason": "no vehicle box"}

    new_bearing = camera_ray_bearing(new_bbox, image_width, drone_heading_deg, horizontal_fov_deg)
    reference = route_bearing
    if old_bbox and _valid_bbox(old_bbox, image_width):
        reference = camera_ray_bearing(old_bbox, image_width, drone_heading_deg, horizontal_fov_deg)

    change = abs(_wrap180(new_bearing - reference))
    if change <= direction_threshold_deg:
        return point_b, {"changed": False, "direction_change_deg": change}

    # Keep the A-to-B range, but place B on the new camera ray.
    redirected = project_point(point_a, new_bearing, distance_m(point_a, point_b))
    return redirected, {
        "changed": True,
        "old_bearing_deg": reference,
        "new_bearing_deg": new_bearing,
        "direction_change_deg": change,
    }


# ---------------------------------------------------------------------------
# Point-A-to-point-B guidance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """Conservative GPS pursuit and command limits."""

    command_hz: float = 10.0
    target_timeout: float = 0.5
    horizontal_fov_deg: float = 70.0
    direction_threshold_deg: float = 20.0
    heading_deadband_deg: float = 8.0
    heading_gain: float = 0.02
    max_yaw_rate: float = 0.20
    distance_gain: float = 0.15
    max_forward_speed: float = 1.0
    max_acceleration: float = 0.5

    def __post_init__(self) -> None:
        for name in ("command_hz", "target_timeout", "horizontal_fov_deg",
                     "heading_gain", "max_yaw_rate", "distance_gain",
                     "max_forward_speed", "max_acceleration"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.command_hz < 2 or self.heading_deadband_deg < 0 or self.direction_threshold_deg < 0:
            raise ValueError("invalid command frequency or angle thresholds")


DEFAULT_SETTINGS = Settings()


def a_to_b(
    point_a: GPSPoint,
    point_b: GPSPoint,
    bbox: dict | None,
    image_width: float,
    drone_heading_deg: float,
    old_bbox: dict | None = None,
    *,
    settings: Settings = DEFAULT_SETTINGS,
) -> dict[str, Any]:
    """Calculate one GPS pursuit command, calling ``otw_check`` first.

    Point A is the drone's current GPS position. Point B is the backend's
    destination GPS position. The returned forward speed is based on remaining
    GPS distance, while yaw is based on the desired GPS bearing. The camera ray
    can redirect B when the vehicle changes direction.
    """
    point_b, direction = otw_check(
        point_a, point_b, bbox, image_width, drone_heading_deg, old_bbox,
        direction_threshold_deg=settings.direction_threshold_deg,
        horizontal_fov_deg=settings.horizontal_fov_deg,
    )
    remaining = distance_m(point_a, point_b)
    desired_bearing = bearing_deg(point_a, point_b) if remaining > 0.01 else drone_heading_deg
    heading_error = _wrap180(desired_bearing - drone_heading_deg)
    yaw_rate = 0.0 if abs(heading_error) <= settings.heading_deadband_deg else (
        max(-settings.max_yaw_rate, min(settings.max_yaw_rate, settings.heading_gain * heading_error))
    )

    # Advance toward B using GPS distance, but reduce forward speed while turning.
    alignment = max(0.0, 1.0 - abs(heading_error) / 90.0)
    forward_speed = min(settings.max_forward_speed, settings.distance_gain * remaining) * alignment
    return {
        "destination": point_b,
        "distance_m": remaining,
        "bearing_deg": desired_bearing,
        "heading_error_deg": heading_error,
        "forward_speed_mps": forward_speed,
        "yaw_rate_rads": yaw_rate,
        "direction_check": direction,
    }


# Compatibility name for callers that previously used calculate_motion().
def calculate_motion(point_a: GPSPoint, point_b: GPSPoint, bbox: dict | None,
                     image_width: float, drone_heading_deg: float,
                     old_bbox: dict | None = None,
                     settings: Settings = DEFAULT_SETTINGS) -> tuple[float, float]:
    """Return GPS-based ``(forward_mps, yaw_rads)`` for one frame."""
    command = a_to_b(point_a, point_b, bbox, image_width, drone_heading_deg, old_bbox, settings=settings)
    return command["forward_speed_mps"], command["yaw_rate_rads"]


# ---------------------------------------------------------------------------
# Shared-cache controller
# ---------------------------------------------------------------------------


class AutonomousTracking:
    """Run GPS pursuit repeatedly using camera boxes as direction updates."""

    def __init__(self, cache: Any, *, send_commands: bool = False,
                 settings: Settings = DEFAULT_SETTINGS) -> None:
        required = ("connection", "write_lock", "get_message", "get_flight_controller_status")
        if not all(hasattr(cache, name) for name in required):
            raise TypeError("cache must be the shared TelemetryCache")
        self.cache, self.cfg = cache, settings
        self.send_commands = bool(send_commands)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._command: Optional[dict[str, Any]] = None
        self._last_bbox: Optional[dict] = None
        self._last_frame_time = float("-inf")
        self._forward_sent = 0.0
        self._active = False
        self._closed = False
        self._next_send = 0.0
        self._thread: Optional[threading.Thread] = None
        self.error: Optional[BaseException] = None

    def set_enabled(self, enabled: bool) -> None:
        """Change command authority and require a fresh camera frame."""
        with self._lock:
            if self._closed:
                raise RuntimeError("tracking is closed")
            was_active = self._active
            self.send_commands = bool(enabled)
            self._command = None
            self._last_bbox = None
            self._last_frame_time = time.monotonic()
            self._forward_sent = 0.0
            self._active = False
            self._next_send = 0.0
            if was_active:
                self._send_command(0.0, 0.0)

    def set_frame_result(self, result: dict[str, Any], captured_at: float) -> bool:
        """Process one camera/GPS result without reading MAVLink.

        Required result fields: ``frame``, ``target``, ``gps``, ``destination``,
        and ``heading_deg``. GPS fields are (latitude, longitude) pairs.
        """
        try:
            frame = result["frame"]
            height, width = frame.shape[:2]
            point_a = tuple(result["gps"])
            point_b = tuple(result["destination"])
            heading = float(result["heading_deg"])
        except (KeyError, AttributeError, TypeError, ValueError) as error:
            raise ValueError("result needs frame, target, gps, destination, and heading_deg") from error
        return self.set_target(result.get("target"), width, height, captured_at,
                               point_a, point_b, heading)

    def set_target(self, bbox: dict | None, image_width: float, image_height: float,
                   captured_at: float, point_a: GPSPoint, point_b: GPSPoint,
                   drone_heading_deg: float) -> bool:
        """Accept one selected vehicle box and its current GPS route data."""
        del image_height  # The horizontal camera ray needs only image width.
        stamp = _finite(captured_at)
        with self._lock:
            if self._closed or stamp is None or stamp <= self._last_frame_time:
                return False
            self._last_frame_time = stamp
            if time.monotonic() - stamp > self.cfg.target_timeout:
                self._command = None
                return False

            self._command = a_to_b(
                point_a, point_b, bbox, image_width, drone_heading_deg,
                self._last_bbox, settings=self.cfg,
            )
            self._last_bbox = bbox
            return True

    def status(self) -> dict[str, Any]:
        """Return the latest cached flight-controller status."""
        return fc_status.get_fc_status(self.cache)

    def _ready(self, state: dict[str, Any]) -> bool:
        """Allow pursuit only for an armed ArduCopter in GUIDED mode."""
        message = self.cache.get_message("HEARTBEAT")
        return bool(state.get("connected") and state.get("armed") is True
                    and state.get("flight_mode") == "GUIDED"
                    and getattr(message, "type", None) == 2)

    def _send_command(self, yaw_rate: float, forward_speed: float) -> bool:
        """Write one bounded BODY_NED velocity command through the shared cache."""
        with self.cache.write_lock:
            if not self._ready(self.status()):
                return False
            link = self.cache.connection
            link.mav.set_position_target_local_ned_send(
                int(time.monotonic() * 1000) & 0xFFFFFFFF,
                link.target_system, link.target_component,
                8, 1479, 0, 0, 0, forward_speed, 0, 0, 0, 0, 0, yaw_rate,
            )
        return True

    def step(self) -> dict[str, Any]:
        """Send one command using the newest GPS/camera calculation."""
        with self._lock:
            state = self.status()
            command = self._command
            ready = self._ready(state)
            now = time.monotonic()
            if command is None or now - self._last_frame_time > self.cfg.target_timeout:
                requested_forward = yaw_rate = 0.0
                fresh = False
            else:
                requested_forward = command["forward_speed_mps"]
                yaw_rate = command["yaw_rate_rads"]
                fresh = True

            if self._active and not ready:
                self.send_commands = False
                self._active = False
                self._forward_sent = 0.0
                requested_forward = yaw_rate = 0.0
                fresh = False

            forward_speed = 0.0
            if fresh:
                increment = self.cfg.max_acceleration / self.cfg.command_hz
                forward_speed = min(requested_forward, self._forward_sent + increment)

            sent = False
            if self.send_commands and ready and (fresh or self._active) and now >= self._next_send:
                sent = self._send_command(yaw_rate, forward_speed)
                if sent:
                    self._active = True
                    self._forward_sent = forward_speed
                self._next_send = now + 1.0 / self.cfg.command_hz
            return {"flight_controller": state, "target_fresh": fresh,
                    "forward_speed_mps": forward_speed, "yaw_rate_rads": yaw_rate,
                    "destination": command.get("destination") if command else None,
                    "distance_m": command.get("distance_m") if command else None,
                    "direction_check": command.get("direction_check") if command else None,
                    "commands_enabled": self.send_commands, "sent": sent}

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                logging.info("%s", self.step())
                self._stop.wait(1.0 / self.cfg.command_hz)
        except BaseException as error:
            self.error = error
            logging.exception("tracking worker stopped")
        finally:
            try:
                self.set_enabled(False)
            except BaseException:
                logging.exception("tracking shutdown failed")

    def start(self) -> None:
        """Start the repeated tracking loop once."""
        with self._lock:
            if self._closed or self._thread is not None:
                raise RuntimeError("create a new tracker to restart")
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def close(self) -> None:
        """Stop tracking and send zero motion when possible."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            if self._thread.is_alive():
                raise RuntimeError("tracking worker did not stop")
        with self._lock:
            if not self._closed:
                if self._active:
                    self._send_command(0.0, 0.0)
                self.send_commands = False
                self._active = False
                self._closed = True


def run_pursuit(results: Iterable[tuple[dict[str, Any], float]], cache: Any, *,
                backend_url: str = heartbeat.DEFAULT_BACKEND_URL,
                mission_id: Optional[str] = None, send_commands: bool = False,
                settings: Settings = DEFAULT_SETTINGS) -> None:
    """Run one telemetry reader, one tracker, and a stream of camera results."""
    stop = threading.Event()
    tracker = AutonomousTracking(cache, send_commands=send_commands, settings=settings)
    reader = threading.Thread(
        target=fc_status.monitor_status,
        args=(cache, stop),
        kwargs={"backend_url": backend_url, "mission_id": mission_id},
        daemon=True,
    )
    try:
        reader.start()
        tracker.start()
        for result, captured_at in results:
            if tracker.error:
                raise RuntimeError("tracking worker failed") from tracker.error
            if not reader.is_alive():
                raise RuntimeError("shared telemetry reader stopped")
            tracker.set_frame_result(result, captured_at)
    finally:
        tracker.close()
        stop.set()
        if reader.ident is not None:
            reader.join(timeout=5.0)
            if reader.is_alive():
                raise RuntimeError("shared telemetry reader did not stop")


# ---------------------------------------------------------------------------
# Hardware-free terminal test
# ---------------------------------------------------------------------------


def main() -> None:
    """Print one sample GPS/camera-ray calculation without hardware."""
    point_a = (37.000000, -122.000000)  # Sample drone GPS position.
    point_b = (37.001000, -122.000000)  # Sample backend destination.
    old_bbox = {"x1": 315, "y1": 100, "x2": 325, "y2": 200}
    new_bbox = {"x1": 600, "y1": 100, "x2": 620, "y2": 200}

    result = a_to_b(
        point_a=point_a,
        point_b=point_b,
        bbox=new_bbox,
        image_width=640,
        drone_heading_deg=0.0,
        old_bbox=old_bbox,
    )

    print("Hardware-free autonomous tracking test")
    print(f"Destination:       {result['destination']}")
    print(f"Remaining distance: {result['distance_m']:.2f} m")
    print(f"Route bearing:      {result['bearing_deg']:.2f} degrees")
    print(f"Heading error:      {result['heading_error_deg']:.2f} degrees")
    print(f"Forward speed:      {result['forward_speed_mps']:.2f} m/s")
    print(f"Yaw rate:           {result['yaw_rate_rads']:.3f} rad/s")
    print(f"Direction changed:  {result['direction_check']['changed']}")


if __name__ == "__main__":
    main()