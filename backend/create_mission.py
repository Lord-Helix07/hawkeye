from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from database.database import get_dynamodb_resource

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

    latitude = get_number("Requested launch latitude: ")
    longitude = get_number("Requested launch longitude: ")

    mission_id = "msn-" + uuid4().hex[:8]

    created_at = datetime.now(timezone.utc).isoformat()

    mission = {
        "mission_id": mission_id,
        "created_at": created_at,
        "status": "pending",

        "target_vehicle": {
            "make": make,
            "model": model,
            "color": color,
            "type": vehicle_type,
            "license_plate": license_plate,
            "identifying_features": identifying_features
        },

        "request_location": {
            "latitude": latitude,
            "longitude": longitude
        }
    }

    try:
        dynamodb = get_dynamodb_resource()

        missions_table = dynamodb.Table("Missions")

        missions_table.put_item(Item=mission)

        print("\nMission created successfully!")
        print(mission)

    except Exception as error:
        print("\nError creating mission:")
        print(error)

if __name__ == "__main__":
    create_mission()

