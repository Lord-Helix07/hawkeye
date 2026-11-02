import json
import math
import sys
from decimal import Decimal

from botocore.exceptions import BotoCoreError, ClientError

#from shivaji --> this import is how ur gonna access the database
from database import get_dynamodb_resource


#from shivaji
def assign_nearest_drone(mission_id):
    """Assign the nearest available live drone and return the updated mission."""
    #all the tables we will need 
    dynamodb = get_dynamodb_resource()
    #by setting dynamodb to the get_dynamodb_resource, we get to use it for all the tables
    missions = dynamodb.Table("Missions")
    drones = dynamodb.Table("Drones")
    mission = missions.get_item(Key={"mission_id": mission_id}).get("Item")

    #edge check for NO mission
    if mission is None:   raise ValueError(f"Mission '{mission_id}' was not found.")
    #if the mission already has a drone --> will be blocked on frontend
    if mission.get("drone_id") or mission.get("assigned_drone_id"): raise ValueError(f"Mission '{mission_id}' already has a drone.")

    #target contains the location of the mission, but not as a pair of lat/lon
    target = mission.get("request_location") or {}
    #if null (shouldnt be)
    if "latitude" not in target or "longitude" not in target:  raise ValueError("Mission needs a latitude and longitude.")
    #origin is the location of the drone in a  pair of num
    origin = (float(target["latitude"]), float(target["longitude"]))


    #logic to find the nearest drone
    nearest = None
    for drone in drones.scan().get("Items", []):
        #if not available or battery is low, skip
        if drone.get("availability") != "available" or float(drone.get("battery_pct", 0)) <= 20:
            continue

        #if u dont have location --> assume farthest
        if "latitude" not in drone or "longitude" not in drone:
            distance = math.pi * 6371000
        
        #u have location and its available
        else:
            #calculate distance between origin and drone --> distance formula 
            lat1, lon1 = map(math.radians, origin)
            lat2, lon2 = map(math.radians, (float(drone["latitude"]), float(drone["longitude"])))

            # ripped from the internet. formula for distance by world geometry
            arc = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
            distance = 6371000 * 2 * math.asin(math.sqrt(arc))
        #new nearest
        if nearest is None or (distance, drone["drone_id"]) < nearest:
            nearest = (distance, drone["drone_id"])
    #if no nearest, no drone available
    if nearest is None: raise ValueError("No available drone. Please communicate with the team to turn on or charge their drones.")
    #nearest will now NOT be none, and so we can assign the drone
    distance, drone_id = nearest
    #for printing
    distance = Decimal(str(round(distance, 3)))

    #transaction to update the mission and drone tables 
    try:
        dynamodb.meta.client.transact_write_items(TransactItems=[
            {"Update": {
                "TableName": "Missions",
                "Key": {"mission_id": mission_id},
                "UpdateExpression": "SET drone_id = :drone, assigned_drone_id = :drone, assignment_distance_m = :distance",
                "ConditionExpression": "attribute_exists(mission_id) AND attribute_not_exists(drone_id) AND attribute_not_exists(assigned_drone_id)",
                "ExpressionAttributeValues": {":drone": drone_id, ":distance": distance},
            }},
            {"Update": {
                "TableName": "Drones",
                "Key": {"drone_id": drone_id},
                "UpdateExpression": "SET availability = :assigned",
                "ConditionExpression": "attribute_exists(drone_id) AND availability = :available",
                "ExpressionAttributeValues": {":assigned": "assigned", ":available": "available"},
            }},
        ])
    except dynamodb.meta.client.exceptions.TransactionCanceledException:
        raise ValueError("Assignment rejected: the mission or drone changed. No update was applied.")
    #output the mission and drone
    return {
        "message": "Nearest eligible drone assigned successfully.",
        "mission": missions.get_item(Key={"mission_id": mission_id}).get("Item"),
        "distance_m": distance,
    }


def prompt_id(label): # user input for an ID
    value = input(label).strip()
    while not value:
        print('An ID is required.')
        value = input(label).strip()
    return value


def main():
    try: #Main Code for drone assignment
        mission_id = prompt_id('Enter the mission ID: ')
        result = assign_nearest_drone(mission_id)
        print(json.dumps(result, indent=2, default=str))
        return 0

    except ValueError as error:  # Display the assignment explanation.
        print(f'Assignment failed: {error}', file=sys.stderr)
        return 1

    except (BotoCoreError, ClientError): #connection error
        print('Could not confirm the request. Check DynamoDB. Refresh before retrying: it may already be saved.', file=sys.stderr)
        return 1
        
    except (KeyboardInterrupt, EOFError): # user cancellation
        print('\nCancelled.', file=sys.stderr)
        return 1


if __name__ == '__main__': # Runs the main code when ran directly
    sys.exit(main())
