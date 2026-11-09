"""Visual forward pursuit for Hawkeye.

This module owns target-to-motion calculations and the tracking control loop.
It does not open a MAVLink connection or read MAVLink messages. The caller
must provide the shared TelemetryCache and exactly one other owner must call
``cache.update()`` continuously.

The controller uses apparent target width as a distance estimate: a target
that is too small produces forward velocity, while horizontal image error
produces yaw rate. Forward motion is reduced while the target is off-center.
This is visual-size pursuit, not metric distance control.
"""

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


def _finite_float(value: Any) -> Optional[float]:
    """Return a finite float or ``None`` for invalid input."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


@dataclass(frozen=True)
class Settings:
    """Conservative starting values for visual forward pursuit."""

    command_hz: float = 10.0          # How often movement commands are sent.
    target_timeout: float = 0.5        # Maximum acceptable camera-result age.
    min_confidence: float = 0.60       # Minimum detector confidence.
    center_deadband: float = 0.10      # Ignore small left/right errors.
    yaw_gain: float = 0.35             # Converts image error into yaw rate.
    max_yaw_rate: float = 0.20         # Maximum yaw rate in radians/second.
    yaw_direction: int = 1             # Reverse this if the camera is mirrored.
    target_width_ratio: float = 0.25   # Desired target width / image width.
    width_deadband: float = 0.02       # Prevent tiny forward corrections.
    forward_gain: float = 4.0          # Converts size error into forward speed.
    max_forward_speed: float = 1.0     # Maximum forward speed in m/s.
    forward_alignment: float = 0.30    # Stop advancing when target is too far aside.
    max_acceleration: float = 0.5      # Maximum increase in forward speed per second.

    def __post_init__(self) -> None:
        # Reject unsafe or mathematically invalid tuning values immediately.
        positive = (
            "command_hz", "target_timeout", "yaw_gain", "max_yaw_rate",
            "forward_gain", "max_forward_speed", "max_acceleration",
        )
        for name in positive:
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.command_hz < 2:
            raise ValueError("command_hz must be at least 2 Hz")
        if self.yaw_direction not in (-1, 1):
            raise ValueError("yaw_direction must be -1 or 1")
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        if not 0 <= self.center_deadband < 1:
            raise ValueError("center_deadband must be between 0 and 1")
        if not 0 < self.target_width_ratio <= 1:
            raise ValueError("target_width_ratio must be greater than 0 and at most 1")
        if not 0 <= self.width_deadband < self.target_width_ratio:
            raise ValueError("width_deadband must be smaller than target_width_ratio")
        if not self.center_deadband < self.forward_alignment <= 1:
            raise ValueError("forward_alignment must exceed center_deadband and be at most 1")


DEFAULT_SETTINGS = Settings()


# ---------------------------------------------------------------------------
# Detection geometry and motion calculations
# ---------------------------------------------------------------------------


def _target_geometry(target: Any, width: Any, height: Any,
                     minimum_confidence: float) -> Optional[tuple[float, float]]:
    """Return normalized ``(horizontal_error, width_ratio)`` for a box."""
    if not isinstance(target, dict):
        return None
    # Normalize all incoming values before using them in flight calculations.
    values = [_finite_float(value) for value in (
        width, height,
        *(target.get(key) for key in ("x1", "y1", "x2", "y2", "confidence")),
    )]
    if any(value is None for value in values):
        return None

    image_width, image_height, x1, y1, x2, y2, confidence = values
    if image_width <= 0 or image_height <= 0:
        return None
    if not (0 <= x1 < x2 <= image_width and 0 <= y1 < y2 <= image_height):
        return None
    if not minimum_confidence <= confidence <= 1:
        return None

    # Error is -1 at the far left, 0 at the image center, and +1 at the right.
    center_error = ((x1 + x2) / 2 - image_width / 2) / (image_width / 2)

    # Apparent width is used as a rough distance signal: larger means closer.
    width_ratio = (x2 - x1) / image_width
    return center_error, width_ratio


def _turn_rate(error: float, settings: Settings) -> float:
    """Convert normalized horizontal error into a bounded yaw rate."""
    if abs(error) <= settings.center_deadband:
        return 0.0
    rate = settings.yaw_direction * settings.yaw_gain * error

    # Clamp the result so a bad detection cannot request an extreme turn.
    return max(-settings.max_yaw_rate, min(settings.max_yaw_rate, rate))


def _motion_from_geometry(geometry: Optional[tuple[float, float]],
                          settings: Settings) -> tuple[float, float]:
    """Return requested ``(forward_mps, yaw_rads)`` from target geometry."""
    if geometry is None:
        return 0.0, 0.0
    horizontal_error, width_ratio = geometry
    # Positive gap means the target is smaller than desired and the drone
    # should move forward. A negative gap means it is already close enough.
    width_gap = max(0.0, settings.target_width_ratio - width_ratio - settings.width_deadband)

    # Forward movement is reduced while the target is not centered.
    alignment = max(0.0, 1.0 - abs(horizontal_error) / settings.forward_alignment)
    forward = min(settings.max_forward_speed, settings.forward_gain * width_gap) * alignment
    return forward, _turn_rate(horizontal_error, settings)


def calculate_motion(target: Any, width: Any, height: Any,
                     settings: Settings = DEFAULT_SETTINGS) -> tuple[float, float]:
    """Calculate requested ``(forward_mps, yaw_rads)`` from one target box."""
    geometry = _target_geometry(target, width, height, settings.min_confidence)
    return _motion_from_geometry(geometry, settings)


def calculate_yaw_rate(target: Any, width: Any, height: Any,
                       settings: Settings = DEFAULT_SETTINGS) -> float:
    """Compatibility helper returning only the requested yaw rate."""
    return calculate_motion(target, width, height, settings)[1]


# ---------------------------------------------------------------------------
# Tracking controller
# ---------------------------------------------------------------------------


class AutonomousTracking:
    """Compute and optionally send visual-pursuit velocity commands.

    ``cache`` is the shared telemetry cache. This class never calls
    ``recv_match`` or creates a connection. Commands are disabled by default;
    enabling them requires a fresh target frame afterward.
    """

    def __init__(self, cache: Any, *, send_commands: bool = False,
                 settings: Settings = DEFAULT_SETTINGS) -> None:
        required = ("connection", "write_lock", "get_message", "get_flight_controller_status")
        if not all(hasattr(cache, name) for name in required):
            raise TypeError("cache must be the shared TelemetryCache")
        self.cache = cache                  # Shared telemetry/MAVLink cache.
        self.cfg = settings                 # Immutable tracking configuration.
        self.send_commands = bool(send_commands)

        # The controller can receive camera results while the worker is sending
        # commands, so all controller state is protected by one reentrant lock.
        self._lock = threading.RLock()
        self._stop = threading.Event()

        # Stored as: requested forward speed, requested yaw rate, frame time.
        self._target: tuple[float, float, Optional[float]] = (0.0, 0.0, None)
        self._forward_sent = 0.0
        self._last_input = float("-inf")
        self._active = False
        self._closed = False
        self._next_send = 0.0
        self._thread: Optional[threading.Thread] = None
        self.error: Optional[BaseException] = None

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable output and invalidate the previous target."""
        with self._lock:
            if self._closed:
                raise RuntimeError("tracking is closed")
            # Disabling or re-enabling invalidates old camera data. The next
            # command-authority change must be followed by a new frame.
            was_active = self._active
            self.send_commands = bool(enabled)
            self._active = False
            self._target = (0.0, 0.0, None)
            self._forward_sent = 0.0
            self._last_input = time.monotonic()
            self._next_send = 0.0
            # Stop forward motion before removing command authority.
            if was_active:
                self._send_command(0.0, 0.0)

    def set_target(self, target: Any, width: Any, height: Any,
                   captured_at: Any) -> bool:
        """Accept one already-selected target box.

        ``captured_at`` must be the Pi's ``time.monotonic()`` timestamp taken
        when the image was captured, before detection and processing.
        """
        # The timestamp must come from the same monotonic clock used by this
        # controller; wall-clock timestamps cannot reliably measure frame age.
        stamp = _finite_float(captured_at)
        now = time.monotonic()
        geometry = _target_geometry(target, width, height, self.cfg.min_confidence)
        with self._lock:
            # Ignore closed, malformed, duplicate, or out-of-order results.
            if self._closed or stamp is None or stamp <= self._last_input:
                return False
            self._last_input = stamp
            # A stale detection must not keep the drone moving toward an old
            # location after the vehicle has already changed position.
            if not 0 <= now - stamp <= self.cfg.target_timeout:
                self._target = (0.0, 0.0, None)
                return False
            # Store the calculated command; step() later decides whether it is
            # safe and timely enough to transmit.
            forward, yaw = _motion_from_geometry(geometry, self.cfg)
            self._target = (forward, yaw, stamp if geometry is not None else None)
            return geometry is not None

    def set_frame_result(self, result: dict[str, Any], captured_at: Any) -> bool:
        """Accept a backend result without running detection a second time."""
        try:
            frame = result["frame"]
            height, width = frame.shape[:2]
        except (KeyError, AttributeError, TypeError, ValueError) as error:
            raise ValueError("result must contain a frame with a shape") from error
        return self.set_target(result.get("target"), width, height, captured_at)

    def status(self) -> dict[str, Any]:
        """Return the latest cached flight-controller status."""
        return fc_status.get_fc_status(self.cache)

    def _ready(self, state: dict[str, Any]) -> bool:
        """Require a connected, armed ArduCopter in GUIDED mode."""
        # A camera detection is never sufficient by itself to authorize flight.
        heartbeat_message = self.cache.get_message("HEARTBEAT")
        return bool(
            state.get("connected")
            and state.get("armed") is True
            and state.get("flight_mode") == "GUIDED"
            and getattr(heartbeat_message, "type", None) == 2
        )

    def _send_command(self, yaw_rate: float, forward_speed: float) -> bool:
        """Send a BODY_NED command through the shared cache transport.

        The current cache exposes its already-open transport as ``connection``;
        this method only serializes a write and never opens or reads the link.
        """
        if not math.isfinite(yaw_rate) or not math.isfinite(forward_speed):
            return False
        # Apply a final clamp immediately before transmission as a last safety
        # boundary, even if the caller supplied unusual values.
        yaw_rate = max(-self.cfg.max_yaw_rate, min(self.cfg.max_yaw_rate, yaw_rate))
        forward_speed = max(0.0, min(self.cfg.max_forward_speed, forward_speed))

        with self.cache.write_lock:
            if not self._ready(self.status()):
                return False
            link = self.cache.connection

            # BODY_NED makes forward velocity relative to the drone's heading.
            # Type-mask 1479 ignores position, acceleration, and yaw angle,
            # while accepting velocity and yaw-rate fields.
            link.mav.set_position_target_local_ned_send(
                int(time.monotonic() * 1000) & 0xFFFFFFFF,
                link.target_system, link.target_component,
                8,       # MAV_FRAME_BODY_NED
                1479,    # Enable forward velocity and yaw rate.
                0, 0, 0, forward_speed, 0, 0, 0, 0, 0, yaw_rate,
            )
        return True

    def step(self) -> dict[str, Any]:
        """Perform one bounded control step without reading MAVLink."""
        with self._lock:
            # 1. Read only the latest cached status. This method never calls
            # cache.update() or competes with the shared MAVLink reader.
            now = time.monotonic()
            state = self.status()
            requested, requested_yaw, captured_at = self._target
            fresh = captured_at is not None and 0 <= now - captured_at <= self.cfg.target_timeout
            ready = self._ready(state)

            # 2. Immediately remove authority if the flight state changes.
            if self._active and not ready:
                self.send_commands = False
                self._active = False
                self._target = (0.0, 0.0, None)
                self._forward_sent = 0.0
                fresh = False

            # 3. Expired target data produces a stop command rather than a
            # prediction based on an old image.
            requested_forward = requested if fresh else 0.0
            yaw_rate = requested_yaw if fresh else 0.0
            if fresh:
                # 4. Ramp forward speed gradually to avoid sudden acceleration.
                increment = self.cfg.max_acceleration / self.cfg.command_hz
                forward_speed = min(requested_forward, self._forward_sent + increment)
            else:
                # Lost target: stop advancing immediately.
                forward_speed = 0.0

            sent = False
            # 5. Transmit only at the configured rate and only when the target
            # and flight-controller safety checks both pass.
            if (not self._closed and self.send_commands and ready
                    and (fresh or self._active) and now >= self._next_send):
                sent = self._send_command(yaw_rate, forward_speed)
                if sent:
                    # Store the speed actually transmitted so the next step's
                    # acceleration limit starts from the real command.
                    self._active = True
                    self._forward_sent = forward_speed
                self._next_send = now + 1.0 / self.cfg.command_hz

            return {
                "flight_controller": state,
                "target_fresh": fresh,
                "yaw_rate_rads": yaw_rate,
                "forward_speed_mps": forward_speed,
                "requested_forward_mps": requested_forward,
                "commands_enabled": self.send_commands,
                "sent": sent,
            }

    def _run(self) -> None:
        """Continuously call step() until the controller is stopped."""
        try:
            next_log = 0.0
            while not self._stop.is_set():
                report = self.step()
                if time.monotonic() >= next_log:
                    logging.info("%s", report)
                    next_log = time.monotonic() + 1.0
                self._stop.wait(1.0 / self.cfg.command_hz)
        except BaseException as error:
            self.error = error
            logging.exception("tracking worker stopped")
        finally:
            try:
                self.set_enabled(False)
            except BaseException as error:
                self.error = self.error or error
                logging.exception("final zero-motion write failed")

    def start(self) -> None:
        """Start the background control loop once."""
        with self._lock:
            if self._closed or self._thread is not None:
                raise RuntimeError("create a new tracking controller to restart")
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def close(self) -> None:
        """Stop the worker and invalidate tracking state."""
        # Closing is intentionally idempotent: shutdown code may call it from
        # more than one cleanup path.
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            if self._thread.is_alive():
                raise RuntimeError("tracking worker did not stop")
        with self._lock:
            if not self._closed:
                try:
                    # Send zero velocity before marking the controller closed.
                    if self._active:
                        self._send_command(0.0, 0.0)
                finally:
                    self.send_commands = False
                    self._active = False
                    self._closed = True


