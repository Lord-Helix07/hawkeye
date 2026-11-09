"""Missions handshake reads and writes. No flight controller and no network."""

import inspect

import backend_comms


class Table:
    def __init__(self, items, pages=None):
        self.items = [dict(item) for item in items]
        self.pages = list(pages) if pages is not None else None
        self.updates = []
        self.reads = []
        self.fail = False

    def scan(self, **kwargs):
        if self.pages is not None:
            return self.pages.pop(0)
        values = kwargs["ExpressionAttributeValues"]
        allowed = {
            values[":launch_requested"],
            values[":land_requested"],
            values[":ready"],
            values[":confirmed"],
        }
        found = [
            item for item in self.items
            if item.get("drone_id") == values[":drone_id"]
            and item.get("status") in allowed
        ]
        return {"Items": found}

    def get_item(self, Key, ConsistentRead=False):
        self.reads.append(ConsistentRead)
        if self.fail:
            raise RuntimeError("read failed")
        for item in self.items:
            if item.get("mission_id") == Key["mission_id"]:
                return {"Item": item}
        return {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None):
        if self.fail:
            raise RuntimeError("backend down")
        self.updates.append({
            "mission_id": Key["mission_id"],
            "status": ExpressionAttributeValues[":status"],
            "expression": UpdateExpression,
        })


def test_backend_module_does_not_command_or_read_mavlink():
    source = inspect.getsource(backend_comms)
    assert "recv_match" not in source
    assert "set_mode" not in source
    assert "command_long_send" not in source


def _status(table, drone_id):
    backend_comms.poll_results()
    assert backend_comms.enqueue_status_check(drone_id, backend_comms.new_request_id())
    backend_comms.ensure_worker(table, None)
    assert backend_comms.wait_idle(2)
    found = backend_comms.poll_results()
    assert found[-1]["state"] == "completed"
    return found[-1]["item"]


def test_scan_pages_and_ignores_other_rows():
    table = Table([], pages=[
        {"Items": [], "LastEvaluatedKey": {"mission_id": "m-0"}},
        {"Items": [{
            "mission_id": "m-7",
            "drone_id": "drone-7",
            "launch_status": "requested",
        }]},
    ])
    assert _status(table, "drone-7")["mission_id"] == "m-7"

    live = Table([
        {"mission_id": "other", "drone_id": "drone-9", "status": "launch_requested"},
        {"mission_id": "done", "drone_id": "drone-7", "status": "active"},
        {"mission_id": "m-7", "drone_id": "drone-7", "status": "land_requested"},
    ])
    assert _status(live, "drone-7")["mission_id"] == "m-7"
    assert _status(live, "missing") is None
    backend_comms.stop_worker()


def test_report_writes_only_launch_status():
    table = Table([{"mission_id": "m-7"}])
    assert backend_comms.report_status(table, "m-7", "not_ready") is None
    update = table.updates[0]
    assert update["status"] == "not_ready"
    assert update["expression"] == "SET #status = :status"

    assert backend_comms.report_status(table, "m-7", "launched") is None
    assert table.updates[1]["expression"] == "SET #status = :status"


def test_report_error_is_returned_and_attached_without_changing_state():
    table = Table([{"mission_id": "m-7"}])
    table.fail = True
    error = backend_comms.report_status(table, "m-7", "launched")
    assert error == "backend down"
    result = {"state": "LAUNCH_SUCCEEDED"}
    backend_comms.attach_report_error(result, error)
    assert result["state"] == "LAUNCH_SUCCEEDED"
    assert result["report_error"] == "backend down"
    backend_comms.attach_report_error(result, None)
    assert result["report_error"] == "backend down"


def test_confirmation_comes_from_the_launch_row():
    assert backend_comms.confirmation_from_status(
        {"mission_id": "m-7", "status": "ready"}
    ) == "waiting"
    assert backend_comms.confirmation_from_status(
        {"mission_id": "m-7", "status": "confirmed"}
    ) == "confirmed"
    assert backend_comms.confirmation_from_status(
        {"mission_id": "m-7", "status": "launch_requested"}
    ) == "cancelled"
    assert backend_comms.confirmation_from_status(
        {"mission_id": "m-7", "status": "active"}
    ) == "cancelled"
    assert backend_comms.confirmation_from_status(None) == "cancelled"


