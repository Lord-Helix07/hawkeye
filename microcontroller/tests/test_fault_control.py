"""Fault landing is armed from the coordinator, including during launch."""

import landing_sequence
import main as flight_main
from flight_controller import fc_connection
from fakes import FakeLink, launch_stream
from maintest import Drones, Missions, mission, poll


def landed(trigger_reason):
    return {
        "state": "LANDED",
        "reason": "Touchdown and disarm confirmed.",
        "trigger_reason": trigger_reason,
        "request_attempted": True,
        "write_completed": True,
        "land_mode_confirmed": True,
        "touchdown_confirmed": True,
    }


def test_passed_health_fault_lands_once_and_does_not_launch(clock, monkeypatch):
    calls = []

    def fake_run(cache, progress=None, trigger_reason=None, **kwargs):
        calls.append(trigger_reason)
        return landed(trigger_reason)

    monkeypatch.setattr(landing_sequence, "run_landing", fake_run)
    link = FakeLink(clock, launch_stream({}))
    missions = Missions(mission("confirmed"))
    health = {"battery_status": "LOW"}
    flight, result = poll(
        clock,
        link,
        missions,
        health=health,
        execute_landing=True,
        simulation_confirmed=True,
    )
    assert result["state"] == "LANDED"
    assert calls == ["Flight battery status is LOW."]
    assert flight["landing_started"] is True
    assert flight["following"] is False
    assert link.modes == []
    _, again = poll(
        clock,
        link,
        missions,
        flight=flight,
        health=health,
        execute_landing=True,
        simulation_confirmed=True,
    )
    assert again is None
    assert calls == ["Flight battery status is LOW."]


def test_website_landing_cancels_launch_confirmation(clock, monkeypatch):
    calls = []

    def fake_run(cache, progress=None, trigger_reason=None, **kwargs):
        calls.append(trigger_reason)
        return landed(trigger_reason)

    monkeypatch.setattr(landing_sequence, "run_landing", fake_run)
    link = FakeLink(clock, launch_stream({}))
    missions = Missions(mission("requested"))
    flight, waiting = poll(clock, link, missions)
    assert waiting["state"] == "AWAITING_CONFIRMATION"
    assert flight["launch_phase"] == "awaiting_confirmation"
    drones = Drones({"drone_id": "drone-7", "landing_status": "LAND_REQUESTED"})
    flight, result = poll(
        clock,
        link,
        missions,
        drones=drones,
        flight=flight,
        execute_landing=True,
        simulation_confirmed=True,
    )
    assert result["state"] == "LANDED"
    assert calls == [None]
    assert flight["launch_phase"] is None
    assert flight["landing_started"] is True
    assert link.modes == []
    _, again = poll(
        clock,
        link,
        missions,
        drones=drones,
        flight=flight,
        execute_landing=True,
        simulation_confirmed=True,
    )
    assert again is None
    assert calls == [None]


def test_fault_during_launch_commands_stops_before_takeoff(clock, monkeypatch):
    calls = []

    def fake_run(cache, progress=None, trigger_reason=None, **kwargs):
        calls.append(trigger_reason)
        return landed(trigger_reason)

    monkeypatch.setattr(landing_sequence, "run_landing", fake_run)
    link = FakeLink(clock, launch_stream({}))
    cache = fc_connection.cache_for(link)
    flight = flight_main.new_flight_state(True)
    flight["cache"] = cache

    def tick(current):
        if not current.get("commands_started"):
            return
        import health_monitor
        health_monitor.watch(
            flight,
            current,
            health_provider=lambda: {"battery_status": "CRITICAL"},
        )

    cache["tick"] = tick
    _, result = poll(
        clock,
        link,
        Missions(mission("confirmed")),
        flight=flight,
        cache=cache,
        execute_landing=True,
        simulation_confirmed=True,
    )
    assert result["state"] == "LANDED", result
    assert calls == ["Flight battery status is CRITICAL."]
    assert link.modes == [4]
    assert link.commands == []
    assert flight["landing_started"] is True
    _, again = poll(
        clock,
        link,
        Missions(mission("confirmed")),
        flight=flight,
        cache=cache,
        execute_landing=True,
        simulation_confirmed=True,
    )
    assert again is None
    assert calls == ["Flight battery status is CRITICAL."]


def test_run_loop_lands_on_fault_and_closes_the_link(clock, monkeypatch):
    calls = []

    def fake_run(cache, progress=None, trigger_reason=None, **kwargs):
        calls.append(trigger_reason)
        return landed(trigger_reason)

    monkeypatch.setattr(landing_sequence, "run_landing", fake_run)
    link = FakeLink(clock, launch_stream({}))
    cache = fc_connection.cache_for(link)
    monkeypatch.setattr(fc_connection, "open_link", lambda *args, **kwargs: cache)
    flight = flight_main.run(
        "drone-7",
        execute_landing=True,
        simulation_confirmed=True,
        missions=Missions(mission("launched")),
        table=Drones(),
        health_provider=lambda: {"battery_status": "CRITICAL"},
        max_cycles=5,
    )
    assert flight["landing_started"] is True
    assert calls == ["Flight battery status is CRITICAL."]
    assert link.closed is True
    assert link.modes == []
