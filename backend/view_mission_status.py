"""
View Mission Status

Fields: Mission ID
Action: Retrieve the selected mission.
Side Actions: Verify mission exists.
Output: Print Missions row corresponding to the entered mission ID or error message.
Database Update: None (read-only).
"""


# threading allows us to run the FastAPI server in the background
# while the program continues running the terminal prompt.
import threading

# time allows us to briefly wait for the FastAPI server to start.
import time


# httpx allows this program to send an HTTP request to FastAPI.
import httpx

# uvicorn runs the FastAPI application as a local web server.
import uvicorn

# These exceptions allow us to handle DynamoDB connection problems.
from botocore.exceptions import BotoCoreError, ClientError

# FastAPI creates the API application.
# HTTPException allows us to return clear HTTP error messages.
from fastapi import FastAPI, HTTPException

# jsonable_encoder converts DynamoDB data into a format that
# FastAPI can safely return as JSON.
from fastapi.encoders import jsonable_encoder

# This function already exists in backend/database.py.
# It creates the connection to AWS DynamoDB or DynamoDB Local.
from database import get_dynamodb_resource


# Create the FastAPI application.
#
# The title appears in the automatic FastAPI documentation
# available at http://127.0.0.1:8000/docs.
app = FastAPI(title="View Mission Status API")


@app.get("/missions/{mission_id}")
def get_mission_status(mission_id: str):

    # Remove accidental spaces before or after the Mission ID.
    mission_id = mission_id.strip()

    # Do not send an empty Mission ID to DynamoDB.
    if not mission_id:
        raise HTTPException(
            status_code=400,
            detail="Mission ID cannot be empty.",
        )

    try:
        # Get the DynamoDB resource using the existing function
        # from database.py.
        #
        # This function uses:
        # - AWS DynamoDB by default, or
        # - DynamoDB Local if DYNAMODB_ENDPOINT_URL is set.
        dynamodb = get_dynamodb_resource()

        # Select the table named "Missions".
        table = dynamodb.Table("Missions")

        # Read one item using the table's primary key.
        #
        # According to the database schema, the primary key is:
        #     mission_id
        #
        # This is a read-only operation. It does not change the table.
        response = table.get_item(
            Key={
                "mission_id": mission_id
            }
        )

        # DynamoDB places the result inside the "Item" field.
        # If no matching item exists, "Item" will be missing.
        mission = response.get("Item")

        # Handle a Mission ID that does not exist.
        if mission is None:
            raise HTTPException(
                status_code=404,
                detail=f"Mission '{mission_id}' was not found.",
            )

        # Return the mission record as JSON.
        #
        # jsonable_encoder helps convert DynamoDB values into a format
        # that FastAPI can send in an HTTP response.
        return jsonable_encoder(mission)

    # Re-raise HTTPException so FastAPI keeps the correct status code
    # and error message for empty or nonexistent Mission IDs.
    except HTTPException:
        raise

    # Handle problems connecting to DynamoDB or reading from the table.
    #
    # A 503 status code means the service is temporarily unavailable.
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(
            status_code=503,
            detail=f"Database error: {error}",
        )


def start_api():
    """
    Start the FastAPI application using Uvicorn.
    DynamoDB Local uses port 8001, while FastAPI uses port 8000.
    These are separate services, so they do not conflict.
    """

    # Create the Uvicorn server configuration.
    server_config = uvicorn.Config(
        app,


        # on this computer.
        host="127.0.0.1",

        # FastAPI will listen on port 8000.
        port=8000,

        # Only show important server messages.
        log_level="warning",
    )

    # Start the FastAPI server.
    uvicorn.Server(server_config).run()


def main():
    """
    Run the terminal portion of the program.

    This function:
    1. Starts FastAPI in the background.
    2. Prompts the user for a Mission ID.
    3. Sends a request through FastAPI.
    4. Prints the result.
    """

    # Create a background thread for the FastAPI server.
    #
    # A thread allows the API and the terminal prompt to run
    # at the same time.
    api_thread = threading.Thread(
        target=start_api,

        # The server will close automatically when this program ends.
        daemon=True,
    )

    # Start the FastAPI server thread.
    api_thread.start()

    # Give Uvicorn a moment to begin listening on port 8000.
    time.sleep(1)

    # Ask the user to enter the Mission ID.
    mission_id = input("Enter Mission ID: ").strip()

    # Check for empty input before sending the request.
    if not mission_id:
        print("Error: Mission ID cannot be empty.")
        return

    try:
        # Send a GET request to the FastAPI endpoint.
        #
        # Example:
        #     http://127.0.0.1:8000/missions/M001
        #
        # This means the terminal program communicates with the
        # database through FastAPI instead of accessing DynamoDB
        # directly from the command-line section.
        response = httpx.get(
            f"http://127.0.0.1:8000/missions/{mission_id}",
            timeout=5,
        )

        # Status code 200 means the mission was found.
        if response.status_code == 200:
            print("\nMission found:")

            # Print the mission record returned by FastAPI.
            print(response.json())

        # Status code 404 means the Mission ID does not exist.
        elif response.status_code == 404:
            print(f"\nError: Mission '{mission_id}' was not found.")

        # Handle other errors, such as a database error.
        else:
            error_details = response.json().get(
                "detail",
                "Unknown API error.",
            )
            print(f"\nError: {error_details}")

    # Handle problems connecting to the FastAPI server.
    except httpx.RequestError as error:
        print(f"\nError connecting to FastAPI: {error}")


# This condition makes sure main() only runs when this file
# is executed directly.
#
# It prevents the terminal program from running automatically
# if another file imports this module.
if __name__ == "__main__":
    main()