# Saves signup records in the DynamoDB Users table.
# Set DYNAMODB_ENDPOINT_URL to use DynamoDB Local instead of AWS.

from datetime import datetime, timezone
import os
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


class BadgeNumTaken(Exception):
    """A user with this badge number already exists."""


class UsersTableSchemaError(Exception):
    """The Users table is not keyed by badge_num."""


def users_table_name() -> str:
    return os.getenv("USERS_TABLE", "Users")


def get_dynamodb_resource():
    """Return a DynamoDB resource using the default credential chain."""
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    kwargs = {
        "region_name": region,
        "config": Config(
            retries={"total_max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=10,
        ),
    }
    endpoint_url = os.getenv("DYNAMODB_ENDPOINT_URL")
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.resource("dynamodb", **kwargs)


def _table_names(client) -> set[str]:
    names: set[str] = set()
    paginator = client.get_paginator("list_tables")
    for page in paginator.paginate():
        names.update(page.get("TableNames", []))
    return names


def ensure_users_table(dynamodb=None):
    """Create the Users table when it is missing, then return it.

    The partition key matches the shared schema: badge_num (string).
    """
    dynamodb = dynamodb or get_dynamodb_resource()
    client = dynamodb.meta.client
    table_name = users_table_name()

    if table_name not in _table_names(client):
        try:
            table = dynamodb.create_table(
                TableName=table_name,
                BillingMode="PAY_PER_REQUEST",
                KeySchema=[{"AttributeName": "badge_num", "KeyType": "HASH"}],
                AttributeDefinitions=[
                    {"AttributeName": "badge_num", "AttributeType": "S"},
                ],
            )
        except client.exceptions.ResourceInUseException:
            table = dynamodb.Table(table_name)
        table.wait_until_exists()
        return table

    description = client.describe_table(TableName=table_name)["Table"]
    hash_key = next(
        key["AttributeName"]
        for key in description["KeySchema"]
        if key["KeyType"] == "HASH"
    )
    if hash_key != "badge_num":
        raise UsersTableSchemaError(
            f"{table_name} partition key is {hash_key}, expected badge_num"
        )
    return dynamodb.Table(table_name)


def create_user(badge_num: str, password_hash: str, dynamodb=None) -> None:
    """Insert a user keyed by badge number. Fails if the badge number is already registered.
    """
    dynamodb = dynamodb or get_dynamodb_resource()
    ensure_users_table(dynamodb)
    client = dynamodb.meta.client
    table_name = users_table_name()
    created_at = _utc_now()

    try:
        client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": table_name,
                        "Item": {
                            "badge_num": badge_num,

                            "password_hash": password_hash,
                            "status": "active",
                            "created_at": created_at,
                        },
                        "ConditionExpression": "attribute_not_exists(badge_num)",
                    }
                },
                
            ]
        )
    except client.exceptions.TransactionCanceledException as error:
        reasons = error.response.get("CancellationReasons", [])
        if any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons):
            raise BadgeNumTaken from error
        raise


# def _profile_exists(client, table_name: str, username: str, email: str) -> bool:
#     """Find users loaded before uniqueness records existed."""
#     paginator = client.get_paginator("scan")
#     for page in paginator.paginate(
#         TableName=table_name,
#         FilterExpression="username = :username OR email = :email",
#         ExpressionAttributeValues={":username": username, ":email": email},
#         ProjectionExpression="badge_num",
#     ):
#         if page.get("Items"):
#             return True
#     return False


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    try:
        table = ensure_users_table()
    except (BotoCoreError, ClientError, UsersTableSchemaError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Users table ready: {table.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