def test_dashboard_snapshot_is_the_telemetry_row():
    sample = backend_comms.dashboard_snapshot(
        "drone-01",
        "msn-1001",
        {
            "latitude": 37.33571,
            "longitude": -121.8832,
            "altitude_m": 47.5,
            "speed_mps": 14.4,
            "heading_deg": 268,
            "battery_pct": 89,
            "stale": False,
        },
        timestamp="2026-10-27T21:15:20Z",
    )
    assert sample == {
        "drone_id": "drone-01",
        "timestamp": "2026-10-27T21:15:20Z",
        "mission_id": "msn-1001",
        "latitude": 37.33571,
        "longitude": -121.8832,
        "altitude_m": 47.5,
        "speed_mps": 14.4,
        "heading_deg": 268,
        "battery_pct": 89,
        "stale": False,
    }


class _DashboardTable:
    def __init__(self):
        self.items = []
        self.updates = []
        self.fail = False

    def put_item(self, Item):
        if self.fail:
            raise RuntimeError("backend down")
        self.items.append(Item)

    def update_item(self, **kwargs):
        if self.fail:
            raise RuntimeError("backend down")
        self.updates.append(kwargs)


def test_report_dashboard_writes_telemetry_and_the_live_drone():
    from decimal import Decimal

    telemetry = _DashboardTable()
    drones = _DashboardTable()
    sample = backend_comms.dashboard_snapshot(
        "drone-01",
        "msn-1001",
        {
            "latitude": 37.33571,
            "longitude": -121.8832,
            "battery_pct": 89,
            "stale": False,
        },
        timestamp="2026-10-27T21:15:20Z",
    )
    assert backend_comms.report_dashboard(telemetry, drones, sample) is None
    item = telemetry.items[0]
    assert item["latitude"] == Decimal("37.33571")
    assert item["longitude"] == Decimal("-121.8832")
    assert item["battery_pct"] == 89
    assert item["stale"] is False
    update = drones.updates[0]
    assert update["Key"] == {"drone_id": "drone-01"}
    assert update["ExpressionAttributeValues"][":latitude"] == Decimal("37.33571")
    assert ":battery_pct" in update["ExpressionAttributeValues"]
    assert "availability" not in update["ExpressionAttributeNames"]

    telemetry.fail = True
    assert backend_comms.report_dashboard(telemetry, drones, sample) == "backend down"
    assert backend_comms.report_dashboard(None, drones, sample) == "telemetry table is not open"


def test_enqueue_dashboard_sends_the_latest_sample():
    telemetry = _DashboardTable()
    drones = _DashboardTable()
    backend_comms._worker.telemetry = telemetry
    assert backend_comms.enqueue_dashboard(
        "drone-01", "msn-1001", {"battery_pct": 90, "stale": False}, 1
    ) == 1
    assert backend_comms.enqueue_dashboard(
        "drone-01",
        "msn-1001",
        {"battery_pct": 89, "latitude": 37.33, "longitude": -121.88, "stale": False},
        2,
    ) == 2
    assert len(backend_comms._worker.jobs) == 1
    backend_comms.ensure_worker(None, drones, telemetry)
    assert backend_comms.wait_idle(2)
    found = backend_comms.poll_results()
    assert found[-1]["kind"] == "dashboard_report"
    assert found[-1]["state"] == "completed"
    assert telemetry.items[-1]["battery_pct"] == 89
    assert drones.updates[-1]["Key"] == {"drone_id": "drone-01"}
    backend_comms.stop_worker()
    assert backend_comms.enqueue_dashboard(
        "drone-01", "msn-1001", {"battery_pct": 80, "stale": True}, 3
    ) is None


def test_record_report_enqueue_marks_the_result_queued():
    queued = {"state": "LAUNCH_SUCCEEDED"}
    backend_comms.record_report_enqueue(queued, 4)
    assert queued == {
        "state": "LAUNCH_SUCCEEDED",
        "report_seq": 4,
        "report_state": "queued",
    }
