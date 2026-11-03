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


# This is the AWS Lambda function that handles the Launch Drone request.
def lambda_handler(event, context):
    # This handles the browser's preflight request before the real POST request.
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return make_response(200, {"message": "CORS preflight accepted"})

    # Get the Mission ID before checking anything in the database.
    mission_id = get_mission_id(event)
    if not mission_id:
        return make_response(400, {"error": "Mission ID is required"})

    # Lambda uses its AWS permissions to access the Missions table.
    table = boto3.resource("dynamodb").Table(TABLE_NAME)

    try:
        # Look up the mission that the user wants to launch.
        mission = table.get_item(Key={"mission_id": mission_id}).get("Item")
        if mission is None:
            return make_response(404, {"error": f"Mission '{mission_id}' was not found"})

        # A mission needs a drone assigned before it can launch.
        drone_id = mission.get("assigned_drone_id")
        if not drone_id:
            return make_response(409, {"error": "Launch rejected: no drone is assigned"})

        # Only check readiness if the sample mission includes a readiness field.
        readiness = mission.get("drone_status", mission.get("drone_readiness"))
        if readiness is not None and str(readiness).upper() not in {"READY", "IDLE", "ASSIGNED"}:
            return make_response(409, {"error": f"Launch rejected: drone '{drone_id}' is not ready"})

        # Do not launch a mission that already started or already has a request.
        status = str(mission.get("status", "")).lower()
        if status == "launch_requested" or mission.get("launch_request_timestamp"):
            return make_response(409, {"error": "Launch rejected: request already exists"})
        if status in {"active", "completed", "aborted", "failed"}:
            return make_response(409, {"error": f"Launch rejected: mission status is '{mission.get('status')}'"})

        # Save the request time in UTC so every service uses the same time zone.
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Update the status and timestamp in one database operation.
        # The condition stops duplicate requests from updating the same mission.
        updated = table.update_item(
            Key={"mission_id": mission_id},
            UpdateExpression="SET #status = :requested, launch_request_timestamp = :timestamp",
            ConditionExpression="attribute_not_exists(launch_request_timestamp) AND (attribute_not_exists(#status) OR #status <> :requested)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":requested": "launch_requested", ":timestamp": timestamp},
            ReturnValues="ALL_NEW",
        )
    except ClientError as error:
        # This catches DynamoDB errors and gives the caller a readable message.
        error_code = error.response.get("Error", {}).get("Code", "unknown")
        if error_code == "ConditionalCheckFailedException":
            return make_response(409, {"error": "Launch rejected: request already exists"})
        return make_response(500, {"error": f"DynamoDB error: {error_code}"})

    # Return the updated Missions row after the launch request succeeds.
    return make_response(200, {
        "message": "Launch request submitted; awaiting manual takeoff confirmation",
        "mission": updated["Attributes"],
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
