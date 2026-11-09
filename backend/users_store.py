# Saves signup records in the DynamoDB Users table.
# Set DYNAMODB_ENDPOINT_URL to use DynamoDB Local instead of AWS.

from datetime import datetime, timezone
import os
import sys
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
class BadgeNumTaken(Exception):
    """A user with this badge number already exists."""


class LoginLocked(Exception):
    """A user account is temporarily locked after too many failed logins."""

    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = max(0, retry_after_seconds)
        super().__init__("Login temporarily locked")


class UsersTableSchemaError(Exception):
    """The Users table is not keyed by badge_num."""


def users_table_name() -> str:
    return os.getenv("USERS_TABLE", "Users")


def _dynamodb_kwargs() -> dict:
    """Build shared connection settings for DynamoDB resource and client."""
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
    return kwargs


def get_dynamodb_resource(): # connect to DynamoDB
    """Return a DynamoDB resource using the default credential chain."""
    return boto3.resource("dynamodb", **_dynamodb_kwargs())


def _table_names(client) -> set[str]: # get all table names in the DynamoDB
    names: set[str] = set()
    paginator = client.get_paginator("list_tables")
    for page in paginator.paginate():
        names.update(page.get("TableNames", []))
    return names


def _ensure_keyed_table(dynamodb, table_name: str, key_name: str): # ensure the table exists and is keyed correctly
    client = dynamodb.meta.client

    if table_name not in _table_names(client):
        try:
            table = dynamodb.create_table(
                TableName=table_name,
                BillingMode="PAY_PER_REQUEST",
                KeySchema=[{"AttributeName": key_name, "KeyType": "HASH"}],
                AttributeDefinitions=[
                    {"AttributeName": key_name, "AttributeType": "S"},
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
    if hash_key != key_name:
        raise UsersTableSchemaError(
            f"{table_name} partition key is {hash_key}, expected {key_name}"
        )
    return dynamodb.Table(table_name)


def ensure_users_table(dynamodb=None):
    """Create or validate the Users table keyed by badge_num."""
    dynamodb = dynamodb or get_dynamodb_resource()
    return _ensure_keyed_table(dynamodb, users_table_name(), "badge_num")


def create_user(
    badge_num: str,
    password_hash: str,
    dynamodb=None,
) -> None:
    """Insert a user keyed by badge number. Fails if that badge is already registered."""
    badge_num = badge_num.strip()
    dynamodb = dynamodb or get_dynamodb_resource()
    table = ensure_users_table(dynamodb)

    try:
        table.put_item(
            Item={
                "badge_num": badge_num,
                "password_hash": password_hash,
                "status": "active",
                "created_at": _utc_now(),
            },
            ConditionExpression="attribute_not_exists(badge_num)",
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as error:
        raise BadgeNumTaken from error



def _utc_now() -> str: # get the current UTC time as a string
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_user(badge_num: str, dynamodb=None): 
    """Return one user by badge number, or None when no user exists."""
    dynamodb = dynamodb or get_dynamodb_resource()
    table = ensure_users_table(dynamodb)
    return table.get_item(
        Key={"badge_num": badge_num.strip()},
        ConsistentRead=True,
    ).get("Item")


def clear_expired_login_lock(badge_num: str, dynamodb=None) -> None: # Clear a lock that has already expired and reset failed attempts
    """Clear a lock that has already expired and reset failed attempts."""
    dynamodb = dynamodb or get_dynamodb_resource()
    table = ensure_users_table(dynamodb)
    now = int(time.time())
    try:
        table.update_item(
            Key={"badge_num": badge_num.strip()},
            UpdateExpression="SET failed_attempts = :zero REMOVE locked_until",
            ConditionExpression=(
                "attribute_exists(badge_num) AND attribute_exists(locked_until) "
                "AND locked_until <= :now"
            ),
            ExpressionAttributeValues={":zero": 0, ":now": now},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        pass


def record_failed_login( # Record a failed login attempt and lock the account if necessary
    badge_num: str,
    dynamodb=None,
    max_attempts: int = 10,
    lock_seconds: int = 15 * 60,
) -> dict:
    """Atomically count a failed login and lock the account at the limit."""
    dynamodb = dynamodb or get_dynamodb_resource()
    table = ensure_users_table(dynamodb)
    now = int(time.time())

    try:
        response = table.update_item(
            Key={"badge_num": badge_num.strip()},
            UpdateExpression=(
                "SET failed_attempts = if_not_exists(failed_attempts, :zero) + :one"
            ),
            ConditionExpression=(
                "attribute_exists(badge_num) AND "
                "(attribute_not_exists(locked_until) OR locked_until <= :now)"
            ),
            ExpressionAttributeValues={":zero": 0, ":one": 1, ":now": now},
            ReturnValues="UPDATED_NEW",
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as error:
        user = get_user(badge_num, dynamodb)
        locked_until = int((user or {}).get("locked_until", 0))
        if locked_until > now:
            raise LoginLocked(locked_until - now) from error
        raise

    failed_attempts = int(response["Attributes"]["failed_attempts"])
    attempts_remaining = max(0, max_attempts - failed_attempts)
    if failed_attempts < max_attempts:
        return {
            "locked": False,
            "failed_attempts": failed_attempts,
            "attempts_remaining": attempts_remaining,
        }

    locked_until = now + lock_seconds
    table.update_item(
        Key={"badge_num": badge_num.strip()},
        UpdateExpression="SET locked_until = :locked_until",
        ConditionExpression=(
            "attribute_exists(badge_num) AND failed_attempts >= :max_attempts"
        ),
        ExpressionAttributeValues={
            ":locked_until": locked_until,
            ":max_attempts": max_attempts,
        },
    )
    return {
        "locked": True,
        "failed_attempts": failed_attempts,
        "attempts_remaining": 0,
        "locked_until": locked_until,
        "retry_after_seconds": lock_seconds,
    }


def reset_login_attempts(badge_num: str, dynamodb=None) -> None:
    """Clear failed-login state after a successful login."""
    dynamodb = dynamodb or get_dynamodb_resource()
    table = ensure_users_table(dynamodb)
    table.update_item(
        Key={"badge_num": badge_num.strip()},
        UpdateExpression="SET failed_attempts = :zero REMOVE locked_until",
        ConditionExpression="attribute_exists(badge_num)",
        ExpressionAttributeValues={":zero": 0},
    )


def get_user_by_email(email: str, dynamodb=None):
    """Return the user registered with this email, or None."""
    dynamodb = dynamodb or get_dynamodb_resource()
    index = ensure_email_index_table(dynamodb)
    entry = index.get_item(
        Key={"email": email.strip().lower()},
        ConsistentRead=True,
    ).get("Item")
    if entry is None:
        return None
    return get_user(entry["badge_num"], dynamodb)


def save_password_reset_token( # store a hashed reset token on the user record
    badge_num: str,
    token_hash: str,
    expires_at: int,
    dynamodb=None,
) -> None:
    """Store a hashed, expiring password-reset token (replaces any older one)."""
    dynamodb = dynamodb or get_dynamodb_resource()
    table = ensure_users_table(dynamodb)
    table.update_item(
        Key={"badge_num": badge_num.strip()},
        UpdateExpression=(
            "SET reset_token_hash = :hash, reset_expires_at = :expires, "
            "reset_requested_at = :now"
        ),
        ConditionExpression="attribute_exists(badge_num)",
        ExpressionAttributeValues={
            ":hash": token_hash,
            ":expires": expires_at,
            ":now": int(time.time()),
        },
    )


def reset_password_with_token( # swap in the new password if the token still matches
    badge_num: str,
    token_hash: str,
    new_password_hash: str,
    dynamodb=None,
) -> bool:
    """Set a new password when the token matches and hasn't expired.

    Single use: the token is removed in the same write, and the login lock is
    cleared. Returns False when the token is wrong, used, or expired.
    """
    dynamodb = dynamodb or get_dynamodb_resource()
    table = ensure_users_table(dynamodb)
    try:
        table.update_item(
            Key={"badge_num": badge_num.strip()},
            UpdateExpression=(
                "SET password_hash = :password, failed_attempts = :zero "
                "REMOVE reset_token_hash, reset_expires_at, reset_requested_at, locked_until"
            ),
            ConditionExpression=(
                "attribute_exists(badge_num) AND reset_token_hash = :hash "
                "AND reset_expires_at > :now"
            ),
            ExpressionAttributeValues={
                ":password": new_password_hash,
                ":zero": 0,
                ":hash": token_hash,
                ":now": int(time.time()),
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False
    return True


def main() -> int: # main function to ensure tables exist and print status
    try:
        table = ensure_users_table()
    except (BotoCoreError, ClientError, UsersTableSchemaError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Users table ready: {table.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
