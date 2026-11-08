import argparse
import logging
import math
import threading
import time
from dataclasses import dataclass


# CHANGE THESE TEST VALUES HERE. They are starting values, not flight tuning.
@dataclass(frozen=True)
class Settings:
    baud: int = 115200                 # Confirm for the actual serial link.
    target_system: int = 1             # Confirm flight-controller MAVLink IDs.
    target_component: int = 1
    source_system: int = 245           # Must be unique on your MAVLink network.
    source_component: int = 191
    command_hz: float = 10.0
    heartbeat_timeout: float = 3.0     # Our chosen timeout, not a MAVLink rule.
    target_timeout: float = 0.5        # Expire images older than this (seconds).
    min_confidence: float = 0.60
    center_deadband: float = 0.10      # Error scaled from -1 (left) to +1.
    yaw_gain: float = 0.35             # rad/s per unit horizontal error.
    max_yaw_rate: float = 0.20         # rad/s; about 11.5 degrees/second.
    yaw_direction: int = 1            # Assumes unmirrored, forward-facing view.

    def __post_init__(self):
        for name in ("command_hz", "heartbeat_timeout", "target_timeout",
                     "yaw_gain", "max_yaw_rate"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not 0 <= self.min_confidence <= 1 or not 0 <= self.center_deadband < 1:
            raise ValueError("Invalid confidence or deadband")
        if self.yaw_direction not in (-1, 1):
            raise ValueError("yaw_direction must be -1 or 1")
        if self.command_hz < 2:
            raise ValueError("Use command_hz >= 2 to refresh velocity setpoints")


def calculate_yaw_rate(target, width, height, settings=Settings()):
    """Return a bounded turn rate; missing/invalid targets request zero motion."""
    if target is None:
        return 0.0
    try:
        width, height = float(width), float(height)
        x1, y1, x2, y2, confidence = (
            float(target[key]) for key in ("x1", "y1", "x2", "y2", "confidence")
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return 0.0
    if not all(math.isfinite(v) for v in (width, height, x1, y1, x2, y2, confidence)):
        return 0.0
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height
            and settings.min_confidence <= confidence <= 1):
        return 0.0
    center_x = (x1 + x2) / 2
    error = (center_x - width / 2) / (width / 2)
    if abs(error) <= settings.center_deadband:
        return 0.0
    return max(-settings.max_yaw_rate, min(settings.max_yaw_rate,
               settings.yaw_direction * settings.yaw_gain * error))


class AutonomousTracking:
    """Own this MAVLink connection exclusively; detection runs elsewhere.

    The worker keeps checking target age even if the camera caller stalls.
    It never arms, takes off, changes mode, or disarms the flight controller.
    Nonzero movement requires fresh ArduCopter heartbeat + GUIDED + armed.
    Dry-run still publishes our companion heartbeat, but no movement messages.
    """

    def __init__(self, connection, *, send_commands=False, settings=Settings()):
        from pymavlink import mavutil  # Offline demo works without this package.
        self.mu = mavutil
        self.cfg = settings
        self.send_commands = send_commands
        self.link = mavutil.mavlink_connection(
            connection, baud=settings.baud,
            source_system=settings.source_system,
            source_component=settings.source_component,
        )
        self._lock = threading.Lock()
        self._target = (0.0, None)     # (yaw rate, image capture timestamp)
        self._last_hb = None
        self._mode = None
        self._armed = None
        self._stop = threading.Event()
        self._thread = None
        self.error = None

    def set_target(self, target, width, height, captured_at):
        """captured_at must use this Pi's time.monotonic() capture clock."""
        now = time.monotonic()
        try:
            stamp = float(captured_at)
            valid_time = math.isfinite(stamp) and 0 <= now - stamp <= self.cfg.target_timeout
        except (ValueError, TypeError, OverflowError):
            valid_time = False
        yaw = calculate_yaw_rate(target, width, height, self.cfg) if valid_time else 0.0
        with self._lock:
            self._target = (yaw, stamp if valid_time and target is not None else None)

    def status(self):
        with self._lock:
            connected = (self._last_hb is not None and
                         time.monotonic() - self._last_hb <= self.cfg.heartbeat_timeout)
            return {"connected": connected,
                    "mode": self._mode if connected else None,
                    "armed": self._armed if connected else None}

    def _receive(self):
        # Bound work so a busy telemetry link cannot starve the watchdog.
        for _ in range(100):
            msg = self.link.recv_match(blocking=False)
            if msg is None:
                break
            if (msg.get_type() != "HEARTBEAT" or
                msg.get_srcSystem() != self.cfg.target_system or
                msg.get_srcComponent() != self.cfg.target_component or
                msg.autopilot != self.mu.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA or
                msg.type != self.mu.mavlink.MAV_TYPE_QUADROTOR):
                continue  # This starter explicitly targets an ArduCopter quad.
            with self._lock:
                self._last_hb = time.monotonic()
                self._mode = self.mu.mode_string_v10(msg)
                self._armed = bool(msg.base_mode & self.mu.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)

    def _send(self, yaw_rate):
        # BODY_NED velocities: forward, right, down, in metres/second.
        # Mask 1479 enables vx/vy/vz AND yaw_rate, ignoring position/accel/yaw.
        # All velocities stay zero: the initial test only rotates horizontally.
        self.link.mav.set_position_target_local_ned_send(
            int(time.monotonic() * 1000) & 0xFFFFFFFF,
            self.cfg.target_system, self.cfg.target_component,
            self.mu.mavlink.MAV_FRAME_BODY_NED, 1479,
            0, 0, 0,   # ignored position
            0, 0, 0,   # forward/right/down velocity: ZERO
            0, 0, 0,   # ignored acceleration
            0, yaw_rate,
        )

    def _ready(self):
        state = self.status()
        return state["connected"] and state["armed"] and state["mode"] == "GUIDED"

    def _run(self):
        next_heartbeat = 0.0
        next_log = 0.0
        try:
            while not self._stop.is_set():
                self._receive()
                now = time.monotonic()
                if now >= next_heartbeat:
                    self.link.mav.heartbeat_send(
                        self.mu.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
                        self.mu.mavlink.MAV_AUTOPILOT_INVALID, 0, 0,
                        self.mu.mavlink.MAV_STATE_ACTIVE,
                    )
                    next_heartbeat = now + 1.0
                with self._lock:
                    yaw, captured_at = self._target
                fresh = captured_at is not None and 0 <= now - captured_at <= self.cfg.target_timeout
                if not fresh:
                    yaw = 0.0
                ready = self._ready()
                if self.send_commands and ready:
                    self._send(yaw)
                if now >= next_log:
                    logging.info("%s target_fresh=%s yaw=%.3f rad/s output=%s",
                                 self.status(), fresh, yaw,
                                 "SENT (not confirmation of motion)" if self.send_commands and ready
                                 else "DRY RUN" if not self.send_commands else "BLOCKED")
                    next_log = now + 1.0
                self._stop.wait(1.0 / self.cfg.command_hz)
        except Exception as error:
            self.error = error
            logging.exception("Tracking worker stopped")
        finally:
            # Best effort only. Link loss cannot guarantee delivery of a stop.
            # ArduCopter's configured command timeout/failsafes remain necessary.
            try:
                if self.send_commands and self._ready():
                    self._send(0.0)
            except Exception:
                logging.exception("Could not send final zero-motion request")
            finally:
                self.link.close()

    def start(self):
        if self._thread is not None:
            raise RuntimeError("Create a new controller rather than restarting")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            if self._thread.is_alive():
                raise RuntimeError("MAVLink worker did not stop; inspect connection")
        else:
            self.link.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", help="Confirmed MAVLink connection; omit for offline demo")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not args.connection:
        for name, bounds in (("left", (50, 150)), ("center", (270, 370)),
                             ("right", (490, 590)), ("lost", None)):
            target = None if bounds is None else dict(
                x1=bounds[0], x2=bounds[1], y1=100, y2=200, confidence=0.9)
            print(f"{name:6} yaw={calculate_yaw_rate(target, 640, 480):+.3f} rad/s; forward=0")
        return
    # CLI is status/dry-run only. Real target selection must be connected by caller.
    controller = AutonomousTracking(args.connection, send_commands=False)
    controller.start()
    try:
        while controller._thread.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        controller.close()
    if controller.error:
        raise RuntimeError("Tracking failed") from controller.error


if __name__ == "__main__":
    main()
