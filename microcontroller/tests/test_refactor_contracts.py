"""Mocked checks for the handshake split, the backend worker, and heartbeat boundaries."""

import threading

import backend_comms
import landing_sequence
import launch_sequence
import main as flight_main
from flight_controller import fc_connection
from flight_controller import fc_status
from flight_controller import heartbeat as heartbeat_tracker
from fakes import (
    ARM,
    GUIDED,
    LAND,
    TAKEOFF,
    FakeLink,
    commands_named,
    extended,
    heartbeat,
    launch_stream,
)
from fakes import ON_GROUND
from maintest import poll


class RecordingTable:
    def __init__(self, pages=None):
        self.pages = list(pages or [])
        self.calls = []
        self.order = []
        self.updates = []
        self.block = None

    def scan(self, **kwargs):
        self.order.append("scan")
        self.calls.append(kwargs.get("ExclusiveStartKey"))
        if self.block is not None:
            self.block.wait(2)
        if self.pages:
            return self.pages.pop(0)
        return {"Items": []}

    def get_item(self, Key, ConsistentRead=False):
        if "drone_id" in Key:
            self.order.append("landing")
            return {
                "Item": {
                    "drone_id": Key["drone_id"],
                    "landing_status": "LAND_REQUESTED",
                }
            }
        self.order.append("confirm")
        return {"Item": {"mission_id": Key["mission_id"], "launch_status": "ready"}}

    def update_item(self, **kwargs):
        self.order.append("report")
        if self.block is not None:
            self.block.wait(2)
        self.updates.append(kwargs)
        return {}


def _session():
    session = backend_comms.begin_session()
    _, token = backend_comms.current_tokens()
    return session, token


def test_equal_timestamp_needs_a_later_heartbeat_receipt(clock):
    link = FakeLink(clock, lambda link: None)
    cache = fc_connection.cache_for(link)
    tracker = cache["heartbeat"]
    heartbeat_tracker.observe(tracker, heartbeat(LAND, False), 50.0)
    cache["command_heartbeat_receipt"] = tracker["receipt"]
    cache["operation_at"] = 50.0
    assert fc_status.commanded_mode(cache, "LAND", 50.0) is False
    heartbeat_tracker.observe(tracker, heartbeat(LAND, False), 50.0)
    assert tracker["seen_at"] == cache["operation_at"]
    assert tracker["receipt"] > cache["command_heartbeat_receipt"]
    assert fc_status.commanded_mode(cache, "LAND", 50.0) is True


def test_landing_still_runs_while_abort_launch_is_true(clock, monkeypatch):
    def stream(link):
        if not link.modes:
            return heartbeat(GUIDED, True)
        if link.reads % 2:
            return heartbeat(LAND, False)
        return extended(ON_GROUND)

    direct = FakeLink(clock, stream)
    direct_cache = fc_connection.cache_for(direct)
    direct_cache["abort_launch"] = True
    landed = landing_sequence.run_landing(direct_cache, trigger_reason="fault")
    assert landed["state"] == "LANDED", landed
    assert direct.modes == [LAND]

    calls = []

    def fake_run(cache, progress=None, trigger_reason=None, **kwargs):
        calls.append(cache.get("abort_launch"))
        return {
            "state": "LANDED",
            "reason": "Touchdown and disarm confirmed.",
            "trigger_reason": trigger_reason,
            "request_attempted": True,
            "write_completed": True,
            "land_mode_confirmed": True,
            "touchdown_confirmed": True,
        }

    monkeypatch.setattr(landing_sequence, "run_landing", fake_run)
    link = FakeLink(clock, lambda link: heartbeat(GUIDED, False))
    flight = flight_main.new_flight_state(True)
    cache = fc_connection.cache_for(link)
    cache["abort_launch"] = True
    flight["cache"] = cache
    flight["abort_launch"] = True
    result = flight_main.request_landing(
        flight,
        link,
        execute_landing=True,
        simulation_confirmed=True,
    )
    assert result["state"] == "LANDED"
    assert calls == [True]


def test_empty_read_still_runs_health(clock):
    seen = []

    def provider():
        seen.append("health")
        return {}

    link = FakeLink(clock, lambda link: None)
    from maintest import Missions, mission

    _, result = poll(
        clock,
        link,
        Missions(mission()),
        health_provider=provider,
    )
    assert result["state"] == "NOT_READY"
    assert result["reason"] == "Flight controller heartbeat missing"
    assert seen


def test_enqueue_does_not_write_until_the_worker_runs():
    table = RecordingTable()
    session, _token = _session()
    seq = backend_comms.enqueue_launch_report(
        "m-1", session, "ready", "Flight controller is ready", None, 1
    )
    assert seq
    assert table.updates == []
    backend_comms.ensure_worker(table, table)
    assert backend_comms.wait_idle(2)
    assert table.updates
    applied = backend_comms.poll_results()
    assert applied[0]["state"] == "completed"
    assert applied[0]["seq"] == seq


def test_scan_continues_onto_the_next_page():
    table = RecordingTable(pages=[
        {"Items": [], "LastEvaluatedKey": {"mission_id": "page-2"}},
        {"Items": [{
            "mission_id": "m-9",
            "drone_id": "drone-9",
            "launch_status": "requested",
        }]},
    ])
    session, token = _session()
    assert backend_comms.enqueue_launch_scan("drone-9", session, token, 7)
    backend_comms.ensure_worker(table, table)
    assert backend_comms.wait_idle(2)
    assert table.calls == [None, {"mission_id": "page-2"}]
    found = backend_comms.poll_results()
    assert found[-1]["state"] == "completed"
    assert found[-1]["item"]["mission_id"] == "m-9"


