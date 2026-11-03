"""Frontend/button-side code for sending a launch request to Lambda."""

import json
import os
import sys

import boto3


LAMBDA_FUNCTION_NAME = os.getenv("HAWKEYE_LAMBDA_FUNCTION")


def submit_launch_request(mission_id):
    """Invoke the backend Lambda with the Mission ID from the button."""
    if not LAMBDA_FUNCTION_NAME:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Set HAWKEYE_LAMBDA_FUNCTION before using the launch button"
            }),
        }

    # This is what the real Launch Drone button will eventually do.
    client = boto3.client("lambda")
    result = client.invoke(
        FunctionName=LAMBDA_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps({"mission_id": mission_id}).encode("utf-8"),
    )
    return json.loads(result["Payload"].read())


def main():
    # The prompt is just a temporary replacement for the frontend button.
    mission_id = input("Mission ID: ").strip()
    if not mission_id:
        print("Error: Mission ID is required.")
        return 1

    try:
        result = submit_launch_request(mission_id)
        body = json.loads(result.get("body", "{}"))
    except Exception as error:
        print(f"Error invoking launch Lambda: {error}")
        return 1

    if result.get("statusCode") == 200:
        print("Updated Missions row:")
        print(json.dumps(body["mission"], indent=2, default=str))
        print(body["message"])
        return 0

    print(f"Error: {body.get('error', body)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
