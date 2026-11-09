"""
Flight-controller status

- Reads data from heartbeat.py cache
- sends that data to backend
"""

import json
import os
import time

if __package__:
    from . import heartbeat as shared
else:
    import heartbeat as shared

DEFAULT_CONNECTION = shared.DEFAULT_CONNECTION
DEFAULT_BAUD_RATE = shared.DEFAULT_BAUD_RATE
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000/flight-controller/status"
DEFAULT_DRONE_ID = "drone-01"
DEFAULT_PUBLISH_INTERVAL = 1.0
timestamp = shared.timestamp
connect_telemetry = shared.connect_telemetry
publish_payload = shared.publish_payload
run_telemetry_publisher = shared.run_telemetry_publisher
TelemetryPublisher = shared.TelemetryPublisher


def mock_payload(drone_id):
    fields = ("latitude", "longitude", "altitude_m", "speed_mps", "heading_deg",
              "gps_fix_type", "satellites_visible", "battery_pct", "battery_voltage", "battery_current")
    status = shared.mock_status()
    status["drone_id"] = drone_id
    telemetry = dict.fromkeys(fields)
    telemetry["timestamp"] = timestamp()
    return dict(drone_id=drone_id, mission_id=None, flight_controller=status,
                telemetry=telemetry, readiness=dict(ready_for_launch=False, reasons=["Mock data is being used."]))


def get_fc_status(cache):
    return cache.get_flight_controller_status()


def build_status_payload(cache, mission_id=None):
    return cache.build_backend_payload(mission_id=mission_id)


def publish_fc_status(cache, backend_url, mission_id=None):
    """Synchronous one-shot helper; use the worker for continuous publishing."""
    payload = build_status_payload(cache, mission_id)
    print(json.dumps(payload, indent=2))
    return publish_payload(backend_url=backend_url, payload=payload)


def run_shared_status_publisher(cache, backend_url, mission_id=None,
                                publish_interval=DEFAULT_PUBLISH_INTERVAL):
    """Caller updates the cache; this loop never reads MAVLink."""
    shared._check_interval(publish_interval)
    publisher = TelemetryPublisher(backend_url)
    try:
        while True:
            publisher.submit(build_status_payload(cache, mission_id))
            time.sleep(publish_interval)
    finally:
        publisher.close()


def run_standalone_mode(connection_address, baud_rate, backend_url, drone_id,
                        mission_id, publish_interval, **options):
    return run_telemetry_publisher(
        connection_address=connection_address, baud_rate=baud_rate,
        backend_url=backend_url, interval=publish_interval,
        drone_id=drone_id, mission_id=mission_id, **options)


def run_mock_mode(backend_url, drone_id, publish_interval, *, mission_id=None, once=False):
    def payload_factory():
        payload = mock_payload(drone_id)
        payload["mission_id"] = mission_id
        return payload
    return shared.run_mock_mode(backend_url, publish_interval, once=once, payload_factory=payload_factory)


def parse_arguments():
    return shared.parse_arguments(backend_url=os.getenv("BACKEND_STATUS_URL", DEFAULT_BACKEND_URL),
                                  include_standalone=True)


def main():
    args = parse_arguments()
    if args.mock:
        run_mock_mode(args.backend_url, args.drone_id, args.interval,
                      mission_id=args.mission_id, once=args.once)
    elif args.standalone:
        run_standalone_mode(args.connection, args.baud, args.backend_url, args.drone_id,
            args.mission_id, args.interval, target_system=args.target_system,
            target_component=args.target_component, battery_id=args.battery_id, once=args.once)
    else:
        print("Shared helper: use --mock to test, or --standalone when it owns the MAVLink port.")


if __name__ == "__main__":
    main()
