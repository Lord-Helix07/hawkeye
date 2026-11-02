import os
import math
from datetime import datetime, timezone
from decimal import Decimal #decimals in DynamoDB items
from urllib.parse import urlparse #breaks URL into components

import boto3 #for interacting with AWS services, including DynamoDB
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer # converting between Python type and Dynamo type
from botocore.config import Config #configure connectiion timeouts and retry

#from shivaji
DYNAMODB_ENDPOINT_URL = os.getenv("DYNAMODB_ENDPOINT_URL")
DYNAMODB_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"


def get_dynamodb_resource():
    """Return a DynamoDB resource for the AWS account in the default credential chain."""
    client_kwargs = {
        "region_name": DYNAMODB_REGION,
        "config": Config(retries={"max_attempts": 3, "mode": "standard"}),
    }
    if DYNAMODB_ENDPOINT_URL:
        client_kwargs["endpoint_url"] = DYNAMODB_ENDPOINT_URL
    return boto3.resource("dynamodb", **client_kwargs)


class AssignmentError(Exception): # custom message for assignment errors
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def local_client(): # prepare boto client for specific local DynamoDB endpoint
    endpoint = os.getenv('DYNAMODB_ENDPOINT_URL', 'http://127.0.0.1:8001')
    parsed = urlparse(endpoint)
    if parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise ValueError('This starter only permits a local DynamoDB endpoint.')
    return boto3.client('dynamodb', endpoint_url=endpoint,
        region_name='us-west-2', aws_access_key_id='local', aws_secret_access_key='local',
        config=Config(connect_timeout=2, read_timeout=5,
                      retries={'mode': 'standard', 'total_max_attempts': 2}))


def encode(item): #convert Python item to DynamoDB format
    serializer = TypeSerializer()
    return {key: serializer.serialize(value) for key, value in item.items()}


def decode(item): #convert DynamoDB item to Python format
    parser = TypeDeserializer()
    return {key: parser.deserialize(value) for key, value in item.items()}


