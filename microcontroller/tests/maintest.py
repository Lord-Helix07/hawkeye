"""Application coordination. Backend and the flight controller are fakes."""

import landing_sequence
import main as flight_main
from flight_controller import fc_connection
from fakes import (
    ACCEPTED,
    GUIDED,
    TAKEOFF,
    FakeLink,
    commands_named,
    heartbeat,
    launch_stream,
)


class Drones:
    def __init__(self, item=None):
        self.item = item

    def get_item(self, Key):
        if self.item and self.item.get("drone_id") == Key["drone_id"]:
            return {"Item": self.item}
        return {}


class Missions:
    def __init__(self, item):
        self.item = dict(item)
        self.updates = []
        self.fail_status = None

    def scan(self, **kwargs):
        values = kwargs["ExpressionAttributeValues"]
        allowed = {values[":requested"], values[":ready"], values[":confirmed"]}
        item = self.item
        if item.get("drone_id") == values[":drone_id"] and item.get("launch_status") in allowed:
            return {"Items": [item]}
        return {"Items": []}

    def get_item(self, Key, ConsistentRead=False):
        if self.item.get("mission_id") != Key["mission_id"]:
            return {}
        return {"Item": self.item}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        status = ExpressionAttributeValues[":launch_status"]
        if status == self.fail_status:
            raise RuntimeError("backend down")
        self.updates.append(status)
        self.item["launch_status"] = status
        self.item["launch_reason"] = ExpressionAttributeValues[":reason"]


def mission(status="requested"):
    return {
        "mission_id": "m-7",
        "drone_id": "drone-7",
        "launch_status": status,
    }


def poll(clock, link, missions, drones=None, **kwargs):
    import backend_comms

    flight = kwargs.pop("flight", None)
    if flight is None:
        flight = flight_main.new_flight_state(True)
    drones = drones if drones is not None else Drones()
    execute_landing = kwargs.pop("execute_landing", False)
    simulation_confirmed = kwargs.pop("simulation_confirmed", False)
    allow_hardware_landing = kwargs.pop("allow_hardware_landing", False)
    def once():
        return flight_main.poll_flight(
            flight,
            link,
            drones,
            "drone-7",
            missions=missions,
            execute_landing=execute_landing,
            simulation_confirmed=simulation_confirmed,
            allow_hardware_landing=allow_hardware_landing,
            **kwargs,
        )

    result = None
    for _ in range(16):
        step = once()
        if step is not None:
            result = step
        phase = flight.get("launch_phase")
        if phase == "reporting_ready" or flight.get("scan_inflight") or (
            flight.get("landing_inflight") and not flight.get("landing_answered")
        ):
            if backend_comms.worker_busy():
                backend_comms.wait_idle(2)
            continue
        if (
            phase == "awaiting_confirmation"
            and result is not None
            and result.get("state") == "AWAITING_CONFIRMATION"
        ):
            break
        if backend_comms.worker_busy():
            backend_comms.wait_idle(2)
            continue
        break
    if backend_comms.worker_busy():
        backend_comms.wait_idle(2)
    step = once()
    if step is not None:
        result = step
    if flight.get("landing_inflight") or backend_comms.worker_busy():
        if backend_comms.worker_busy():
            backend_comms.wait_idle(2)
        step = once()
        if step is not None:
            result = step
    if backend_comms.worker_busy():
        backend_comms.wait_idle(2)
    return flight, result


def test_no_request_sends_no_launch_command(clock):
    link = FakeLink(clock, launch_stream({}))
    missions = Missions(mission("launched"))
    flight, result = poll(clock, link, missions)
    assert result is None
    assert link.modes == []
    assert link.commands == []
    assert flight["launch_started"] is False
    assert flight["following"] is False


def test_failed_readiness_blocks_launch(clock):
    link = FakeLink(clock, lambda link: heartbeat(GUIDED, False))
    missions = Missions(mission())
    flight, result = poll(clock, link, missions)
    assert result["state"] == "NOT_READY", result
    assert "GPS telemetry missing or stale" in result["reasons"]
    assert missions.updates == ["not_ready"]
    assert link.modes == []
    assert flight["launch_started"] is False


def test_ready_report_does_not_command_before_confirmation(clock):
    link = FakeLink(clock, launch_stream({}))
    missions = Missions(mission("requested"))
    flight, result = poll(clock, link, missions)
    assert result["state"] == "AWAITING_CONFIRMATION", result
    assert missions.updates == ["ready"]
    assert missions.item["launch_status"] == "ready"
    assert link.modes == []
    assert link.commands == []
    clock.advance(1)
    _, again = poll(clock, link, missions, flight=flight)
    assert again["state"] == "AWAITING_CONFIRMATION"
    assert link.commands == []


