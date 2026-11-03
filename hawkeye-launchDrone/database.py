"""Small DynamoDB helper used by local tests."""

import os

import boto3


def get_missions_table():
    # Use DynamoDB Local if an endpoint is provided. Otherwise use AWS DynamoDB.
    options = {"region_name": os.getenv("AWS_REGION", "us-east-1")}
    endpoint = os.getenv("DYNAMODB_ENDPOINT")
    if endpoint:
        options["endpoint_url"] = endpoint
    return boto3.resource("dynamodb", **options).Table(os.getenv("MISSIONS_TABLE", "Missions"))
