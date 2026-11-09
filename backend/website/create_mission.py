from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from botocore.exceptions import ClientError

from database.database import get_dynamodb_resource
from mission_numbers import new_mission_id, usable_mission_id

def get_required_input(question):
    while True:
        answer = input(question).strip()

        if answer!= "":
            return answer

        print("This field is required.")

def get_number(question):
    while True:
        answer = input(question).strip()

        try:
            return Decimal(answer)
        except InvalidOperation:
            print("Please enter a valid number.")


def create_mission_record(target_vehicle, request_location=None, mission_id=None, dynamodb=None):
    """Save a new mission and return it.

    Used by the terminal prompt below and by POST /missions in view_mission_status.py.
    mission_id is a random code like "HWK-07-2410". Pass one in to keep the
    code already shown on the Deploy page.
    """
    dynamodb = dynamodb or get_dynamodb_resource()
    table = dynamodb.Table("Missions")

    # prefer the code from the page, then a few fresh ones if that one is taken
    candidates = []
    preferred = usable_mission_id(mission_id)
    if preferred:
        candidates.append(preferred)
    while len(candidates) < 5:
        candidate = new_mission_id()
        if candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        mission = {
            "mission_id": candidate,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "target_vehicle": target_vehicle,
        }
        if request_location:
            mission["request_location"] = request_location

        try:
            # never overwrite an existing mission
            table.put_item(
                Item=mission,
                ConditionExpression="attribute_not_exists(mission_id)",
            )
            return mission
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise

    raise RuntimeError("Could not assign a mission number")


def create_mission():
    print("Create a New Mission")
    print("--------------------")

    make = get_required_input("Vehicle make: ")
    model = get_required_input("Vehicle model: ")
    color = get_required_input("Vehicle color: ")
    vehicle_type = get_required_input("Vehicle type: ")
    license_plate = get_required_input("License plate: ")
    identifying_features = get_required_input(
        "Identifying features: "
    )
    #NOTE FROM SHIVAJI:  shud be constant
    latitude = get_number("Requested launch latitude: ")
    longitude = get_number("Requested launch longitude: ")

    try:
        mission = create_mission_record(
            target_vehicle={
                "make": make,
                "model": model,
                "color": color,
                "type": vehicle_type,
                "license_plate": license_plate,
                "identifying_features": identifying_features
            },
            request_location={
                "latitude": latitude,
                "longitude": longitude
            },
        )

        print("\nMission created successfully!")
        print(mission)

    except Exception as error:
        print("\nError creating mission:")
        print(error)

if __name__ == "__main__":
    create_mission()
