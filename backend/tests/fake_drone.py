"""
Fake drone: pretends to be the Raspberry Pi so you can test the Dashboard
without real hardware.

It does the two things the Pi is supposed to do:
  1. POST telemetry to the backend once a second (same shape as
     microcontroller/heartbeat.py), so it lands in the Telemetry table.
  2. Answer the launch / landing handshake on the mission's row in Missions:
        launch_status   requested -> ready      (operator then clicks Confirm)
                        confirmed -> launched   (drone climbs and flies to the target)
        landing_status  requested -> landing -> landed

How to use it (from backend/, with the backend running):
  1. Create a mission on the Deploy page (allow location so it has a target).
  2. python tests/fake_drone.py 0003
     It registers "drone-sim" in Drones right next to the target, so
     "Launch" assigns it (it's the nearest available drone).
  3. Open the Dashboard for that mission and click Launch -> Confirm -> Land.

Options:
  --api URL     backend to post telemetry to (default http://localhost:8000;
                production is https://fly-hawkeye.com/api)
  --drone ID    drone_id to use (default drone-sim)
  --direct      write telemetry straight to DynamoDB instead of over HTTP

It uses whatever DynamoDB the backend uses (your AWS credentials, or
DYNAMODB_ENDPOINT_URL for DynamoDB Local). Ctrl+C to stop.
"""

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from botocore.exceptions import ClientError

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from database.database import get_dynamodb_resource

DEFAULT_TARGET = (37.3352, -121.8811)  # San Jose, used if the mission has no location
HOME_OFFSET_DEG = 0.003  # the drone starts about 300 m from the target
CRUISE_ALT_M = 40.0
CLIMB_MPS = 4.0
CRUISE_MPS = 12.0
ORBIT_RADIUS_M = 60.0
METERS_PER_DEG_LAT = 111_320.0


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def meters_between(a, b):
    """Rough distance in meters between two (lat, lon) points (fine over a few km)."""
    dlat = (b[0] - a[0]) * METERS_PER_DEG_LAT
    dlon = (b[1] - a[1]) * METERS_PER_DEG_LAT * math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlon)


def move_toward(pos, target, meters):
    """Step from pos toward target by up to `meters`. Returns (new_pos, heading_deg)."""
    dlat = (target[0] - pos[0]) * METERS_PER_DEG_LAT
    dlon = (target[1] - pos[1]) * METERS_PER_DEG_LAT * math.cos(math.radians(pos[0]))
    dist = math.hypot(dlat, dlon)
    heading = (math.degrees(math.atan2(dlon, dlat)) + 360) % 360
    if dist <= meters or dist == 0:
        return target, heading
    f = meters / dist
    return (pos[0] + (target[0] - pos[0]) * f, pos[1] + (target[1] - pos[1]) * f), heading