# ---------------------------------------------------------------------------
# Full pursuit orchestration and offline demonstration
# ---------------------------------------------------------------------------


def run_pursuit(results: Iterable[tuple[dict[str, Any], float]], cache: Any, *,
                backend_url: str = heartbeat.DEFAULT_BACKEND_URL,
                mission_id: Optional[str] = None, send_commands: bool = False,
                settings: Settings = DEFAULT_SETTINGS) -> None:
    """Run tracking with one shared telemetry reader and publisher."""
    # This function coordinates existing components; it does not create a new
    # MAVLink connection. The shared cache remains owned by the caller.
    stop = threading.Event()
    tracker = AutonomousTracking(cache, send_commands=send_commands, settings=settings)
    reader = threading.Thread(
        target=fc_status.monitor_status,
        args=(cache, stop),
        kwargs={"backend_url": backend_url, "mission_id": mission_id},
        daemon=True,
    )
    try:
        # Start telemetry monitoring and command control exactly once.
        reader.start()
        tracker.start()
        for result, captured_at in results:
            if tracker.error:
                raise RuntimeError("tracking worker failed") from tracker.error
            if not reader.is_alive():
                raise RuntimeError("shared telemetry reader stopped")
            # Detection has already happened; tracking consumes its result.
            tracker.set_frame_result(result, captured_at)
        if tracker.error:
            raise RuntimeError("tracking worker failed") from tracker.error
    finally:
        tracker.close()
        stop.set()
        if reader.ident is not None:
            reader.join(timeout=5.0)
            if reader.is_alive():
                raise RuntimeError("shared telemetry reader did not stop")


def main() -> None:
    """Run a hardware-free calculation demonstration."""
    examples = (("far", (288, 352)), ("near", (220, 420)),
                ("right", (490, 590)), ("lost", None))
    for name, bounds in examples:
        target = None if bounds is None else {
            "x1": bounds[0], "x2": bounds[1], "y1": 100, "y2": 200,
            "confidence": 0.9,
        }
        forward, yaw = calculate_motion(target, 640, 480)
        print(f"{name:6} forward={forward:.3f} m/s; yaw={yaw:+.3f} rad/s")


if __name__ == "__main__":
    main()
