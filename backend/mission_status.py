"""
GET /missions/{mission_id}/status: everything the Dashboard shows, in one answer.

Combines the mission's row in Missions, the newest Telemetry row for its drone
and the mission's Alerts:

{
  mission_id, status, created_at, target_vehicle, drone_id,
  launch_status, launch_reason, launch_reasons, landing_status,
  telemetry: { latitude, longitude, speed_mps, battery_pct, altitude_m, heading_deg,
               timestamp, stale } or null,
  flight_controller: {...} or null,
  target_in_frame, tracking_status, last_seen, location,   <- null until the camera
  images: [],                                                  pipeline saves them
  flight_log: [{ time, message }]
}
"""

from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder

from database.database import get_dynamodb_resource

router = APIRouter(tags=["missions"])

# telemetry older than this is shown as "no signal" (the Pi posts once a second)
STALE_SECONDS = 10

TELEMETRY_FIELDS = ("latitude", "longitude", "speed_mps", "battery_pct", "altitude_m", "heading_deg", "timestamp")

LAUNCH_MESSAGES = {
    "ready": "Drone ready for takeoff, waiting for operator",
    "not_ready": "Drone not ready",
    "launched": "Drone launched",
    "failed": "Launch failed",
}


def _parse_time(text):
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def is_stale(timestamp, now=None):
    seen = _parse_time(timestamp)
    if seen is None:
        return True
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - seen).total_seconds() > STALE_SECONDS


def latest_telemetry(dynamodb, drone_id):
    response = dynamodb.Table("Telemetry").query(
        KeyConditionExpression=Key("drone_id").eq(drone_id),
        ScanIndexForward=False,  # newest timestamp first
        Limit=1,
    )
    items = response.get("Items", [])
    return items[0] if items else None


def mission_alerts(dynamodb, mission_id):
    response = dynamodb.Table("Alerts").query(
        KeyConditionExpression=Key("mission_id").eq(mission_id),
    )
    return response.get("Items", [])


def build_flight_log(mission, alerts):
    """Mission milestones plus Alerts, oldest first."""
    log = []
    vehicle = mission.get("target_vehicle") or {}
    if mission.get("created_at"):
        description = " ".join(
            str(vehicle[part]) for part in ("color", "make", "model") if vehicle.get(part)
        )
        plate = vehicle.get("license_plate")
        log.append({
            "time": mission["created_at"],
            "message": f"Mission created: {description}{f', {plate}' if plate else ''}".strip(),
        })
    if mission.get("launch_request_timestamp"):
        drone = mission.get("drone_id", "drone")
        log.append({"time": mission["launch_request_timestamp"], "message": f"Launch requested for {drone}"})
    if mission.get("launch_confirmed_timestamp"):
        log.append({"time": mission["launch_confirmed_timestamp"], "message": "Operator confirmed takeoff"})
    if mission.get("landing_request_timestamp"):
        log.append({"time": mission["landing_request_timestamp"], "message": "Landing requested"})
    for alert in alerts:
        log.append({"time": alert.get("alert_timestamp"), "message": alert.get("message", alert.get("alert_type", ""))})

    log.sort(key=lambda entry: str(entry["time"] or ""))
    return log


def build_mission_status(mission, telemetry_row, alerts, now=None):
    telemetry = None
    flight_controller = None
    if telemetry_row:
        telemetry = {field: telemetry_row.get(field) for field in TELEMETRY_FIELDS}
        telemetry["stale"] = is_stale(telemetry_row.get("timestamp"), now)
        flight_controller = telemetry_row.get("flight_controller")

    return {
        "mission_id": mission["mission_id"],
        "status": mission.get("status"),
        "created_at": mission.get("created_at"),
        "target_vehicle": mission.get("target_vehicle"),
        "drone_id": mission.get("drone_id"),
        "launch_status": mission.get("launch_status"),
        "launch_reason": mission.get("launch_reason"),
        "launch_reasons": mission.get("launch_reasons"),
        "landing_status": mission.get("landing_status"),
        "telemetry": telemetry,
        "flight_controller": flight_controller,
        # not produced yet: these come from the camera / tracking pipeline
        "target_in_frame": mission.get("target_in_frame"),
        "tracking_status": mission.get("tracking_status"),
        "last_seen": mission.get("last_seen"),
        "location": None,
        "images": [],
        "flight_log": build_flight_log(mission, alerts),
    }


@router.get("/missions/{mission_id}/status")
def get_mission_dashboard_status(mission_id: str):
    mission_id = mission_id.strip()
    try:
        dynamodb = get_dynamodb_resource()
        mission = dynamodb.Table("Missions").get_item(Key={"mission_id": mission_id}).get("Item")
        if mission is None:
            raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' was not found.")
        telemetry_row = latest_telemetry(dynamodb, mission["drone_id"]) if mission.get("drone_id") else None
        alerts = mission_alerts(dynamodb, mission_id)
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(status_code=503, detail=f"Database error: {error}") from error

    return jsonable_encoder(build_mission_status(mission, telemetry_row, alerts))
