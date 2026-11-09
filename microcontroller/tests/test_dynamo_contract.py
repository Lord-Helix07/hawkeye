"""Mocked checks against the Missions and Drones rows read from the account.

These fixtures use the key names, field names, and status values that were
present. They do not open a connection.
"""

import inspect
import sys
import types

import backend_comms
from backend_commstest import Table


OBSERVED_MISSIONS = [
    {
        "mission_id": "msn-b6e42207",
        "status": "pending",
        "created_at": "2026-11-03T06:12:05.890773+00:00",
        "request_location": {"latitude": 25, "longitude": 25},
        "target_vehicle": {
            "color": "BLUE",
            "identifying_features": "none",
            "license_plate": "!98382",
            "make": "Toyota Prius",
            "model": "Prius V 2017",
            "type": "Hatchback",
        },
    },
    {
        "mission_id": "msn-1001",
        "drone_id": "drone-01",
        "status": "active",
        "area": "San Jose",
        "officer_unit": "Unit 12",
        "target_vehicle_id": "veh-14",
        "target_label": "gray sedan",
        "started_at": "2026-10-27T21:15:00Z",
    },
    {
        "mission_id": "msn-1002",
        "drone_id": "drone-02",
        "status": "completed",
        "area": "San Jose",
        "officer_unit": "Unit 7",
        "target_vehicle_id": "veh-03",
        "target_label": "white pickup",
        "started_at": "2026-10-27T18:02:00Z",
        "ended_at": "2026-10-27T18:27:00Z",
    },
    {
        "mission_id": "msn-1003",
        "drone_id": "drone-03",
        "status": "visual_contact_lost",
        "area": "Santa Clara",
        "officer_unit": "Unit 4",
        "target_vehicle_id": "veh-21",
        "target_label": "black SUV",
        "started_at": "2026-10-27T20:40:00Z",
    },
]

OBSERVED_DRONES = [
    {"drone_id": "drone-01", "availability": "assigned", "battery_pct": 89, "latitude": 37.33571, "longitude": -121.8832},
    {"drone_id": "drone-02", "availability": "available", "battery_pct": 64, "latitude": 37.3189, "longitude": -121.8946},
    {"drone_id": "drone-03", "availability": "assigned", "battery_pct": 79, "latitude": 37.3598, "longitude": -121.9487},
    {"drone_id": "drone-05", "availability": "offline", "battery_pct": 44, "latitude": 37.3401, "longitude": -121.8904},
]


class DroneTable:
    def __init__(self, items):
        self.items = [dict(item) for item in items]
        self.keys = []

    def get_item(self, Key):
        self.keys.append(dict(Key))
        for item in self.items:
            if item.get("drone_id") == Key["drone_id"]:
                return {"Item": item}
        return {}


def test_observed_mission_rows_are_not_launch_requests():
    table = Table(OBSERVED_MISSIONS)
    for drone_id in ("drone-01", "drone-02", "drone-03", "drone-06"):
        assert backend_comms.find_launch_request(table, drone_id) is None
    assert backend_comms.find_launch_request(Table([]), "drone-01") is None


def test_mission_lifecycle_status_is_not_operator_confirmation():
    for status in ("pending", "active", "visual_contact_lost", "completed"):
        table = Table([{
            "mission_id": "msn-1001",
            "drone_id": "drone-01",
            "status": status,
        }])
        assert backend_comms.read_launch_confirmation(table, "msn-1001") == "cancelled"
        assert table.reads == [True]


def test_launch_lookup_keys_stay_on_mission_id():
    kwargs = backend_comms._launch_scan_kwargs("drone-01")
    assert kwargs["ExpressionAttributeValues"][":drone_id"] == "drone-01"
    handshake = {
        kwargs["ExpressionAttributeValues"][":requested"],
        kwargs["ExpressionAttributeValues"][":ready"],
        kwargs["ExpressionAttributeValues"][":confirmed"],
    }
    assert handshake == {"requested", "ready", "confirmed"}
    assert handshake.isdisjoint({"pending", "active", "visual_contact_lost", "completed"})
    assert "ExclusiveStartKey" not in kwargs


def test_observed_drone_rows_are_not_landing_requests():
    table = DroneTable(OBSERVED_DRONES)
    for item in OBSERVED_DRONES:
        assert backend_comms.find_landing_request(table, item["drone_id"]) is None
    assert backend_comms.find_landing_request(table, "drone-06") is None
    assert table.keys[0] == {"drone_id": "drone-01"}
    assert all("landing_status" not in item for item in OBSERVED_DRONES)


def test_resource_uses_the_default_chain_and_configured_region(monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("DYNAMODB_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    saved = {}

    def resource(name, **kwargs):
        saved["name"] = name
        saved["kwargs"] = kwargs

        class Tables:
            def Table(self, table_name):
                saved["table"] = table_name
                return table_name

        return Tables()

    boto3 = types.ModuleType("boto3")
    boto3.resource = resource
    botocore = types.ModuleType("botocore")
    config_mod = types.ModuleType("botocore.config")

    class Config:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    config_mod.Config = Config
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "botocore", botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", config_mod)

    assert backend_comms.missions_table() == "Missions"
    assert backend_comms.drones_table() == "Drones"
    assert saved["name"] == "dynamodb"
    assert saved["kwargs"]["region_name"] == "us-east-1"
    assert saved["kwargs"]["config"].kwargs["connect_timeout"] == 2
    assert saved["kwargs"]["config"].kwargs["read_timeout"] == 3
    assert "profile_name" not in saved["kwargs"]
    assert "aws_access_key_id" not in saved["kwargs"]
    assert "aws_secret_access_key" not in saved["kwargs"]
    assert "endpoint_url" not in saved["kwargs"]

    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("DYNAMODB_ENDPOINT_URL", "http://127.0.0.1:8001")
    assert backend_comms._region_name() == "us-east-1"
    backend_comms.missions_table()
    assert saved["kwargs"]["region_name"] == "us-east-1"
    assert saved["kwargs"]["endpoint_url"] == "http://127.0.0.1:8001"


def test_region_defaults_to_the_account_region(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    assert backend_comms._region_name() == "us-east-1"
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    assert backend_comms._region_name() == "us-east-1"


def test_backend_source_does_not_embed_a_profile_or_keys():
    source = inspect.getsource(backend_comms._dynamo_resource)
    assert "profile_name" not in source
    assert "aws_access_key_id" not in source
    assert "aws_secret_access_key" not in source
    assert "hawkeye" not in source
