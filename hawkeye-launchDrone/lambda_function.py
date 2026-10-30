"""AWS Lambda handler for a manually assisted drone launch request."""

import json
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


TABLE_NAME = os.getenv("MISSIONS_TABLE", "Missions")


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "OPTIONS,POST",
        },
        "body": json.dumps(body, default=str),
    }


def get_mission_id(event):
    """Read mission_id from direct Lambda, API Gateway body, or path parameters."""
    if event.get("mission_id"):
        return str(event["mission_id"]).strip()

    path_parameters = event.get("pathParameters") or {}
    if path_parameters.get("mission_id"):
        return str(path_parameters["mission_id"]).strip()

    body = event.get("body") or {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return ""
    return str(body.get("mission_id", "")).strip() if isinstance(body, dict) else ""


def lambda_handler(event, context):
    """Submit one launch request and update the Missions DynamoDB row."""
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return response(200, {"message": "CORS preflight accepted"})

    mission_id = get_mission_id(event)
    if not mission_id:
        return response(400, {"error": "Mission ID is required"})

    table = boto3.resource("dynamodb").Table(TABLE_NAME)

    try:
        mission = table.get_item(Key={"mission_id": mission_id}).get("Item")
        if mission is None:
            return response(404, {"error": f"Mission '{mission_id}' was not found"})

        drone_id = mission.get("assigned_drone_id")
        if not drone_id:
            return response(409, {"error": "Launch rejected: no drone is assigned"})

        readiness = mission.get("drone_status", mission.get("drone_readiness"))
        if readiness is not None and str(readiness).upper() not in {"READY", "IDLE", "ASSIGNED"}:
            return response(409, {"error": f"Launch rejected: drone '{drone_id}' is not ready"})

        status = str(mission.get("status", "")).lower()
        if status == "launch_requested" or mission.get("launch_request_timestamp"):
            return response(409, {"error": "Launch rejected: request already exists"})
        if status in {"active", "completed", "aborted", "failed"}:
            return response(409, {"error": f"Launch rejected: mission status is '{mission.get('status')}'"})

        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        updated = table.update_item(
            Key={"mission_id": mission_id},
            UpdateExpression="SET #status = :requested, launch_request_timestamp = :timestamp",
            ConditionExpression="attribute_not_exists(launch_request_timestamp) AND (attribute_not_exists(#status) OR #status <> :requested)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":requested": "launch_requested", ":timestamp": timestamp},
            ReturnValues="ALL_NEW",
        )
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "unknown")
        if code == "ConditionalCheckFailedException":
            return response(409, {"error": "Launch rejected: request already exists"})
        return response(500, {"error": f"DynamoDB error: {code}"})

    return response(200, {
        "message": "Launch request submitted; awaiting manual takeoff confirmation",
        "mission": updated["Attributes"],
    })
