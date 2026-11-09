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
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
from queue import Empty, Full, Queue
from threading import Event, Lock, RLock, Thread
try:
    from pymavlink import mavutil
except ImportError:
    mavutil = None
DEFAULT_CONNECTION = os.getenv('MAVLINK_CONNECTION', '/dev/ttyACM0')
DEFAULT_BAUD_RATE = int(os.getenv('MAVLINK_BAUD_RATE', '115200'))
DEFAULT_BACKEND_URL = os.getenv('BACKEND_TELEMETRY_URL', 'http://127.0.0.1:8000/telemetry')
HEARTBEAT_TIMEOUT_SECONDS = 5.0
TELEMETRY_TIMEOUT_SECONDS = 5.0
MESSAGE_HISTORY_SIZE = 200
DEFAULT_FRAME_MATCH_WINDOW_SECONDS = 2.0


def _locked(method):
    """Keep each public snapshot coherent while another thread updates it."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._state_lock:
            return method(self, *args, **kwargs)
    return wrapper

def utc_timestamp():
    """Return an ISO-8601 UTC timestamp for logs and backend payloads."""
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')

def timestamp():
    """Backward-compatible alias used by the other microcontroller files."""
    return utc_timestamp()

def _finite_float(value):
    """Convert a number to a JSON-safe float, or return None."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None

def _finite_int(value):
    """Convert a number to a JSON-safe integer, or return None."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None

def _message_time_usec(message):
    """Return a MAVLink message's onboard timestamp in microseconds."""
    time_usec = getattr(message, 'time_usec', None)
    if time_usec is not None:
        return _finite_int(time_usec)
    time_boot_ms = getattr(message, 'time_boot_ms', None)
    if time_boot_ms is not None:
        value = _finite_int(time_boot_ms)
        return value * 1000 if value is not None else None
    return None


def base_status():
    """Create the common flight-controller status shape."""
    return dict(drone_id=os.getenv('DRONE_ID', 'drone-01'), connected=False, status='unknown',
                flight_mode='UNKNOWN', custom_mode=None, armed=None, system_status='UNKNOWN',
                last_heartbeat=None, stale=True, error=None)

def mock_status():
    """Return a deterministic status for development without hardware."""
    status = base_status()
    now = utc_timestamp()
    status.update(connected=True, status='connected', flight_mode='STABILIZE', custom_mode=0,
                  armed=False, system_status='STANDBY', last_heartbeat=now, stale=False)
    return status

def _metadata(record=None):
    return dict(received_timestamp=record[2] if record else None,
                received_monotonic_ns=record[1] if record else None,
                source_time_usec=_message_time_usec(record[0]) if record else None)