class AssignmentStore: #stores the assignment data for missions and drones in DynamoDB
    def __init__(self, client, prefix=None, clock=None):
        self.client = client
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        prefix = prefix if prefix is not None else os.getenv('TABLE_PREFIX', 'HawkEyeDemo_')
        self.missions = prefix + 'Missions'
        self.drones = prefix + 'Drones'

    def create_tables(self): # create the tables
        for table, key in [(self.missions, 'mission_id'), (self.drones, 'drone_id')]:
            try:
                self.client.create_table(TableName=table, BillingMode='PAY_PER_REQUEST',
                    KeySchema=[{'AttributeName': key, 'KeyType': 'HASH'}],
                    AttributeDefinitions=[{'AttributeName': key, 'AttributeType': 'S'}])
            except self.client.exceptions.ResourceInUseException:
                pass  
            self.client.get_waiter('table_exists').wait(
                TableName=table, WaiterConfig={'Delay': 1, 'MaxAttempts': 20})

    def seed(self): # add fictional practice records 
        """Add fictional practice records without overwriting existing ones."""
        for number in range(1, 4):
            items = [
                (self.missions, 'mission_id', {'mission_id': f'MISSION-NEAR-{number:03}',
                 'status': 'PLANNED', 'drone_id': None,
                 'request_location': {'latitude': Decimal('34.05'), 'longitude': Decimal('-118.25')}}),
                (self.drones, 'drone_id', {'drone_id': f'DRONE-NEAR-{number:03}',
                 'availability_status': 'AVAILABLE', 'current_mission_id': None,
                 'connection_status': 'CONNECTED', 'last_seen_at': self.clock().isoformat(),
                 'location': {'latitude': Decimal('34.05') + Decimal(number) / 1000,
                              'longitude': Decimal('-118.25')}, 'demo_fixture': True})]
            for table, key, item in items:
                try:
                    self.client.put_item(TableName=table, Item=encode(item),
                        ConditionExpression='attribute_not_exists(#key)',
                        ExpressionAttributeNames={'#key': key})
                except self.client.exceptions.ConditionalCheckFailedException:
                    pass

    def list_items(self, table): # read all items from the specified table
        items = []
        for page in self.client.get_paginator('scan').paginate(TableName=table, ConsistentRead=True):
            items.extend(decode(item) for item in page['Items'])
        key = 'mission_id' if table == self.missions else 'drone_id'
        return sorted(items, key=lambda item: item[key])

    def pair(self, mission_id, drone_id): #read both mission and drone records
        result = self.client.transact_get_items(TransactItems=[
            {'Get': {'TableName': self.missions, 'Key': encode({'mission_id': mission_id})}},
            {'Get': {'TableName': self.drones, 'Key': encode({'drone_id': drone_id})}}])
        return [decode(entry['Item']) if 'Item' in entry else None for entry in result['Responses']]

    @staticmethod
    def same_assignment(mission, drone, mission_id, drone_id): #check if the two records match
        return bool(mission and drone and mission.get('drone_id') == drone_id
            and drone.get('current_mission_id') == mission_id
            and drone.get('availability_status') == 'UNAVAILABLE')

    def get_mission(self, mission_id): #retrieves mission
        item = self.client.get_item(TableName=self.missions,
            Key=encode({'mission_id': mission_id}), ConsistentRead=True).get('Item')
        return decode(item) if item else None

    def existing_assignment(self, mission): #check if the mission already has an assignment
        drone_id = mission.get('drone_id')
        if drone_id is None:
            return None
        current, drone = self.pair(mission['mission_id'], drone_id)
        if self.same_assignment(current, drone, mission['mission_id'], drone_id):
            return {'message': 'Already assigned; no duplicate change.', 'mission': current,
                    'drone': drone, 'distance_m': current.get('assignment_distance_m')}
        raise AssignmentError(409, 'Existing mission/drone links are inconsistent; review before assigning.')

    def is_eligible(self, drone): #check if the drone is eligible for assignment
        if (drone.get('availability_status') != 'AVAILABLE'
                or drone.get('connection_status') != 'CONNECTED'
                or drone.get('current_mission_id') is not None):
            return False
        if coordinates(drone.get('location')) is None:
            return False
        return True

    def assign(self, mission_id): #assign a drone to a mission
        # Repeat selection if another request takes the chosen drone first.
        for attempt in range(3):
            mission = self.get_mission(mission_id)
            if mission is None:
                raise AssignmentError(404, 'Mission does not exist.')
            existing = self.existing_assignment(mission)
            if existing:
                return existing
            if mission.get('status') != 'PLANNED':
                raise AssignmentError(409, 'Only PLANNED missions can be assigned in this starter.')
            # Use request coordinates; fall back only when request_location is absent/null.
            location_field = 'request_location' if mission.get('request_location') is not None else 'start_location'
            target = coordinates(mission.get(location_field))
            if target is None:
                raise AssignmentError(422, 'Mission needs valid numeric latitude/longitude in request_location (or start_location).')
            candidates = []
            for drone in self.list_items(self.drones):
                if self.is_eligible(drone):
                    distance = distance_meters(target, coordinates(drone['location']))
                    candidates.append((distance, drone['drone_id'], drone))
            if not candidates:
                raise AssignmentError(409, 'No available, connected drone with valid coordinates.')
            distance, drone_id, drone = min(candidates, key=lambda item: (item[0], item[1]))
            distance = Decimal(str(round(distance, 3)))
            # Match the location used for selection at write time.
            # Both record changes succeed together, or neither is applied.
            writes = [
                {'Update': {'TableName': self.missions, 'Key': encode({'mission_id': mission_id}),
                    'UpdateExpression': 'SET #drone = :drone, assignment_distance_m = :distance',
                    'ConditionExpression': 'attribute_exists(#id) AND #status = :planned AND (attribute_not_exists(#drone) OR #drone = :empty) AND #loc = :location' +
                        (' AND (attribute_not_exists(request_location) OR request_location = :empty)' if location_field == 'start_location' else ''),
                    'ExpressionAttributeNames': {'#id': 'mission_id', '#status': 'status', '#drone': 'drone_id', '#loc': location_field},
                    'ExpressionAttributeValues': encode({':drone': drone_id, ':planned': 'PLANNED', ':empty': None,
                        ':location': mission[location_field], ':distance': distance})}},
                {'Update': {'TableName': self.drones, 'Key': encode({'drone_id': drone_id}),
                    'UpdateExpression': 'SET #availability = :busy, #mission = :mission',
                    'ConditionExpression': 'attribute_exists(#id) AND #availability = :available AND (attribute_not_exists(#mission) OR #mission = :empty) AND #connection = :connected AND #loc = :location',
                    'ExpressionAttributeNames': {'#id': 'drone_id', '#availability': 'availability_status', '#mission': 'current_mission_id',
                        '#connection': 'connection_status', '#loc': 'location'},
                    'ExpressionAttributeValues': encode({':busy': 'UNAVAILABLE', ':mission': mission_id,
                        ':available': 'AVAILABLE', ':empty': None, ':connected': 'CONNECTED',
                        ':location': drone['location']})}}
            ]
            try:
                self.client.transact_write_items(TransactItems=writes)
            except self.client.exceptions.TransactionCanceledException as error:
                reasons = error.response.get('CancellationReasons', [])
                codes = {reason.get('Code') for reason in reasons} - {'None', None}
                if codes and not codes <= {'ConditionalCheckFailed', 'TransactionConflict'}:
                    raise
                continue
            current, assigned = self.pair(mission_id, drone_id)
            return {'message': 'Nearest eligible drone assigned successfully.', 'mission': current,
                    'drone': assigned, 'distance_m': distance}
        # A concurrent request may have completed this same mission.
        mission = self.get_mission(mission_id)
        if mission:
            existing = self.existing_assignment(mission)
            if existing:
                return existing
        raise AssignmentError(409, 'Drone or mission state kept changing; refresh and retry. No partial assignment was applied.')


def coordinates(location): #checks location data
    """Return valid numeric (latitude, longitude), or None for unusable GPS."""
    if not isinstance(location, dict):
        return None
    values = (location.get('latitude'), location.get('longitude'))
    if any(isinstance(v, bool) or not isinstance(v, (int, float, Decimal)) for v in values):
        return None
    latitude, longitude = map(float, values)
    if not (math.isfinite(latitude) and math.isfinite(longitude)
            and -90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def distance_meters(origin, destination): #calculates surface distance between two points
    """Great-circle surface distance using the Haversine formula; not flight ETA."""
    lat1, lon1 = map(math.radians, origin)
    lat2, lon2 = map(math.radians, destination)
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, a))))