def test_readiness_is_rechecked_after_confirmation(clock, monkeypatch):
    import launch_sequence

    link = FakeLink(clock, launch_stream({}))
    missions = Missions(mission("requested"))
    flight, result = poll(clock, link, missions)
    assert result["state"] == "AWAITING_CONFIRMATION"
    monkeypatch.setattr(launch_sequence, "READINESS_TIMEOUT", 0.3)
    clock.advance(6)
    link.default = lambda link: heartbeat(GUIDED, False)
    missions.item["launch_status"] = "confirmed"
    _, checked = poll(clock, link, missions, flight=flight)
    assert checked["state"] == "NOT_READY", checked
    assert any("GPS" in reason for reason in checked["reasons"])
    assert link.modes == []
    assert "not_ready" in missions.updates


def test_confirmed_ready_launch_hands_off_and_a_report_failure_keeps_the_outcome(clock):
    link = FakeLink(clock, launch_stream({
        "climb": True,
        "takeoff_results": [ACCEPTED],
    }))
    missions = Missions(mission("confirmed"))
    missions.fail_status = "launched"
    flight, result = poll(clock, link, missions)
    assert result["state"] == "LAUNCH_SUCCEEDED", result
    assert result["report_error"] == "backend down"
    assert result["reason"] == "Climb confirmed"
    assert flight["following"] is True
    assert flight["launch_started"] is True
    assert link.modes == [GUIDED]
    assert commands_named(link, TAKEOFF)
    _, second = poll(clock, link, missions, flight=flight)
    assert second is None
    assert link.modes == [GUIDED]


def test_missing_heartbeat_is_not_ready_and_does_not_command(clock):
    link = FakeLink(clock, lambda link: None)
    missions = Missions(mission())
    _, result = poll(clock, link, missions)
    assert result["state"] == "NOT_READY", result
    assert result["reason"] == "Flight controller heartbeat missing"
    assert link.modes == []
    assert missions.updates == ["not_ready"]


def test_confirmation_timeout_does_not_take_off_or_rewrite_ready(clock, monkeypatch):
    import backend_comms

    monkeypatch.setattr(backend_comms, "CONFIRM_TIMEOUT", 0.3)
    link = FakeLink(clock, launch_stream({}))
    missions = Missions(mission())
    flight, result = poll(clock, link, missions)
    assert result["state"] == "AWAITING_CONFIRMATION"
    clock.advance(1)
    _, timed_out = poll(clock, link, missions, flight=flight)
    assert timed_out["state"] == "AWAITING_CONFIRMATION"
    assert timed_out["reason"] == "Operator has not confirmed"
    assert missions.updates == ["ready"]
    assert link.commands == []
    assert flight["launch_phase"] is None


def test_lost_heartbeat_during_confirmation_reports_not_ready(clock):
    link = FakeLink(clock, launch_stream({}))
    missions = Missions(mission())
    flight, result = poll(clock, link, missions)
    assert result["state"] == "AWAITING_CONFIRMATION"
    link.default = lambda link: None
    lost = None
    for _ in range(40):
        _, lost = poll(clock, link, missions, flight=flight)
        if lost["state"] != "AWAITING_CONFIRMATION":
            break
    assert lost["reason"] == "Communication lost while waiting for operator confirmation"
    assert "not_ready" in missions.updates
    assert link.commands == []


def test_inactive_flight_does_not_launch(clock):
    link = FakeLink(clock, launch_stream({}))
    flight = flight_main.new_flight_state(False)
    _, result = poll(clock, link, Missions(mission("confirmed")), flight=flight)
    assert result is None
    assert link.commands == []


def test_landing_request_still_reaches_run_landing(clock, monkeypatch):
    calls = []

    def fake_run(cache, progress=None, trigger_reason=None, **kwargs):
        calls.append((cache, trigger_reason))
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
    link = FakeLink(clock, launch_stream({}))
    drones = Drones({"drone_id": "drone-7", "landing_status": "LAND_REQUESTED"})
    flight, result = poll(
        clock,
        link,
        Missions(mission("confirmed")),
        drones=drones,
        execute_landing=True,
        simulation_confirmed=True,
    )
    assert result["state"] == "LANDED"
    assert calls[0][1] is None
    assert "link" in calls[0][0]
    assert flight["landing_started"] is True
    assert flight["following"] is False
    assert link.modes == []


def test_shared_cache_is_reused_for_later_polls(clock):
    link = FakeLink(clock, launch_stream({}))
    cache = fc_connection.cache_for(link)
    missions = Missions(mission("requested"))
    flight, result = poll(clock, link, missions, cache=cache)
    assert result["state"] == "AWAITING_CONFIRMATION"
    assert flight["cache"] is cache
    assert cache["heartbeat"]["seen_at"] is not None
