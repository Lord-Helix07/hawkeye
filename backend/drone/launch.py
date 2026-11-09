"""
Launch and landing routes the Dashboard calls.

The website and the Raspberry Pi talk through the mission's row in Missions:

    launch_status    website sets "requested"  -> Pi answers "ready" or "not_ready"
                     operator sets "confirmed" -> Pi answers "launched" or "failed"
    landing_status   website sets "requested"  -> Pi should answer "landing" / "landed" / "failed"

POST /missions/{mission_id}/launch            assign the nearest drone (if needed), request launch
POST /missions/{mission_id}/confirm-launch    operator OK after the Pi reported ready
POST /missions/{mission_id}/request-landing   ask the drone to land
"""

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder

from AssignDrone import assign_nearest_drone
from database.database import get_dynamodb_resource
from launch_drone import LAUNCH_CONFIRMED, LAUNCH_READY, LaunchRejected, request_launch, utc_now

router = APIRouter(tags=["launch"])

LANDING_REQUESTED = "requested"
# a drone that has been asked to take off (or is flying) can be asked to land
LANDABLE_LAUNCH_STATUSES = ("confirmed", "launched")


def _missions_table():
    return get_dynamodb_resource().Table("Missions")


def _get_mission(table, mission_id):
    mission = table.get_item(Key={"mission_id": mission_id}).get("Item")
    if mission is None:
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' was not found")
    return mission


def _condition_failed(error):
    return error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


@router.post("/missions/{mission_id}/launch")
def launch_mission(mission_id: str):
    """Assign the nearest available drone if the mission has none, then request launch."""
    mission_id = mission_id.strip()
    try:
        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table("Missions")
        mission = _get_mission(table, mission_id)

        if not mission.get("drone_id"):
            try:
                assign_nearest_drone(mission_id, dynamodb=dynamodb)
            except ValueError as error:
                # no location, no free drone, or someone else assigned one first
                raise HTTPException(status_code=409, detail=str(error)) from error

        mission = request_launch(mission_id, table=table)
    except LaunchRejected as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(status_code=503, detail=f"Database error: {error}") from error

    return jsonable_encoder(mission)


@router.post("/missions/{mission_id}/confirm-launch")
def confirm_launch(mission_id: str):
    """Operator confirms takeoff. Only allowed once the Pi has reported launch_status = ready."""
    mission_id = mission_id.strip()
    table = _missions_table()
    try:
        updated = table.update_item(
            Key={"mission_id": mission_id},
            UpdateExpression="SET launch_status = :confirmed, launch_confirmed_timestamp = :now",
            ConditionExpression="attribute_exists(mission_id) AND launch_status = :ready",
            ExpressionAttributeValues={
                ":confirmed": LAUNCH_CONFIRMED,
                ":ready": LAUNCH_READY,
                ":now": utc_now(),
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as error:
        if _condition_failed(error):
            mission = _get_mission(table, mission_id)  # 404 if it doesn't exist
            current = mission.get("launch_status") or "not requested"
            raise HTTPException(
                status_code=409,
                detail=f"Can only confirm once the drone is ready (launch is '{current}')",
            ) from error
        raise HTTPException(status_code=503, detail=f"Database error: {error}") from error
    except BotoCoreError as error:
        raise HTTPException(status_code=503, detail=f"Database error: {error}") from error

    return jsonable_encoder(updated["Attributes"])


@router.post("/missions/{mission_id}/request-landing")
def request_landing(mission_id: str):
    """Ask the mission's drone to land: sets landing_status = requested."""
    mission_id = mission_id.strip()
    table = _missions_table()
    try:
        updated = table.update_item(
            Key={"mission_id": mission_id},
            UpdateExpression="SET landing_status = :requested, landing_request_timestamp = :now",
            ConditionExpression=(
                "attribute_exists(mission_id) AND launch_status IN (:confirmed, :launched) "
                "AND (attribute_not_exists(landing_status) OR landing_status = :failed)"
            ),
            ExpressionAttributeValues={
                ":requested": LANDING_REQUESTED,
                ":now": utc_now(),
                ":confirmed": LANDABLE_LAUNCH_STATUSES[0],
                ":launched": LANDABLE_LAUNCH_STATUSES[1],
                ":failed": "failed",
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as error:
        if _condition_failed(error):
            mission = _get_mission(table, mission_id)
            if mission.get("landing_status") and mission.get("landing_status") != "failed":
                detail = f"Landing is already '{mission['landing_status']}'"
            else:
                detail = "The drone hasn't taken off yet"
            raise HTTPException(status_code=409, detail=detail) from error
        raise HTTPException(status_code=503, detail=f"Database error: {error}") from error
    except BotoCoreError as error:
        raise HTTPException(status_code=503, detail=f"Database error: {error}") from error

    return jsonable_encoder(updated["Attributes"])
