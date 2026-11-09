"""Manually assisted drone launch Lambda and local test runner."""

import json
import os
import sys
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


# This is the DynamoDB table that stores the mission records.
TABLE_NAME = os.getenv("MISSIONS_TABLE", "Missions")

# This is optional and is only used when the file is run as a local tester.
LAMBDA_FUNCTION_NAME = os.getenv("HAWKEYE_LAMBDA_FUNCTION")


# This creates the response format that API Gateway sends back to the frontend.
def make_response(status_code, body):
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


# This gets the Mission ID from the different request formats that API Gateway can send.
def get_mission_id(event):
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

    if isinstance(body, dict):
        return str(body.get("mission_id", "")).strip()

    return ""


# launch_status values on the Missions row. The Raspberry Pi
# (microcontroller/launch_sequence.py) uses the same words:
#   website sets  requested -> Pi sets ready / not_ready
#   operator sets confirmed -> Pi sets launched / failed
LAUNCH_REQUESTED = "requested"
LAUNCH_READY = "ready"
LAUNCH_CONFIRMED = "confirmed"
# a new request is only allowed when there is no launch yet, or the last one didn't work
RETRYABLE_LAUNCH_STATUSES = ("not_ready", "failed")
CLOSED_MISSION_STATUSES = {"completed", "aborted", "failed"}


class LaunchRejected(Exception):
    """The launch request was refused. status_code says why (404 or 409)."""

    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def request_launch(mission_id, table=None):
    """Set launch_status = requested on the mission and return the updated row.

    Used by POST /missions/{mission_id}/launch (launch.py) and by the Lambda below.
    Raises LaunchRejected when the mission can't launch, ClientError for DynamoDB problems.
    """
    table = table or boto3.resource("dynamodb").Table(TABLE_NAME)

    # Look up the mission that the user wants to launch.
    mission = table.get_item(Key={"mission_id": mission_id}).get("Item")
    if mission is None:
        raise LaunchRejected(404, f"Mission '{mission_id}' was not found")

    # A mission needs a drone assigned before it can launch (AssignDrone.py sets drone_id).
    drone_id = mission.get("drone_id")
    if not drone_id:
        raise LaunchRejected(409, "Launch rejected: no drone is assigned")

    # Only check readiness if the sample mission includes a readiness field.
    readiness = mission.get("drone_status", mission.get("drone_readiness"))
    if readiness is not None and str(readiness).upper() not in {"READY", "IDLE", "ASSIGNED"}:
        raise LaunchRejected(409, f"Launch rejected: drone '{drone_id}' is not ready")

    if str(mission.get("status", "")).lower() in CLOSED_MISSION_STATUSES:
        raise LaunchRejected(409, f"Launch rejected: mission status is '{mission.get('status')}'")

    launch_status = mission.get("launch_status")
    if launch_status and launch_status not in RETRYABLE_LAUNCH_STATUSES:
        raise LaunchRejected(409, f"Launch rejected: launch is already '{launch_status}'")

    # The condition stops two clicks (or two officers) from both requesting a launch.
    try:
        updated = table.update_item(
            Key={"mission_id": mission_id},
            UpdateExpression=(
                "SET launch_status = :requested, launch_request_timestamp = :timestamp "
                "REMOVE launch_reason, launch_reasons"
            ),
            ConditionExpression=(
                "attribute_not_exists(launch_status) OR launch_status IN (:not_ready, :failed)"
            ),
            ExpressionAttributeValues={
                ":requested": LAUNCH_REQUESTED,
                ":timestamp": utc_now(),
                ":not_ready": RETRYABLE_LAUNCH_STATUSES[0],
                ":failed": RETRYABLE_LAUNCH_STATUSES[1],
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise LaunchRejected(409, "Launch rejected: request already exists") from error
        raise

    return updated["Attributes"]


# This is the AWS Lambda function that handles the Launch Drone request.
def lambda_handler(event, context):
    # This handles the browser's preflight request before the real POST request.
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return make_response(200, {"message": "CORS preflight accepted"})

    # Get the Mission ID before checking anything in the database.
    mission_id = get_mission_id(event)
    if not mission_id:
        return make_response(400, {"error": "Mission ID is required"})

    try:
        mission = request_launch(mission_id)
    except LaunchRejected as error:
        return make_response(error.status_code, {"error": str(error)})
    except ClientError as error:
        # This catches DynamoDB errors and gives the caller a readable message.
        error_code = error.response.get("Error", {}).get("Code", "unknown")
        return make_response(500, {"error": f"DynamoDB error: {error_code}"})

    # Return the updated Missions row after the launch request succeeds.
    return make_response(200, {
        "message": "Launch request submitted; awaiting manual takeoff confirmation",
        "mission": mission,
    })


# This function acts like the future frontend button when the file is run locally.
def submit_launch_request(mission_id):
    # The deployed version invokes the Lambda through AWS.
    if LAMBDA_FUNCTION_NAME:
        client = boto3.client("lambda")
        result = client.invoke(
            FunctionName=LAMBDA_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps({"mission_id": mission_id}).encode("utf-8"),
        )
        return json.loads(result["Payload"].read())

    # This local fallback directly tests the Lambda logic when no function name is set.
    return lambda_handler({"mission_id": mission_id}, None)


# This runs the temporary terminal version of the Launch Drone button.
def main():
    # Ask for the required field that the future frontend will provide.
    mission_id = input("Mission ID: ").strip()
    if not mission_id:
        print("Error: Mission ID is required.")
        return 1

    # Send the Mission ID to the Lambda logic and read its response.
    try:
        result = submit_launch_request(mission_id)
        body = json.loads(result.get("body", "{}"))
    except Exception as error:
        print(f"Error invoking launch Lambda: {error}")
        return 1

    # Print the updated row when the request succeeds.
    if result.get("statusCode") == 200:
        print("Updated Missions row:")
        print(json.dumps(body["mission"], indent=2, default=str))
        print(body["message"])
        return 0

    # Print the error returned by Lambda when the request fails.
    print(f"Error: {body.get('error', body)}")
    return 1


# This lets the same file work as a normal Python program from the terminal.
if __name__ == "__main__":
    sys.exit(main())
