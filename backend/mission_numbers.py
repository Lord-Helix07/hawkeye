"""Hands out mission numbers 0001, 0002, 0003, ... from one shared counter.

The counter is one item in the Counters table:
    {"counter_name": "missions", "value": <last number handed out>}

take_next_mission_number() uses DynamoDB's ADD, which is atomic: even if two
officers press Deploy at the same moment, they can never get the same number.
"""

from botocore.exceptions import ClientError

from database.database import create_tables, get_dynamodb_resource

COUNTERS_TABLE = "Counters"
MISSION_COUNTER = "missions"


def format_mission_number(number: int) -> str:
    """1 -> "0001" (this is also the mission_id saved in the Missions table)."""
    return f"{number:04d}"


def _run_on_counters_table(action, dynamodb=None):
    """Run action(table), creating the Counters table first if it doesn't exist yet."""
    dynamodb = dynamodb or get_dynamodb_resource()
    try:
        return action(dynamodb.Table(COUNTERS_TABLE))
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
        create_tables()  # first run on this database: add the missing table, then retry
        return action(dynamodb.Table(COUNTERS_TABLE))


def peek_next_mission_number(dynamodb=None) -> int:
    """The number the next mission will get, without using it up.

    Only a preview: if someone else deploys first, the real number will be higher.
    """

    def read(table):
        item = table.get_item(Key={"counter_name": MISSION_COUNTER}).get("Item")
        return int(item["value"]) + 1 if item else 1

    return _run_on_counters_table(read, dynamodb)


def take_next_mission_number(dynamodb=None) -> int:
    """Use up the next number and return it. Safe to call from many places at once."""

    def increment(table):
        result = table.update_item(
            Key={"counter_name": MISSION_COUNTER},
            UpdateExpression="ADD #value :one",
            ExpressionAttributeNames={"#value": "value"},  # "value" is a reserved word
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        return int(result["Attributes"]["value"])

    return _run_on_counters_table(increment, dynamodb)