def test_landing_check_survives_a_launch_phase_change_and_is_scheduled_first():
    table = RecordingTable(pages=[{
        "Items": [{
            "mission_id": "m-1",
            "drone_id": "drone-1",
            "launch_status": "requested",
        }],
    }])
    session, token = _session()
    assert backend_comms.enqueue_landing_check("drone-1", session, 1)
    assert backend_comms.enqueue_launch_confirm("m-1", session, token, 2)
    assert backend_comms.enqueue_launch_report(
        "m-1", session, "ready", "Flight controller is ready", None, 3
    )
    assert backend_comms.enqueue_launch_scan("drone-1", session, token, 4)
    backend_comms.set_launch_context("m-1", "awaiting_confirmation")
    backend_comms.ensure_worker(table, table)
    assert backend_comms.wait_idle(2)
    assert table.order[0] == "landing"
    results = {item["kind"]: item for item in backend_comms.poll_results()}
    assert results["landing_check"]["state"] == "completed"
    assert results["landing_check"]["requested"] is True
    assert results["launch_scan"]["state"] == "failed"
    assert results["launch_confirm"]["state"] == "failed"


def test_report_slot_saturation_returns_none_and_same_key_supersedes():
    session, _token = _session()
    first = backend_comms.enqueue_launch_report(
        "m-1", session, "ready", "one", None, 1
    )
    blocked = backend_comms.enqueue_launch_report(
        "m-2", session, "ready", "two", None, 2
    )
    replacement = backend_comms.enqueue_launch_report(
        "m-1", session, "not_ready", "three", ["three"], 3
    )
    assert first
    assert blocked is None
    assert replacement
    failed = backend_comms.poll_results()
    assert failed[0]["state"] == "failed"
    assert failed[0]["reason"] == "superseded"
    assert failed[0]["seq"] == first


def test_shutdown_reports_unsent_and_uncertain(monkeypatch):
    monkeypatch.setattr(backend_comms, "_CONNECT_TIMEOUT", 0.05)
    monkeypatch.setattr(backend_comms, "_READ_TIMEOUT", 0.05)
    gate = threading.Event()
    table = RecordingTable()
    table.block = gate
    session, _token = _session()
    backend_comms.ensure_worker(table, table)
    assert backend_comms.enqueue_launch_report(
        "m-1", session, "ready", "Flight controller is ready", None, 1
    )
    assert backend_comms.enqueue_landing_report("drone-1", session, "LANDING", 2)
    for _ in range(50):
        if "report" in table.order:
            break
        gate.wait(0.01)
    leftovers = backend_comms.stop_worker()
    gate.set()
    threading.Event().wait(0.2)
    states = {(item.get("kind"), item.get("state"), item.get("reason")) for item in leftovers}
    assert ("launch_report", "uncertain", "shutdown during send") in states
    assert ("landing_report", "failed", "unsent") in states


def test_launch_cancel_before_guided_sends_nothing(clock):
    link = FakeLink(clock, launch_stream({}))
    cache = fc_connection.cache_for(link)
    result = launch_sequence.run_launch(cache, "drone-1", stop=lambda: True)
    assert result is None
    assert link.modes == []
    assert link.commands == []


def test_launch_cancel_after_guided_and_before_arm(clock):
    link = FakeLink(clock, launch_stream({}))
    cache = fc_connection.cache_for(link)

    def stop():
        return bool(link.modes) and not commands_named(link, ARM)

    result = launch_sequence.run_launch(cache, "drone-1", stop=stop)
    assert result["state"] == "LAUNCH_FAILED", result
    assert result["reason"] == "Launch cancelled before the next command"
    assert commands_named(link, ARM) == []
    assert commands_named(link, TAKEOFF) == []


def test_launch_cancel_after_arm_and_during_climb(clock):
    link = FakeLink(clock, launch_stream({}))
    cache = fc_connection.cache_for(link)

    def stop_before_takeoff():
        return bool(commands_named(link, ARM))

    armed = launch_sequence.run_launch(cache, "drone-1", stop=stop_before_takeoff)
    assert armed["state"] == "LAUNCH_INTERRUPTED", armed
    assert commands_named(link, TAKEOFF) == []

    climbing = FakeLink(clock, launch_stream({"climb": True}))
    climb_cache = fc_connection.cache_for(climbing)

    def stop_during_climb():
        return bool(commands_named(climbing, TAKEOFF))

    interrupted = launch_sequence.run_launch(
        climb_cache, "drone-1", stop=stop_during_climb
    )
    assert interrupted["state"] == "LAUNCH_INTERRUPTED", interrupted
    assert interrupted["reason"] == "Launch cancelled before the next command"
    assert commands_named(climbing, TAKEOFF)


def test_unavailable_backend_does_not_raise_into_the_flight_thread(clock):
    class Down:
        def scan(self, **kwargs):
            raise RuntimeError("backend down")

        def get_item(self, Key, ConsistentRead=False):
            raise RuntimeError("backend down")

    from maintest import Missions, mission

    link = FakeLink(clock, launch_stream({}))
    flight, result = poll(clock, link, Missions(mission("launched")), drones=Down())
    assert result is None
    assert flight.get("backend_error")
    assert link.modes == []
