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
            values[":requested"],
            values[":ready"],
            values[":confirmed"],
        }
        found = [
            item for item in self.items
            if item.get("drone_id") == values[":drone_id"]
            and item.get("launch_status") in allowed
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

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        if self.fail:
            raise RuntimeError("backend down")
        self.updates.append({
            "mission_id": Key["mission_id"],
            "status": ExpressionAttributeValues[":launch_status"],
            "reason": ExpressionAttributeValues[":reason"],
            "expression": UpdateExpression,
            "reasons": ExpressionAttributeValues.get(":reasons"),
        })


def test_backend_module_does_not_command_or_read_mavlink():
    source = inspect.getsource(backend_comms)
    assert "recv_match" not in source
    assert "set_mode" not in source
    assert "command_long_send" not in source


def test_scan_pages_and_ignores_other_rows():
    table = Table([], pages=[
        {"Items": [], "LastEvaluatedKey": {"mission_id": "m-0"}},
        {"Items": [{
            "mission_id": "m-7",
            "drone_id": "drone-7",
            "launch_status": "requested",
        }]},
    ])
    found = backend_comms.find_launch_request(table, "drone-7")
    assert found["mission_id"] == "m-7"

    live = Table([
        {"mission_id": "other", "drone_id": "drone-9", "launch_status": "requested"},
        {"mission_id": "done", "drone_id": "drone-7", "launch_status": "launched"},
        {"mission_id": "m-7", "drone_id": "drone-7", "launch_status": "ready"},
    ])
    assert backend_comms.find_launch_request(live, "drone-7")["mission_id"] == "m-7"
    assert backend_comms.find_launch_request(live, "missing") is None


def test_report_keeps_status_reason_and_optional_reasons():
    table = Table([{"mission_id": "m-7"}])
    assert backend_comms.report_launch(
        table, "m-7", "not_ready", "Flight controller is not ready", ["GPS fix is not 3D"]
    ) is None
    update = table.updates[0]
    assert update["status"] == "not_ready"
    assert update["reason"] == "Flight controller is not ready"
    assert update["reasons"] == ["GPS fix is not 3D"]
    assert "launch_reasons = :reasons" in update["expression"]

    assert backend_comms.report_launch(
        table, "m-7", "launched", "Climb confirmed"
    ) is None
    assert "REMOVE launch_reasons" in table.updates[1]["expression"]


def test_report_error_is_returned_and_attached_without_changing_state():
    table = Table([{"mission_id": "m-7"}])
    table.fail = True
    error = backend_comms.report_launch(table, "m-7", "launched", "Climb confirmed")
    assert error == "backend down"
    result = {"state": "LAUNCH_SUCCEEDED"}
    backend_comms.attach_report_error(result, error)
    assert result["state"] == "LAUNCH_SUCCEEDED"
    assert result["report_error"] == "backend down"
    backend_comms.attach_report_error(result, None)
    assert result["report_error"] == "backend down"


def test_confirmation_read_preserves_the_handshake_tokens():
    table = Table([{"mission_id": "m-7", "launch_status": "ready"}])
    assert backend_comms.read_launch_confirmation(table, "m-7") == "waiting"
    assert table.reads == [True]
    table.items[0]["launch_status"] = "confirmed"
    assert backend_comms.read_launch_confirmation(table, "m-7") == "confirmed"
    table.items[0]["launch_status"] = "requested"
    assert backend_comms.read_launch_confirmation(table, "m-7") == "cancelled"
    table.items.clear()
    assert backend_comms.read_launch_confirmation(table, "m-7") == "cancelled"
    table.fail = True
    assert backend_comms.read_launch_confirmation(table, "m-7") == "read_failed"


def test_launch_scan_arguments_are_fresh_each_call():
    first = backend_comms._launch_scan_kwargs("drone-1")
    second = backend_comms._launch_scan_kwargs("drone-1")
    assert first is not second
    assert first["ExpressionAttributeValues"] is not second["ExpressionAttributeValues"]
    first["ExclusiveStartKey"] = {"mission_id": "m-1"}
    first["ExpressionAttributeValues"][":drone_id"] = "other"
    assert "ExclusiveStartKey" not in second
    assert second["ExpressionAttributeValues"][":drone_id"] == "drone-1"
    assert first["FilterExpression"] == second["FilterExpression"]


def test_record_report_enqueue_keeps_an_existing_report_error():
    queued = {"state": "LAUNCH_SUCCEEDED"}
    assert backend_comms.record_report_enqueue(queued, 4) is True
    assert queued == {
        "state": "LAUNCH_SUCCEEDED",
        "report_seq": 4,
        "report_state": "queued",
    }

    full = {"state": "LAUNCH_FAILED", "report_error": "backend down"}
    assert backend_comms.record_report_enqueue(full, None) is False
    assert full == {
        "state": "LAUNCH_FAILED",
        "report_error": "backend down",
        "report_seq": None,
        "report_state": "failed",
    }

    missing = {"state": "LANDING"}
    assert backend_comms.record_report_enqueue(missing, None) is False
    assert missing["report_seq"] is None
    assert missing["report_state"] == "failed"
    assert missing["report_error"] == "report queue full"
    assert missing["state"] == "LANDING"
