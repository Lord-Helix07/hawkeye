"""
Flight-controller status

- Reads status from TelemetryCache
- Builds the backend payload
- Publishes status
- Provides mock and standalone testing modes

"""

import argparse
import json
import os
import time

try:
    # Used when imported as part of the microcontroller package.
    from .telemetry import (
        connect_telemetry,
        publish_payload,
    )
except ImportError:
    # Used when running this file directly.
    from telemetry import (
        connect_telemetry,
        publish_payload,
    )


DEFAULT_CONNECTION = "/dev/ttyACM0"
DEFAULT_BAUD_RATE = 115200

DEFAULT_BACKEND_URL = (
    "http://127.0.0.1:8000/flight-controller/status"
)

DEFAULT_DRONE_ID = "drone-01"
DEFAULT_PUBLISH_INTERVAL = 1.0


def timestamp():
    """Return a UTC timestamp."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def mock_payload(drone_id):
    """
    Create fake data with the same structure used by the
    real telemetry system.
    """
    current_time = timestamp()

    return {
        "drone_id": drone_id,
        "mission_id": None,
        "flight_controller": {
            "drone_id": drone_id,
            "connected": True,
            "status": "connected",
            "flight_mode": "STABILIZE",
            "custom_mode": 0,
            "armed": False,
            "system_status": "STANDBY",
            "last_heartbeat": current_time,
            "stale": False,
            "error": None,
        },
        "telemetry": {
            "latitude": None,
            "longitude": None,
            "altitude_m": None,
            "speed_mps": None,
            "heading_deg": None,
            "gps_fix_type": None,
            "satellites_visible": None,
            "battery_pct": None,
            "battery_voltage": None,
            "battery_current": None,
            "timestamp": current_time,
        },
        "readiness": {
            "ready_for_launch": False,
            "reasons": [
                "Mock data is being used."
            ],
        },
    }


def get_fc_status(cache):
    """
    Read the latest flight-controller status from
    the shared TelemetryCache.

    This function does not read directly from MAVLink.
    """
    return cache.get_flight_controller_status()


def build_status_payload(cache, mission_id=None):
    """
    Build one complete backend payload from the shared cache.
    """
    return cache.build_backend_payload(
        mission_id=mission_id
    )


def publish_fc_status(
    cache,
    backend_url,
    mission_id=None,
):
    """
    Publish current FC status and telemetry.

    The shared cache must already be connected and updated
    by the main controller.
    """
    payload = build_status_payload(
        cache=cache,
        mission_id=mission_id,
    )

    print(json.dumps(payload, indent=2))

    return publish_payload(
        backend_url=backend_url,
        payload=payload,
    )


def run_shared_status_publisher(
    cache,
    backend_url,
    mission_id=None,
    publish_interval=DEFAULT_PUBLISH_INTERVAL,
):
    """
    Publish from an existing shared cache.

    Important:
    The caller must update the cache. This function does not
    call cache.update(), because launch and landing code may
    also use the same cache.
    """
    next_publish_time = time.monotonic()

    while True:
        now = time.monotonic()

        if now >= next_publish_time:
            publish_fc_status(
                cache=cache,
                backend_url=backend_url,
                mission_id=mission_id,
            )

            next_publish_time = (
                now + publish_interval
            )

        time.sleep(0.05)


def run_standalone_mode(
    connection_address,
    baud_rate,
    backend_url,
    drone_id,
    mission_id,
    publish_interval,
):
    """
    Standalone testing mode.

    This mode owns the MAVLink connection and should only be
    used when launch_sequence.py and landing_sequence.py are
    not running at the same time.
    """
    cache = None

    try:
        cache = connect_telemetry(
            connection_address=connection_address,
            baud_rate=baud_rate,
            drone_id=drone_id,
        )

        next_publish_time = time.monotonic()

        while True:
            # telemetry.py owns the actual MAVLink read.
            cache.update(timeout=0.2)

            now = time.monotonic()

            if now >= next_publish_time:
                publish_fc_status(
                    cache=cache,
                    backend_url=backend_url,
                    mission_id=mission_id,
                )

                next_publish_time = (
                    now + publish_interval
                )

    except KeyboardInterrupt:
        print("Stopping FC status publisher.")

    except Exception as error:
        print(f"FC status publisher failed: {error}")

    finally:
        if cache is not None:
            cache.close()


def run_mock_mode(
    backend_url,
    drone_id,
    publish_interval,
):
    """
    Continuously publish fake status for local testing.
    """
    try:
        while True:
            payload = mock_payload(drone_id)

            print(json.dumps(payload, indent=2))

            publish_payload(
                backend_url=backend_url,
                payload=payload,
            )

            time.sleep(publish_interval)

    except KeyboardInterrupt:
        print("Stopping mock status publisher.")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=(
            "HawkEye flight-controller status publisher"
        )
    )

    parser.add_argument(
        "--connection",
        default=os.getenv(
            "MAVLINK_CONNECTION",
            DEFAULT_CONNECTION,
        ),
        help=(
            "MAVLink address, such as /dev/ttyACM0 "
            "or udp:127.0.0.1:14550"
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
            DEFAULT_DRONE_ID,
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
        help=(
            "Seconds between backend updates"
        ),
    )

    parser.add_argument(
        "--mock",
        action="store_true",
        help="Publish fake telemetry data",
    )

    parser.add_argument(
        "--standalone",
        action="store_true",
        help=(
            "Open its own MAVLink connection for testing. "
            "Do not use with launch or landing."
        ),
    )

    return parser.parse_args()


def main():
    args = parse_arguments()

    if args.mock:
        run_mock_mode(
            backend_url=args.backend_url,
            drone_id=args.drone_id,
            publish_interval=args.interval,
        )

    elif args.standalone:
        run_standalone_mode(
            connection_address=args.connection,
            baud_rate=args.baud,
            backend_url=args.backend_url,
            drone_id=args.drone_id,
            mission_id=args.mission_id,
            publish_interval=args.interval,
        )

    else:
        print(
            "fc_status_updated.py is a shared helper."
        )
        print(
            "Use --mock for testing."
        )
        print(
            "Use --standalone only when no other file "
            "is using the MAVLink connection."
        )


if __name__ == "__main__":
    main()