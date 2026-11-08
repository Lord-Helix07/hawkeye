"""Launch, landing, telemetry and Dashboard status routes, against a fake DynamoDB (moto)."""

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

moto = pytest.importorskip("moto")


@pytest.fixture
def dynamodb(monkeypatch):
    for name, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("DYNAMODB_ENDPOINT_URL", raising=False)

    with moto.mock_aws():
        import database.database as database

        monkeypatch.setattr(database, "DYNAMODB_ENDPOINT_URL", None)
        resource = database.get_dynamodb_resource()
        for name, definition in database.TABLE_DEFINITIONS.items():
            resource.create_table(TableName=name, BillingMode="PAY_PER_REQUEST", **definition)
        yield resource


@pytest.fixture
def client(dynamodb):
    from fastapi.testclient import TestClient

    from api import app

    return TestClient(app)


def add_mission(dynamodb, **extra):
    mission = {
        "mission_id": "0001",
        "created_at": "2026-11-08T20:00:00+00:00",
        "status": "pending",
        "target_vehicle": {"color": "silver", "make": "Honda", "model": "Civic", "license_plate": "JLS24K"},
        "request_location": {"latitude": Decimal("37.3352"), "longitude": Decimal("-121.8811")},
    }
    mission.update(extra)
    dynamodb.Table("Missions").put_item(Item=mission)


def add_drone(dynamodb, drone_id="drone-01", **extra):
    drone = {
        "drone_id": drone_id,
        "availability": "available",
        "battery_pct": 90,
        "latitude": Decimal("37.3360"),
        "longitude": Decimal("-121.8820"),
    }
    drone.update(extra)
    dynamodb.Table("Drones").put_item(Item=drone)


def mission_row(dynamodb):
    return dynamodb.Table("Missions").get_item(Key={"mission_id": "0001"})["Item"]


# ---------- launch ----------

def test_launch_assigns_nearest_drone_and_requests_launch(client, dynamodb):
    add_mission(dynamodb)
    add_drone(dynamodb, "drone-far", latitude=Decimal("37.40"), longitude=Decimal("-121.95"))
    add_drone(dynamodb, "drone-near")

    response = client.post("/missions/0001/launch")

    assert response.status_code == 200, response.text
    row = mission_row(dynamodb)
    assert row["drone_id"] == "drone-near"
    assert row["launch_status"] == "requested"
    assert "assigned_drone_id" not in row
    assert "launch_request_timestamp" in row


def test_launch_is_what_the_pi_looks_for(client, dynamodb):
    """The Pi scans for drone_id = X AND launch_status = requested."""
    add_mission(dynamodb)
    add_drone(dynamodb)
    client.post("/missions/0001/launch")

    items = dynamodb.Table("Missions").scan(
        FilterExpression="drone_id = :d AND launch_status = :r",
        ExpressionAttributeValues={":d": "drone-01", ":r": "requested"},
    )["Items"]
    assert [item["mission_id"] for item in items] == ["0001"]


def test_launch_without_free_drone_is_409(client, dynamodb):
    add_mission(dynamodb)
    add_drone(dynamodb, availability="assigned")

    response = client.post("/missions/0001/launch")

    assert response.status_code == 409
    assert "No available drone" in response.json()["detail"]


def test_launch_without_location_is_409(client, dynamodb):
    add_mission(dynamodb, request_location=None)
    add_drone(dynamodb)

    response = client.post("/missions/0001/launch")

    assert response.status_code == 409
    assert "latitude and longitude" in response.json()["detail"]


def test_launch_twice_is_409(client, dynamodb):
    add_mission(dynamodb)
    add_drone(dynamodb)
    assert client.post("/missions/0001/launch").status_code == 200

    response = client.post("/missions/0001/launch")

    assert response.status_code == 409
    assert "already" in response.json()["detail"]


def test_launch_retry_after_not_ready(client, dynamodb):
    add_mission(dynamodb, drone_id="drone-01", launch_status="not_ready", launch_reason="No GPS fix")

    response = client.post("/missions/0001/launch")

    assert response.status_code == 200
    row = mission_row(dynamodb)
    assert row["launch_status"] == "requested"
    assert "launch_reason" not in row


def test_launch_unknown_mission_is_404(client, dynamodb):
    assert client.post("/missions/9999/launch").status_code == 404


# ---------- confirm launch ----------

def test_confirm_launch_when_ready(client, dynamodb):
    add_mission(dynamodb, drone_id="drone-01", launch_status="ready")

    response = client.post("/missions/0001/confirm-launch")

    assert response.status_code == 200
    assert mission_row(dynamodb)["launch_status"] == "confirmed"


def test_confirm_launch_before_ready_is_409(client, dynamodb):
    add_mission(dynamodb, drone_id="drone-01", launch_status="requested")

    response = client.post("/missions/0001/confirm-launch")

    assert response.status_code == 409
    assert "requested" in response.json()["detail"]
    assert mission_row(dynamodb)["launch_status"] == "requested"


def test_confirm_launch_unknown_mission_is_404(client, dynamodb):
    assert client.post("/missions/9999/confirm-launch").status_code == 404


# ---------- request landing ----------

def test_request_landing_after_launch(client, dynamodb):
    add_mission(dynamodb, drone_id="drone-01", launch_status="launched")

    response = client.post("/missions/0001/request-landing")

    assert response.status_code == 200
    row = mission_row(dynamodb)
    assert row["landing_status"] == "requested"
    assert "landing_request_timestamp" in row


def test_request_landing_before_takeoff_is_409(client, dynamodb):
    add_mission(dynamodb, drone_id="drone-01", launch_status="ready")

    response = client.post("/missions/0001/request-landing")

    assert response.status_code == 409
    assert "hasn't taken off" in response.json()["detail"]


