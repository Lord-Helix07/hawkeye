from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from database.database import get_dynamodb_resource
from mission_numbers import format_mission_number, take_next_mission_number

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


def create_mission_record(target_vehicle, request_location=None, dynamodb=None):
    """Save a new mission with the next mission number and return it.

    Used by the terminal prompt below and by POST /missions in view_mission_status.py.
    mission_id is the 4-digit number as text ("0001"), so it reads well on screen.
    """
    dynamodb = dynamodb or get_dynamodb_resource()

    mission_number = take_next_mission_number(dynamodb)

    mission = {
        "mission_id": format_mission_number(mission_number),
        "mission_number": mission_number,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "target_vehicle": target_vehicle,
    }
    if request_location:
        mission["request_location"] = request_location

    # the condition is a safety net: never overwrite an existing mission
    dynamodb.Table("Missions").put_item(
        Item=mission,
        ConditionExpression="attribute_not_exists(mission_id)",
    )
    return mission


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