class TelemetryCache:
    """Own one MAVLink connection and retain the newest telemetry messages."""

    def __init__(self, connection, *, history_size=MESSAGE_HISTORY_SIZE,
                 frame_match_window_seconds=DEFAULT_FRAME_MATCH_WINDOW_SECONDS,
                 drone_id=None, target_system=None, target_component=None, battery_id=0,
                 telemetry_timeout_seconds=TELEMETRY_TIMEOUT_SECONDS):
        """Initialize the cache around one MAVLink connection."""
        self.connection = connection
        self.drone_id = str(drone_id or os.getenv('DRONE_ID', 'drone-01')).strip()
        if not self.drone_id:
            raise ValueError('drone_id cannot be empty')
        self.target_system = target_system
        self.target_component = target_component
        self.battery_id = int(battery_id)
        if not 0 <= self.battery_id <= 255:
            raise ValueError('battery_id must be between 0 and 255')
        for value in (frame_match_window_seconds, telemetry_timeout_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError('freshness windows must be finite and positive')
        for value in (target_system, target_component):
            if value is not None and (not 1 <= value <= 255):
                raise ValueError('target IDs must be between 1 and 255')
        self.telemetry_timeout_seconds = telemetry_timeout_seconds
        self._source = None
        self._state_lock = RLock()
        self._read_lock = Lock()
        self._next_companion_heartbeat = 0.0
        self._closed = False
        self.history_size = max(1, int(history_size))
        self.frame_match_window_ns = int(max(0.0, float(frame_match_window_seconds)) * 1000000000)
        self.messages = {}
        self.message_history = defaultdict(lambda: deque(maxlen=self.history_size))
        self.message_metadata = {}
        self.prearm_messages = deque(maxlen=20)
        self.last_heartbeat_monotonic_ns = None
        self.last_heartbeat_time = None
        self.last_error = None

    def close(self):
        """Close the owned MAVLink connection safely."""
        if self._closed:
            return
        self._closed = True
        close = getattr(self.connection, 'close', None)
        if callable(close):
            close()

    def record_message(self, message):
        """Store a message and receipt-time metadata."""
        with self._state_lock:
            return self._record_message(message)

    def _record_message(self, message):
        if self._closed:
            return False
        message_type = message.get_type()
        if message_type == 'BAD_DATA':
            return False
        source = (message.get_srcSystem(), message.get_srcComponent())
        if self._source is None:
            # MAV_AUTOPILOT_ARDUPILOTMEGA=3; reject GCS/camera/gimbal heartbeats.
            if (message_type != 'HEARTBEAT' or getattr(message, 'autopilot', None) != 3
                    or getattr(message, 'type', None) in (5, 6, 18, 26, 30)
                    or not all(1 <= value <= 255 for value in source)
                    or self.target_system is not None and source[0] != self.target_system
                    or self.target_component is not None and source[1] != self.target_component):
                return False
            self._source = source
            self.connection.target_system, self.connection.target_component = source
        if source != self._source:
            return False
        if message_type == 'HEARTBEAT' and getattr(message, 'autopilot', None) != 3:
            return False
        if message_type == 'BATTERY_STATUS' and getattr(message, 'id', None) != self.battery_id:
            return False
        if message_type == 'HIGHRES_IMU' and getattr(message, 'id', 0) != 0:
            return False
        received_monotonic_ns = time.monotonic_ns()
        received_utc = utc_timestamp()
        source_time_usec = _message_time_usec(message)
        self.messages[message_type] = message
        self.message_history[message_type].append((message, received_monotonic_ns, received_utc))
        self.message_metadata[message_type] = {'received_timestamp': received_utc, 'received_monotonic_ns': received_monotonic_ns, 'source_time_usec': source_time_usec}
        if message_type == 'HEARTBEAT':
            self.last_heartbeat_monotonic_ns = received_monotonic_ns
            self.last_heartbeat_time = received_utc
            self.last_error = None
        if message_type == 'STATUSTEXT':
            text = getattr(message, 'text', '')
            if isinstance(text, bytes):
                text = text.decode('utf-8', errors='replace')
            text = str(text).rstrip('\x00')
            if text and 'prearm' in text.lower():
                self.prearm_messages.append(text)
        return True

    def update(self, timeout=0.2, max_messages=200):
        """Read available MAVLink messages and update the cache."""
        if self._closed:
            raise RuntimeError('Telemetry connection is closed')
        if not math.isfinite(timeout) or timeout < 0 or max_messages < 1:
            raise ValueError('timeout must be nonnegative; max_messages must be positive')
        if not self._read_lock.acquire(blocking=False):
            raise RuntimeError('Only one caller may read this MAVLink connection')
        try:
            count = 0
            deadline = time.monotonic() + timeout
            if time.monotonic() >= self._next_companion_heartbeat:
                self.connection.mav.heartbeat_send(18, 8, 0, 0, 4)  # Companion liveness only.
                self._next_companion_heartbeat = time.monotonic() + 1.0
            for index in range(max_messages):
                message = self.connection.recv_match(blocking=index == 0 and timeout > 0, timeout=max(0.0, deadline - time.monotonic()) if index == 0 else 0)
                if message is None:
                    break
                count += int(self.record_message(message))
                if timeout > 0 and time.monotonic() >= deadline:
                    break
            return count
        except Exception as error:
            with self._state_lock:
                self.last_error = str(error)
                self.last_heartbeat_monotonic_ns = None
            raise
        finally:
            self._read_lock.release()

    def get_message(self, message_type):
        """Return the newest cached message of a type."""
        return self.get_message_at(message_type)

    def get_message_at(self, message_type, frame_timestamp_ns=None, max_age_seconds=None):
        """Return the message nearest to a camera frame timestamp."""
        record = self.get_message_record_at(message_type, frame_timestamp_ns, max_age_seconds)
        return record[0] if record is not None else None

    def get_message_record_at(self, message_type, frame_timestamp_ns=None, max_age_seconds=None):
        """Return the selected message plus its matching receipt metadata."""
        with self._state_lock:
            history = tuple(self.message_history.get(message_type, ()))
        if not history:
            return None
        if frame_timestamp_ns is None:
            record = history[-1]
            max_age = self.telemetry_timeout_seconds if max_age_seconds is None else max_age_seconds
            age = (time.monotonic_ns() - record[1]) / 1000000000.0
            return record if 0 <= age <= max_age else None
        target = int(frame_timestamp_ns)
        if target < 0 or target > time.monotonic_ns():
            return None
        record = min(history, key=lambda item: abs(item[1] - target))
        max_age_ns = self.frame_match_window_ns
        if max_age_seconds is not None:
            max_age_ns = int(max(0.0, float(max_age_seconds)) * 1000000000)
        return record if abs(record[1] - target) <= max_age_ns else None

    def get_message_metadata_at(self, message_type, frame_timestamp_ns=None):
        return _metadata(self.get_message_record_at(message_type, frame_timestamp_ns))

    @_locked
    def get_message_timestamp(self, message_type):
        return dict(self.message_metadata.get(message_type, _metadata()))

    @_locked
    def heartbeat_is_recent(self):
        """Return whether a heartbeat arrived within the timeout window."""
        if self._closed or self.last_error is not None or self.last_heartbeat_monotonic_ns is None:
            return False
        age = (time.monotonic_ns() - self.last_heartbeat_monotonic_ns) / 1000000000.0
        return 0 <= age <= HEARTBEAT_TIMEOUT_SECONDS

    @_locked
    def get_flight_controller_status(self):
        """Convert the newest HEARTBEAT into backend-ready status."""
        status = base_status()
        status['drone_id'] = self.drone_id
        heartbeat = self.get_message('HEARTBEAT')
        if heartbeat is None or not self.heartbeat_is_recent():
            status.update(status='heartbeat_timeout' if self.last_heartbeat_time else 'waiting_for_heartbeat',
                          last_heartbeat=self.last_heartbeat_time, error=self.last_error)
            return status
        armed_flag = 128
        status.update(connected=True, status='connected', flight_mode=mavutil.mode_string_v10(heartbeat),
                      custom_mode=_finite_int(getattr(heartbeat, 'custom_mode', None)),
                      armed=bool(heartbeat.base_mode & armed_flag),
                      system_status=system_status_name(getattr(heartbeat, 'system_status', None)),
                      last_heartbeat=self.last_heartbeat_time, stale=False, error=None)
        return status

    def _sample(self, kind, frame_timestamp_ns):
        if frame_timestamp_ns is None and (not self.heartbeat_is_recent()):
            return None
        return self.get_message_at(kind, frame_timestamp_ns)

    @_locked
    def get_attitude(self, frame_timestamp_ns=None):
        """Return roll, pitch and yaw in degrees."""
        return self._group('ATTITUDE', {name + '_deg': (name, math.pi / 180) for name in ('roll', 'pitch', 'yaw')}, frame_timestamp_ns)[1]

    @_locked
    def get_imu(self, frame_timestamp_ns=None):
        """Return updated HIGHRES_IMU fields in m/s^2 and rad/s."""
        imu = self._sample('HIGHRES_IMU', frame_timestamp_ns)
        flags = _finite_int(getattr(imu, 'fields_updated', 0)) or 0
        data = {'timestamp': self.get_message_metadata_at('HIGHRES_IMU', frame_timestamp_ns)}
        for group, suffix, start in (('accelerometer_mps2', 'acc', 0), ('gyroscope_rads', 'gyro', 3)):
            data[group] = {axis: _finite_float(getattr(imu, axis + suffix, None)) if flags & 1 << bit else None for bit, axis in enumerate('xyz', start)}
        return data

    @_locked
    def get_telemetry_snapshot(self, frame_timestamp_ns=None):
        """Build fresh position, motion, GPS, battery, attitude and IMU values."""
        frame = frame_timestamp_ns
        message, position = self._group('GLOBAL_POSITION_INT', {
            'latitude_deg': ('lat', 1e7), 'longitude_deg': ('lon', 1e7),
            'altitude_m': ('alt', 1000), 'relative_altitude_m': ('relative_alt', 1000)}, frame)
        for field, limit in (('latitude_deg', 90), ('longitude_deg', 180)):
            if position[field] is not None and (not -limit <= position[field] <= limit):
                position[field] = None
        vx, vy = (_finite_float(getattr(message, axis, None)) for axis in ('vx', 'vy'))
        heading = _finite_float(getattr(message, 'hdg', None))
        motion = dict(speed_mps=math.hypot(vx, vy) / 100 if vx is not None and vy is not None else None,
                      heading_deg=heading / 100 if heading is not None and 0 <= heading < 36000 else None,
                      timestamp=position['timestamp'])
        _, hud = self._group('VFR_HUD', {'speed_mps': ('groundspeed', 1), 'heading_deg': ('heading', 1)}, frame)
        values = {}
        for key in ('speed_mps', 'heading_deg'):
            value = hud[key]
            valid = value is not None and value >= 0 and (key != 'heading_deg' or value < 360)
            values[key] = value if valid else None
        self._fill_missing(motion, values, 'VFR_HUD', frame)
        message, gps = self._group('GPS_RAW_INT', {}, frame)
        for field, limit in (('fix_type', 8), ('satellites_visible', 254)):
            value = _finite_int(getattr(message, field, None))
            gps[field] = value if value is not None and 0 <= value <= limit else None
        return dict(timestamp=timestamp(), position=position, motion=motion, gps=gps,
                    battery=self._battery(frame), attitude=self.get_attitude(frame), imu=self.get_imu(frame))

    @_locked
    def get_readiness(self):
        """Return basic readiness information for launch-sequence callers."""
        status = self.get_flight_controller_status()
        gps = self.get_message('GPS_RAW_INT')
        fix_type = _finite_int(getattr(gps, 'fix_type', None)) if gps else None
        reasons = []
        if not status['connected']:
            reasons.append('Flight-controller heartbeat missing or stale')
        if status['armed'] is not False:
            reasons.append('Flight controller is armed or armed state is unknown')
        if fix_type is None or not 3 <= fix_type <= 8:
            reasons.append('Fresh 3D GPS fix is missing')
        if status['system_status'] != 'STANDBY':
            reasons.append('Flight controller does not report STANDBY')
        system = self.get_message('SYS_STATUS')
        prearm = 1 << 28
        present = _finite_int(getattr(system, 'onboard_control_sensors_present', 0)) or 0
        enabled = _finite_int(getattr(system, 'onboard_control_sensors_enabled', 0)) or 0
        healthy = _finite_int(getattr(system, 'onboard_control_sensors_health', 0)) or 0
        if system is None or not present & enabled & healthy & prearm:
            reasons.append('Fresh enabled/passed pre-arm check is missing')
        basic_checks_passed = not reasons
        reasons.append('Launch-sequence checks and operator confirmation are required')
        return dict(ready=False, ready_for_launch=False, basic_checks_passed=basic_checks_passed,
                    reasons=reasons, heartbeat_recent=self.heartbeat_is_recent(),
                    gps_fix_type=fix_type, prearm_messages=list(self.prearm_messages))

    @_locked
    def build_backend_payload(self, *, mission_id=None, frame_id=None, frame_timestamp_ns=None, bounding_box=None):
        """Build the shared payload consumed by the backend and camera system."""
        frame = {'frame_id': frame_id, 'frame_timestamp_ns': frame_timestamp_ns, 'bounding_box': bounding_box}
        if frame_timestamp_ns is not None:
            frame['telemetry'] = self.get_telemetry_snapshot(frame_timestamp_ns)
        return dict(drone_id=self.drone_id, mission_id=mission_id, frame=frame,
                    flight_controller=self.get_flight_controller_status(),
                    telemetry=self.get_telemetry_snapshot(), readiness=self.get_readiness(),
                    published_timestamp=utc_timestamp())

    def _group(self, kind, fields, frame):
        """Decode fields with unit divisors and the selected sample's timestamp."""
        message = self._sample(kind, frame)
        data = {}
        for output, (field, divisor) in fields.items():
            value = _finite_float(getattr(message, field, None))
            data[output] = value / divisor if value is not None else None
        data['timestamp'] = self.get_message_metadata_at(kind, frame)
        return (message, data)

    def _fill_missing(self, data, values, kind, frame):
        """Fill gaps without losing the actual source timestamp of each field."""
        metadata = self.get_message_metadata_at(kind, frame)
        for field, value in values.items():
            data.setdefault(field + '_timestamp', data['timestamp'] if data[field] is not None else {})
            if data[field] is None and value is not None:
                data[field] = value
                data[field + '_timestamp'] = metadata

    def _battery(self, frame):
        """Decode the selected battery, using SYS_STATUS only for primary-battery gaps."""
        battery, data = self._group('BATTERY_STATUS', {'percentage': ('battery_remaining', 1), 'current_a': ('current_battery', 100)}, frame)
        if data['percentage'] is not None and (not 0 <= data['percentage'] <= 100):
            data['percentage'] = None
        if data['current_a'] == -0.01:  # MAVLink unknown current: -1 centiamp.
            data['current_a'] = None
        cells = [_finite_float(v) for v in getattr(battery, 'voltages', []) or []]
        cells = [v for v in cells if v is not None and 0 <= v < 65535]
        extra = [_finite_float(v) for v in getattr(battery, 'voltages_ext', []) or []]
        extra = [v for v in extra if v is not None and 0 < v < 65535]
        data['voltage_v'] = sum(cells + extra) / 1000 if cells else None
        system = self._sample('SYS_STATUS', frame) if self.battery_id == 0 else None
        values = {}
        for output, field, divisor, invalid in (
            ('percentage', 'battery_remaining', 1, -1),
            ('current_a', 'current_battery', 100, -1),
            ('voltage_v', 'voltage_battery', 1000, 65535)):
            value = _finite_float(getattr(system, field, None))
            valid = value is not None and value != invalid
            if output in ('percentage', 'voltage_v'):
                valid = valid and 0 <= value <= (100 if output == 'percentage' else 65534)
            values[output] = value / divisor if valid else None
        self._fill_missing(data, values, 'SYS_STATUS', frame)
        return data

def system_status_name(status_number):
    """Convert MAVLink MAV_STATE values to readable names."""
    statuses = {0: 'UNINIT', 1: 'BOOT', 2: 'CALIBRATING', 3: 'STANDBY', 4: 'ACTIVE', 5: 'CRITICAL', 6: 'EMERGENCY', 7: 'POWEROFF', 8: 'FLIGHT_TERMINATION'}
    return statuses.get(status_number, 'UNKNOWN')

def connect_telemetry(connection_address=DEFAULT_CONNECTION, baud_rate=DEFAULT_BAUD_RATE, drone_id=None, **cache_options):
    """Open one MAVLink connection and return its shared cache."""
    if mavutil is None:
        raise RuntimeError('Install pymavlink to use a flight controller: pip install pymavlink')
    connection = mavutil.mavlink_connection(connection_address, baud=int(baud_rate), autoreconnect=True, source_system=245, source_component=191)
    try:
        return TelemetryCache(connection, drone_id=drone_id, **cache_options)
    except Exception:
        connection.close()
        raise

def publish_payload(backend_url, payload, timeout=3.0):
    """POST one JSON payload. Return False when the backend is unavailable."""
    try:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('HTTP timeout must be finite and positive')
        request = urllib.request.Request(backend_url, data=json.dumps(payload, allow_nan=False).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=timeout) as response:
            print(f'Telemetry published with HTTP {response.status}')
            return 200 <= response.status < 300
    except urllib.error.HTTPError as error:
        print(f'Backend rejected telemetry: HTTP {error.code}')
    except urllib.error.URLError as error:
        print(f'Could not reach backend: {error}')
    except OSError as error:
        print(f'Telemetry publish failed: {error}')
    except (ValueError, TypeError, OverflowError) as error:
        print(f'Invalid telemetry publish request: {error}')
    return False

class TelemetryPublisher:
    """Nonblocking latest-only HTTP output. Never reads from MAVLink.

    A slow/unavailable backend cannot block the serial reader. There is no
    unbounded backlog or replay of old samples; pending data is replaced.
    publish_payload() remains synchronous for compatibility with callers.
    """

    def __init__(self, backend_url, timeout=3.0):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('HTTP timeout must be finite and positive')
        self.backend_url = backend_url
        self.timeout = timeout
        self._pending = Queue(maxsize=1)
        self._stop = Event()
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(self, payload):
        item = deepcopy(payload)
        try:
            self._pending.put_nowait(item)
        except Full:
            try:
                self._pending.get_nowait()
            except Empty:
                pass
            try:
                self._pending.put_nowait(item)
            except Full:
                pass

    def _run(self):
        while not self._stop.is_set():
            try:
                payload = self._pending.get(timeout=0.1)
            except Empty:
                continue
            try:
                publish_payload(self.backend_url, payload, self.timeout)
            except Exception as error:
                print(f'Telemetry publisher error: {error}')

    def close(self):
        self._stop.set()
        self._thread.join(timeout=self.timeout + 0.5)
        if self._thread.is_alive():
            print('HTTP worker still finishing an outstanding request.')

def mock_payload(drone_id=None, mission_id=None):
    """Reuse the real payload schema for hardware-free testing."""
    payload = TelemetryCache(None, drone_id=drone_id).build_backend_payload(mission_id=mission_id)
    payload.update(mock=True)
    payload['flight_controller'] = mock_status()
    payload['flight_controller']['drone_id'] = payload['drone_id']
    data = payload['telemetry']
    data['motion'].update(speed_mps=0.0, heading_deg=0.0)
    data['attitude'].update(roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0)
    data['imu']['accelerometer_mps2'].update(x=0.0, y=0.0, z=9.81)
    data['imu']['gyroscope_rads'].update(x=0.0, y=0.0, z=0.0)
    payload['readiness'].update(reasons=['Mock data is being used'], heartbeat_recent=True)
    return payload

def run_mock_mode(backend_url, interval, *, drone_id=None, mission_id=None, once=False, payload_factory=None):
    """Continuously print and publish mock telemetry until Ctrl+C."""
    _check_interval(interval)
    publisher = TelemetryPublisher(backend_url) if backend_url and (not once) else None
    try:
        while True:
            payload = payload_factory() if payload_factory else mock_payload(drone_id, mission_id)
            print(json.dumps(payload, indent=2))
            if once:
                if backend_url:
                    publish_payload(backend_url, payload)
                break
            if publisher:
                publisher.submit(payload)
            time.sleep(interval)
    except KeyboardInterrupt:
        print('Stopping mock telemetry publisher.')
    finally:
        if publisher:
            publisher.close()

def _check_interval(interval):
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError('interval must be finite and positive')

def run_telemetry_publisher(connection_address, baud_rate, backend_url, interval=1.0, *,
                            drone_id=None, mission_id=None, target_system=None,
                            target_component=None, battery_id=0, once=False):
    """Standalone loop that owns the connection and publishes snapshots."""
    _check_interval(interval)
    cache = None
    publisher = TelemetryPublisher(backend_url) if backend_url and (not once) else None
    try:
        cache = connect_telemetry(connection_address, baud_rate, drone_id=drone_id, target_system=target_system, target_component=target_component, battery_id=battery_id)
        next_publish = time.monotonic() + (HEARTBEAT_TIMEOUT_SECONDS if once else 0)
        while True:
            try:
                cache.update(timeout=min(0.2, interval))
            except (OSError, RuntimeError) as error:
                print(f'MAVLink read failed: {error}')
                time.sleep(min(0.2, interval))
            now = time.monotonic()
            if now < next_publish and (not (once and cache.heartbeat_is_recent())):
                continue
            next_publish = now + interval
            payload = cache.build_backend_payload(mission_id=mission_id)
            print(json.dumps(payload, indent=2))
            if once:
                if backend_url:
                    publish_payload(backend_url, payload)
                break
            if publisher:
                publisher.submit(payload)
    except KeyboardInterrupt:
        print('Stopping telemetry publisher.')
    except (OSError, ValueError) as error:
        print(f'Telemetry connection failed: {error}')
    finally:
        try:
            if cache is not None:
                cache.close()
        finally:
            if publisher:
                publisher.close()

def parse_arguments(argv=None, *, backend_url=DEFAULT_BACKEND_URL, include_standalone=False):
    """Read command-line options for the standalone publisher."""
    parser = argparse.ArgumentParser(description='Shared ArduPilot telemetry publisher')
    parser.add_argument('--connection', default=DEFAULT_CONNECTION)
    parser.add_argument('--baud', type=int, default=DEFAULT_BAUD_RATE)
    parser.add_argument('--backend-url', default=backend_url)
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--mock', action='store_true')
    parser.add_argument('--drone-id', default=os.getenv('DRONE_ID', 'drone-01'))
    parser.add_argument('--mission-id', default=None)
    parser.add_argument('--target-system', type=int, default=None)
    parser.add_argument('--target-component', type=int, default=None)
    parser.add_argument('--battery-id', type=int, default=0)
    parser.add_argument('--once', action='store_true', help='Print one snapshot and exit')
    parser.add_argument('--no-publish', action='store_true', help='Print only, without HTTP')
    parser.add_argument('--publish-mock', action='store_true', help='Explicitly allow mock data to be posted to the selected backend')
    if include_standalone:
        parser.add_argument('--standalone', action='store_true')
    args = parser.parse_args(argv)
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error('--interval must be finite and positive')
    if args.baud <= 0:
        parser.error('--baud must be positive')
    if not args.drone_id.strip():
        parser.error('--drone-id cannot be empty')
    for value in (args.target_system, args.target_component):
        if value is not None and (not 1 <= value <= 255):
            parser.error('MAVLink target IDs must be between 1 and 255')
    if not 0 <= args.battery_id <= 255:
        parser.error('--battery-id must be between 0 and 255')
    if args.no_publish or (args.mock and (not args.publish_mock)):
        args.backend_url = ''
    return args

def main():
    """Start mock mode or the standalone telemetry publisher."""
    args = parse_arguments()
    if args.mock:
        run_mock_mode(args.backend_url, args.interval, drone_id=args.drone_id, mission_id=args.mission_id, once=args.once)
    else:
        run_telemetry_publisher(args.connection, args.baud, args.backend_url, args.interval,
            drone_id=args.drone_id, mission_id=args.mission_id, target_system=args.target_system,
            target_component=args.target_component, battery_id=args.battery_id, once=args.once)
if __name__ == '__main__':
    main()
