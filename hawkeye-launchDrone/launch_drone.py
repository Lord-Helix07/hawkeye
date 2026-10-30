"""Simple local tester for the launch Lambda."""

import json

from lambda_function import lambda_handler


mission_id = input("Mission ID: ").strip()
result = lambda_handler({"mission_id": mission_id}, None)
body = json.loads(result["body"])

if result["statusCode"] == 200:
    print("Updated Missions row:")
    print(json.dumps(body["mission"], indent=2, default=str))
    print(body["message"])
else:
    print(f"Error: {body.get('error', body)}")
