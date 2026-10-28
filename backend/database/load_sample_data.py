# Load backend/database/sample_data.json into the connected DynamoDB.
# For DynamoDB Local:
#   DYNAMODB_ENDPOINT_URL=http://127.0.0.1:8001 python backend/database/load_sample_data.py

import json
from decimal import Decimal
from pathlib import Path

from database import DYNAMODB_ENDPOINT_URL, create_tables, get_dynamodb_resource


SAMPLE_DATA_PATH = Path(__file__).with_name("sample_data.json")


def dynamodb_value(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [dynamodb_value(item) for item in value]
    if isinstance(value, dict):
        return {key: dynamodb_value(item) for key, item in value.items()}
    return value


def load_sample_data():
    """Create missing tables and write every sample item."""
    tables = json.loads(SAMPLE_DATA_PATH.read_text())
    table_names = create_tables()
    print(f"Tables: {', '.join(table_names)}")
    dynamodb = get_dynamodb_resource()

    for table_name, items in tables.items():
        table = dynamodb.Table(table_name)
        for item in items:
            table.put_item(Item=dynamodb_value(item))
        print(f"{table_name}: {len(items)}")


if __name__ == "__main__":
    endpoint = DYNAMODB_ENDPOINT_URL or "the AWS account in the default credential chain"
    print(f"Loading sample data into {endpoint}")
    load_sample_data()
