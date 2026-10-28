# ASSIGNED TO: AWS / Database Team
# Connects to the AWS account in the default credential chain.
# Set DYNAMODB_ENDPOINT_URL to use DynamoDB Local instead.

import os

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


# Dynamo db endpoints/region/settings
DYNAMODB_ENDPOINT_URL = os.getenv("DYNAMODB_ENDPOINT_URL")
DYNAMODB_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"

# Define the tables and the schema for each table (Telemetry)
#key schema defines a primary key (what dynamo needs find the item), if it can be sorted via a key
TABLE_DEFINITIONS = {
    "Telemetry": {
        "KeySchema": [
            #drone_id gives it the information it needs for all the other attributes in the Drone table (Hash)
            {"AttributeName": "drone_id", "KeyType": "HASH"},
            #timestamp allows the data to be sorted by a (Range)
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            #AttributeType S --> string
            {"AttributeName": "drone_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
    },
    "Missions": {
        "KeySchema": [
            {"AttributeName": "mission_id", "KeyType": "HASH"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "mission_id", "AttributeType": "S"},
        ],
    },
    "Alerts": {
        "KeySchema": [
            {"AttributeName": "mission_id", "KeyType": "HASH"},
            {"AttributeName": "alert_timestamp", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "mission_id", "AttributeType": "S"},
            {"AttributeName": "alert_timestamp", "AttributeType": "S"},
        ],
    },
    "MediaMetadata": {
        "KeySchema": [
            {"AttributeName": "media_id", "KeyType": "HASH"},
            {"AttributeName": "captured_at", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "media_id", "AttributeType": "S"},
            {"AttributeName": "captured_at", "AttributeType": "S"},
        ],
    },
    "Users": {
        "KeySchema": [
            {"AttributeName": "badge_num", "KeyType": "HASH"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "badge_num", "AttributeType": "S"},
        ],
    },
    "Drones": {
        "KeySchema": [
            {"AttributeName": "drone_id", "KeyType": "HASH"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "drone_id", "AttributeType": "S"},
        ],
    },
}


def get_dynamodb_resource():
    """Return a DynamoDB resource for the AWS account in the default credential chain."""
    client_kwargs = {
        "region_name": DYNAMODB_REGION,
        "config": Config(retries={"max_attempts": 3, "mode": "standard"}),
    }
    if DYNAMODB_ENDPOINT_URL:
        client_kwargs["endpoint_url"] = DYNAMODB_ENDPOINT_URL
    return boto3.resource("dynamodb", **client_kwargs)

#make the tables if they dont exist
def create_tables():
    """Create any missing tables in the connected account and return all table names."""
    dynamodb = get_dynamodb_resource()
    existing_tables = set(dynamodb.meta.client.list_tables()["TableNames"])

    for table_name, definition in TABLE_DEFINITIONS.items():
        if table_name in existing_tables:
            continue

        table = dynamodb.create_table(
            TableName=table_name,
            BillingMode="PAY_PER_REQUEST",
            **definition,
        )
        table.wait_until_exists()

    return sorted(dynamodb.meta.client.list_tables()["TableNames"])


def check_connection():
    """Report whether the AWS account and all required tables are available."""
    endpoint = DYNAMODB_ENDPOINT_URL or f"dynamodb.{DYNAMODB_REGION}.amazonaws.com"
    try:
        identity = None
        if not DYNAMODB_ENDPOINT_URL:
            identity = boto3.client("sts", region_name=DYNAMODB_REGION).get_caller_identity()
        table_names = set(get_dynamodb_resource().meta.client.list_tables()["TableNames"])
    except (BotoCoreError, ClientError) as error:
        return {
            "connected": False,
            "region": DYNAMODB_REGION,
            "endpoint": endpoint,
            "error": str(error),
        }

    required_tables = set(TABLE_DEFINITIONS)
    missing_tables = sorted(required_tables - table_names)
    status = {
        "connected": True,
        "region": DYNAMODB_REGION,
        "endpoint": endpoint,
        "tables": sorted(table_names),
        "missing_tables": missing_tables,
    }
    if identity:
        status["account"] = identity["Account"]
        status["arn"] = identity["Arn"]
    return status


if __name__ == "__main__":
    status = check_connection()
    if not status["connected"]:
        print(f"Could not reach DynamoDB in {status['region']} at {status['endpoint']}")
        print(status["error"])
        raise SystemExit(1)

    account = status.get("account", "local")
    print(f"Connected to DynamoDB account {account} in {status['region']}")
    print(f"Tables: {', '.join(status['tables']) or '(none)'}")
    if status["missing_tables"]:
        print(f"Missing expected tables: {', '.join(status['missing_tables'])}")
