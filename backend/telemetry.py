"""
Telemetry routes the Raspberry Pi posts to (about once a second).

POST /telemetry                     microcontroller/heartbeat.py   (nested "position"/"motion"/... shape)
POST /flight-controller/status      microcontroller/fc_status.py   (flat "telemetry" shape, see
                                    microcontroller/backend_micro_comms.md)

Both shapes are flattened into one Telemetry row, keyed by drone_id + timestamp:
    { drone_id, timestamp, mission_id, latitude, longitude, altitude_m, speed_mps,
      heading_deg, battery_pct, battery_voltage, battery_current, gps_fix_type,
      satellites_visible, roll_deg, pitch_deg, yaw_deg, flight_controller, readiness }
The drone's row in Drones also gets its latest position and battery, so
AssignDrone.py picks the nearest drone from live data.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Body, HTTPException

from database.database import get_dynamodb_resource

router = APIRouter(tags=["telemetry"])


def _first(*values):
    """The first value that isn't None."""
    return next((value for value in values if value is not None), None)


def _to_dynamo(value):
    """DynamoDB needs Decimal instead of float, and drops nothing else."""
    return json.loads(json.dumps(value), parse_float=Decimal)


def normalize_payload(payload):
    """Turn either Pi payload shape into one flat Telemetry row (None values left out)."""
    drone_id = str(payload.get("drone_id") or "").strip()
    if not drone_id:
        raise HTTPException(status_code=422, detail="drone_id is required")

    telemetry = payload.get("telemetry") or {}
    position = telemetry.get("position") or {}
    motion = telemetry.get("motion") or {}
    gps = telemetry.get("gps") or {}
    battery = telemetry.get("battery") or {}
    attitude = telemetry.get("attitude") or {}

    row = {
        "drone_id": drone_id,
        "timestamp": _first(
            telemetry.get("timestamp"),
            payload.get("published_timestamp"),
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        ),
        "mission_id": payload.get("mission_id"),
        "latitude": _first(position.get("latitude_deg"), telemetry.get("latitude")),
        "longitude": _first(position.get("longitude_deg"), telemetry.get("longitude")),
        # height above the takeoff point, which is what the officer cares about
        "altitude_m": _first(
            position.get("relative_altitude_m"), position.get("altitude_m"), telemetry.get("altitude_m")
        ),
        "speed_mps": _first(motion.get("speed_mps"), telemetry.get("speed_mps")),
        "heading_deg": _first(motion.get("heading_deg"), telemetry.get("heading_deg")),
        "battery_pct": _first(battery.get("percentage"), telemetry.get("battery_pct")),
        "battery_voltage": _first(battery.get("voltage_v"), telemetry.get("battery_voltage")),
        "battery_current": _first(battery.get("current_a"), telemetry.get("battery_current")),
        "gps_fix_type": _first(gps.get("fix_type"), telemetry.get("gps_fix_type")),
        "satellites_visible": _first(gps.get("satellites_visible"), telemetry.get("satellites_visible")),
        "roll_deg": attitude.get("roll_deg"),
        "pitch_deg": attitude.get("pitch_deg"),
        "yaw_deg": attitude.get("yaw_deg"),
        "flight_controller": payload.get("flight_controller"),
        "readiness": payload.get("readiness"),
    }
    return _to_dynamo({key: value for key, value in row.items() if value is not None})


def save_telemetry(payload, dynamodb=None):
    """Save one Pi payload and refresh the drone's live position. Returns the saved row."""
    dynamodb = dynamodb or get_dynamodb_resource()
    row = normalize_payload(payload)
    dynamodb.Table("Telemetry").put_item(Item=row)

    # keep Drones in step for drone assignment; skip drones that aren't registered
    live = {key: row[key] for key in ("latitude", "longitude", "battery_pct") if key in row}
    live["last_seen"] = row["timestamp"]
    try:
        dynamodb.Table("Drones").update_item(
            Key={"drone_id": row["drone_id"]},
            UpdateExpression="SET " + ", ".join(f"{key} = :{key}" for key in live),
            ConditionExpression="attribute_exists(drone_id)",
            ExpressionAttributeValues={f":{key}": value for key, value in live.items()},
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
    return row


def _save(payload):
    try:
        row = save_telemetry(payload)
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(status_code=503, detail=f"Database error: {error}") from error
    return {"saved": True, "drone_id": row["drone_id"], "timestamp": row["timestamp"]}


@router.post("/telemetry", status_code=201)
def post_telemetry(payload: dict = Body(...)):
    return _save(payload)


@router.post("/flight-controller/status", status_code=201)
def post_flight_controller_status(payload: dict = Body(...)):
    return _save(payload)