class FakeDrone:
    def __init__(self, mission_id, drone_id, dynamodb, post_telemetry):
        self.mission_id = mission_id
        self.drone_id = drone_id
        self.dynamodb = dynamodb
        self.missions = dynamodb.Table("Missions")
        self.drones = dynamodb.Table("Drones")
        self.post_telemetry = post_telemetry

        self.phase = "on_ground"  # on_ground -> flying -> landing -> landed
        self.altitude = 0.0
        self.speed = 0.0
        self.heading = 0.0
        self.battery = 95.0
        self.orbit_angle = 0.0
        self.target = DEFAULT_TARGET
        self.position = None

    # ---- setup -------------------------------------------------------------

    def setup(self):
        mission = self._mission()
        location = mission.get("request_location") or {}
        if "latitude" in location and "longitude" in location:
            self.target = (float(location["latitude"]), float(location["longitude"]))
        else:
            print("! Mission has no location, so Launch can't assign a drone. Using San Jose as the target.")

        if mission.get("drone_id") and mission["drone_id"] != self.drone_id:
            print(f"Mission already has {mission['drone_id']}; simulating that drone instead.")
            self.drone_id = mission["drone_id"]

        self.position = (self.target[0] + HOME_OFFSET_DEG, self.target[1] + HOME_OFFSET_DEG)

        if not mission.get("drone_id"):
            # register (or reset) the fake drone right next to the target so it wins assignment
            self.drones.put_item(Item={
                "drone_id": self.drone_id,
                "availability": "available",
                "battery_pct": Decimal(str(round(self.battery))),
                "latitude": Decimal(str(self.position[0])),
                "longitude": Decimal(str(self.position[1])),
                "last_seen": utc_now(),
            })
            print(f"Registered {self.drone_id} as available, ~{meters_between(self.position, self.target):.0f} m from the target.")
            print("Now click Launch on the Dashboard.")

    def _mission(self):
        mission = self.missions.get_item(Key={"mission_id": self.mission_id}).get("Item")
        if mission is None:
            raise SystemExit(f"Mission '{self.mission_id}' was not found. Create it on the Deploy page first.")
        return mission

    # ---- handshake (what microcontroller/launch_sequence.py should do) ---------

    def _set_status(self, field, expected, new):
        """Change launch_status/landing_status only if it's still `expected`."""
        try:
            self.missions.update_item(
                Key={"mission_id": self.mission_id},
                UpdateExpression=f"SET {field} = :new",
                ConditionExpression=f"{field} = :expected",
                ExpressionAttributeValues={":new": new, ":expected": expected},
            )
            print(f"{field}: {expected} -> {new}")
            return True
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise

    def handle_handshake(self, mission):
        if mission.get("drone_id") and mission["drone_id"] != self.drone_id:
            print(f"Mission was assigned {mission['drone_id']}; simulating that drone instead.")
            self.drone_id = mission["drone_id"]

        launch = mission.get("launch_status")
        landing = mission.get("landing_status")

        if launch == "requested":
            self._set_status("launch_status", "requested", "ready")
        elif launch == "confirmed" and self.phase == "on_ground":
            if self._set_status("launch_status", "confirmed", "launched"):
                self.phase = "flying"

        if landing == "requested" and self.phase == "flying":
            if self._set_status("landing_status", "requested", "landing"):
                self.phase = "landing"

    # ---- flight ----------------------------------------------------------------

    def fly(self, dt):
        if self.phase == "flying":
            self.altitude = min(CRUISE_ALT_M, self.altitude + CLIMB_MPS * dt)
            if meters_between(self.position, self.target) > ORBIT_RADIUS_M + 5:
                self.position, self.heading = move_toward(self.position, self.target, CRUISE_MPS * dt)
            else:
                # circle the target, like it's tracking the vehicle
                self.orbit_angle = (self.orbit_angle + CRUISE_MPS * dt / ORBIT_RADIUS_M) % (2 * math.pi)
                north = ORBIT_RADIUS_M * math.cos(self.orbit_angle)
                east = ORBIT_RADIUS_M * math.sin(self.orbit_angle)
                self.position = (
                    self.target[0] + north / METERS_PER_DEG_LAT,
                    self.target[1] + east / (METERS_PER_DEG_LAT * math.cos(math.radians(self.target[0]))),
                )
                self.heading = (math.degrees(self.orbit_angle) + 90) % 360
            self.speed = CRUISE_MPS
            self.battery = max(0.0, self.battery - 0.05 * dt)
        elif self.phase == "landing":
            self.speed = 0.0
            self.altitude = max(0.0, self.altitude - CLIMB_MPS * dt)
            if self.altitude == 0.0:
                self.phase = "landed"
                self._set_status("landing_status", "landing", "landed")
                self.drones.update_item(
                    Key={"drone_id": self.drone_id},
                    UpdateExpression="SET availability = :available",
                    ExpressionAttributeValues={":available": "available"},
                )
        else:
            self.speed = 0.0

    def payload(self):
        """Same nested shape microcontroller/heartbeat.py sends to POST /telemetry."""
        armed = self.phase in ("flying", "landing")
        return {
            "drone_id": self.drone_id,
            "mission_id": self.mission_id,
            "published_timestamp": utc_now(),
            "telemetry": {
                "timestamp": utc_now(),
                "position": {
                    "latitude_deg": round(self.position[0], 7),
                    "longitude_deg": round(self.position[1], 7),
                    "relative_altitude_m": round(self.altitude, 1),
                },
                "motion": {"speed_mps": round(self.speed, 1), "heading_deg": round(self.heading)},
                "gps": {"fix_type": 3, "satellites_visible": 14},
                "battery": {
                    "percentage": round(self.battery, 1),
                    "voltage_v": round(14.8 * (0.85 + 0.15 * self.battery / 100), 2),
                    "current_a": 18.0 if armed else 0.4,
                },
                "attitude": {"roll_deg": 2.0 if armed else 0.0, "pitch_deg": -3.0 if armed else 0.0, "yaw_deg": round(self.heading)},
            },
            "flight_controller": {"armed": armed, "mode": "GUIDED" if armed else "STABILIZE", "connected": True},
            "readiness": {"ready": True, "reasons": []},
        }

    def step(self, dt=1.0):
        self.handle_handshake(self._mission())
        self.fly(dt)
        self.post_telemetry(self.payload())


def http_poster(api_url):
    url = api_url.rstrip("/") + "/telemetry"

    def post(payload):
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                response.read()
        except urllib.error.HTTPError as error:
            print(f"! POST {url} -> {error.code}: {error.read().decode()[:200]}")
        except urllib.error.URLError as error:
            print(f"! Can't reach {url} ({error.reason}). Is the backend running?")

    return post


def main():
    parser = argparse.ArgumentParser(description="Pretend to be the drone's Raspberry Pi.")
    parser.add_argument("mission_id", help="mission to fly, e.g. 0003")
    parser.add_argument("--api", default="http://localhost:8000", help="backend URL")
    parser.add_argument("--drone", default="drone-sim", help="drone_id to use")
    parser.add_argument("--direct", action="store_true", help="write telemetry straight to DynamoDB")
    args = parser.parse_args()

    dynamodb = get_dynamodb_resource()
    if args.direct:
        from telemetry import save_telemetry

        def post(payload):
            save_telemetry(payload, dynamodb=dynamodb)
    else:
        post = http_poster(args.api)

    drone = FakeDrone(args.mission_id.strip(), args.drone, dynamodb, post)
    drone.setup()
    print(f"Sending telemetry for {drone.drone_id} every second. Ctrl+C to stop.")
    try:
        while drone.phase != "landed":
            started = time.monotonic()
            drone.step()
            time.sleep(max(0.0, 1.0 - (time.monotonic() - started)))
        print("Landed. Done.")
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