def test_request_landing_twice_is_409(client, dynamodb):
    add_mission(dynamodb, drone_id="drone-01", launch_status="launched")
    client.post("/missions/0001/request-landing")

    response = client.post("/missions/0001/request-landing")

    assert response.status_code == 409
    assert "already" in response.json()["detail"]


# ---------- telemetry ----------

HEARTBEAT_PAYLOAD = {  # microcontroller/heartbeat.py build_backend_payload()
    "drone_id": "drone-01",
    "mission_id": None,
    "frame": {"frame_id": None, "frame_timestamp_ns": None, "bounding_box": None},
    "flight_controller": {"connected": True, "flight_mode": "GUIDED", "armed": True},
    "telemetry": {
        "timestamp": "2026-11-08T20:05:00Z",
        "position": {"latitude_deg": 37.3361, "longitude_deg": -121.8821, "altitude_m": 70.1, "relative_altitude_m": 9.1},
        "motion": {"speed_mps": 6.5, "heading_deg": 275.0},
        "gps": {"fix_type": 3, "satellites_visible": 12, "timestamp": {}},
        "battery": {"percentage": 81, "voltage_v": 24.1, "current_a": 5.2, "timestamp": {}},
        "attitude": {"roll_deg": 1.5, "pitch_deg": -2.0, "yaw_deg": 275.0, "timestamp": {}},
        "imu": {},
    },
    "readiness": {"ready": True},
    "published_timestamp": "2026-11-08T20:05:00Z",
}

FC_STATUS_PAYLOAD = {  # microcontroller/backend_micro_comms.md
    "drone_id": "drone-01",
    "mission_id": None,
    "flight_controller": {"connected": True, "flight_mode": "STABILIZE", "armed": False},
    "telemetry": {
        "latitude": 37.3352, "longitude": -121.8811, "altitude_m": 42.0, "speed_mps": 8.5,
        "heading_deg": 275, "gps_fix_type": 3, "satellites_visible": 12, "battery_pct": 91,
        "battery_voltage": 24.1, "battery_current": 5.2, "timestamp": "2026-11-08T20:06:00Z",
    },
    "readiness": {"ready_for_launch": False, "reasons": []},
}


def test_post_telemetry_saves_flat_row_and_updates_drone(client, dynamodb):
    add_drone(dynamodb)

    response = client.post("/telemetry", json=HEARTBEAT_PAYLOAD)

    assert response.status_code == 201, response.text
    row = dynamodb.Table("Telemetry").get_item(
        Key={"drone_id": "drone-01", "timestamp": "2026-11-08T20:05:00Z"}
    )["Item"]
    assert row["latitude"] == Decimal("37.3361")
    assert row["altitude_m"] == Decimal("9.1")  # height above takeoff, not sea level
    assert row["battery_pct"] == 81
    assert row["pitch_deg"] == Decimal("-2.0")
    assert "mission_id" not in row  # None values are left out
    drone = dynamodb.Table("Drones").get_item(Key={"drone_id": "drone-01"})["Item"]
    assert drone["latitude"] == Decimal("37.3361")
    assert drone["battery_pct"] == 81
    assert drone["availability"] == "available"  # untouched


def test_post_flight_controller_status_flat_shape(client, dynamodb):
    response = client.post("/flight-controller/status", json=FC_STATUS_PAYLOAD)

    assert response.status_code == 201, response.text
    row = dynamodb.Table("Telemetry").get_item(
        Key={"drone_id": "drone-01", "timestamp": "2026-11-08T20:06:00Z"}
    )["Item"]
    assert row["battery_pct"] == 91
    assert row["flight_controller"]["flight_mode"] == "STABILIZE"
    # an unregistered drone doesn't get a Drones row made for it
    assert "Item" not in dynamodb.Table("Drones").get_item(Key={"drone_id": "drone-01"})


def test_telemetry_without_drone_id_is_422(client, dynamodb):
    assert client.post("/telemetry", json={"telemetry": {}}).status_code == 422


# ---------- dashboard status ----------

def test_status_combines_mission_telemetry_and_log(client, dynamodb):
    add_mission(dynamodb, drone_id="drone-01", launch_status="ready", launch_reason="Flight controller is ready",
                launch_request_timestamp="2026-11-08T20:01:00Z")
    client.post("/flight-controller/status", json=FC_STATUS_PAYLOAD)
    client.post("/telemetry", json=HEARTBEAT_PAYLOAD)  # older timestamp than the FC one

    response = client.get("/missions/0001/status")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["launch_status"] == "ready"
    assert body["drone_id"] == "drone-01"
    assert body["telemetry"]["timestamp"] == "2026-11-08T20:06:00Z"  # newest row
    assert body["telemetry"]["battery_pct"] == 91
    assert body["telemetry"]["stale"] is True  # these test timestamps are old
    assert body["flight_controller"]["flight_mode"] == "STABILIZE"
    assert [entry["message"] for entry in body["flight_log"]] == [
        "Mission created: silver Honda Civic, JLS24K",
        "Launch requested for drone-01",
    ]
    assert body["images"] == []


def test_status_without_drone_has_no_telemetry(client, dynamodb):
    add_mission(dynamodb)

    body = client.get("/missions/0001/status").json()

    assert body["telemetry"] is None
    assert body["launch_status"] is None


def test_status_unknown_mission_is_404(client, dynamodb):
    assert client.get("/missions/9999/status").status_code == 404


def test_fresh_telemetry_is_not_stale():
    from mission_status import is_stale

    now = datetime(2026, 11, 8, 20, 0, 5, tzinfo=timezone.utc)
    assert not is_stale("2026-11-08T20:00:00Z", now)
    assert is_stale("2026-11-08T19:59:00Z", now)
    assert is_stale(None, now)
