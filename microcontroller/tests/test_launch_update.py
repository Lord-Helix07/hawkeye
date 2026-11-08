"""Regression tests for launch ACK draining and recovery writes.

Expectations from the earlier defects stay in place. This loads the
launch_sequence.py in the working tree.
"""

import importlib.util
from pathlib import Path

import pytest

from fakes import (
    ACCEPTED,
    ARM,
    BATTERY_CONFIG,
    DENIED,
    FAILED,
    GUIDED,
    IN_AIR,
    IN_PROGRESS,
    LAND,
    TAKEOFF,
    FakeLink,
    Msg,
    ack,
    commands_named,
    extended,
    launch_stream,
)

LAUNCH_PATH = (
    Path(__file__).resolve().parents[1] / "launch_sequence.py"
)


def load_launch():
    spec = importlib.util.spec_from_file_location(
        "launch_sequence_under_test", LAUNCH_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def launch(clock, monkeypatch):
    module = load_launch()
    monkeypatch.setattr(module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(
        module.time,
        "sleep",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("real sleep is blocked")
        ),
    )

    class ScriptedOperator:
        def __init__(self):
            pass

        def get_response(self):
            return "CONFIRM"

    monkeypatch.setattr(module, "OperatorInput", ScriptedOperator)
    return module


def run_launch(launch, monkeypatch, clock, link, **kwargs):
    monkeypatch.setattr(
        launch, "connect", lambda address, baud: link
    )
    options = {
        "connection_address": "mock://fc",
        "baud_rate": 115200,
        "config": BATTERY_CONFIG,
        "execute_flight": True,
        "simulation_confirmed": True,
        "allow_hardware_flight": False,
        "auto_recovery_land": False,
    }
    options.update(kwargs)
    return launch.run_launch(**options)


def test_launch_module_under_test_is_the_working_tree():
    module = load_launch()
    assert Path(module.__file__).resolve() == LAUNCH_PATH.resolve()
    assert hasattr(module, "prepare_command")
    assert hasattr(module, "verify_pre_takeoff")


def test_takeoff_is_not_sent_after_mode_leaves_guided(
    launch, clock, monkeypatch
):
    link = FakeLink(clock, launch_stream({
        "mode_after_arm": 0,
        "alt_mm": 300,
        "takeoff_results": [DENIED],
    }))
    result = run_launch(launch, monkeypatch, clock, link)

    assert commands_named(link, ARM), "arm was never reached"
    assert commands_named(link, TAKEOFF) == [], (
        "NAV_TAKEOFF was sent after the mode left GUIDED"
    )
    assert result["state"] != "LAUNCH_SUCCEEDED"


def test_buffered_ack_is_not_the_new_takeoff_result(launch, clock):
    link = FakeLink(clock, queued=[ack(TAKEOFF, DENIED)])
    cache = launch.TelemetryCache(link)

    result = launch.takeoff(link, cache)

    assert commands_named(link, TAKEOFF)
    assert result == "UNKNOWN", result


def test_failure_after_in_progress_is_rejection(launch, clock):
    link = FakeLink(
        clock,
        queued=[
            ack(TAKEOFF, IN_PROGRESS),
            ack(TAKEOFF, FAILED),
        ],
    )
    cache = launch.TelemetryCache(link)

    result = launch.wait_for_ack(cache, TAKEOFF, cache.sequence)

    assert result == "REJECTED", result


def test_rejected_takeoff_is_not_success_at_target_relative_altitude(
    launch, clock, monkeypatch
):
    link = FakeLink(clock, launch_stream({
        "alt_mm": 9200,
        "climb": False,
        "takeoff_results": [IN_PROGRESS, FAILED],
    }))
    result = run_launch(launch, monkeypatch, clock, link)

    assert result["state"] != "LAUNCH_SUCCEEDED", result
    assert result.get("takeoff_ack") != "IN_PROGRESS"


def test_recovery_read_error_returns_a_status(
    launch, clock, monkeypatch
):
    link = FakeLink(clock)
    link._raise_on_read = True
    link.heartbeat_result = __import__(
        "fakes", fromlist=["heartbeat"]
    ).heartbeat(GUIDED, False)
    monkeypatch.setattr(
        launch.mavutil,
        "mavlink_connection",
        lambda *args, **kwargs: link,
    )

    result = launch.run_launch(
        "mock://fc",
        115200,
        BATTERY_CONFIG,
        execute_flight=False,
    )

    assert isinstance(result, dict)
    assert link.close_count == 1


def test_in_progress_without_a_final_ack_can_still_reach_altitude(
    launch, clock, monkeypatch
):
    link = FakeLink(clock, launch_stream({
        "climb": True,
        "alt_mm": 300,
        "takeoff_results": [IN_PROGRESS],
    }))
    result = run_launch(launch, monkeypatch, clock, link)

    assert result["state"] == "LAUNCH_SUCCEEDED", result
    assert result["takeoff_ack"] == "IN_PROGRESS"
    assert commands_named(link, TAKEOFF)


def test_default_flags_send_no_flight_commands(
    launch, clock, monkeypatch
):
    link = FakeLink(clock, launch_stream({}))
    result = run_launch(
        launch,
        monkeypatch,
        clock,
        link,
        execute_flight=False,
        simulation_confirmed=False,
        allow_hardware_flight=False,
    )

    assert result["state"] == "FLIGHT_DISABLED"
    assert link.commands == []
    assert link.modes == []


def test_both_environment_flags_block_commands(
    launch, clock, monkeypatch
):
    link = FakeLink(clock, launch_stream({}))
    result = run_launch(
        launch,
        monkeypatch,
        clock,
        link,
        simulation_confirmed=True,
        allow_hardware_flight=True,
    )

    assert result["state"] == "AUTHORIZATION_REQUIRED"
    assert commands_named(link, ARM) == []
    assert commands_named(link, TAKEOFF) == []


def test_mode_change_during_climb_does_not_command_land(
    launch, clock, monkeypatch
):
    link = FakeLink(clock, launch_stream({
        "alt_mm": 2000,
        "climb": False,
        "takeoff_results": [ACCEPTED],
        "mode_after_takeoff": 0,
    }))
    result = run_launch(
        launch,
        monkeypatch,
        clock,
        link,
        auto_recovery_land=True,
    )

    assert result["state"] != "LAUNCH_SUCCEEDED"
    assert LAND not in link.modes


def test_low_relative_altitude_does_not_disarm(
    launch, clock, monkeypatch
):
    link = FakeLink(clock, launch_stream({
        "alt_mm": 100,
        "climb": False,
        "disarm_after_takeoff": True,
        "takeoff_results": [DENIED],
    }))
    result = run_launch(
        launch,
        monkeypatch,
        clock,
        link,
        auto_recovery_land=True,
    )

    disarms = [
        args for args in commands_named(link, ARM) if args[4] == 0
    ]
    assert disarms == []
    assert result["state"] != "LAUNCH_SUCCEEDED"


def test_bad_data_does_not_let_a_buffered_ack_decide_takeoff(
    launch, clock
):
    link = FakeLink(
        clock,
        queued=[
            Msg("BAD_DATA"),
            ack(TAKEOFF, DENIED),
        ],
    )
    cache = launch.TelemetryCache(link)

    result = launch.takeoff(link, cache)

    assert commands_named(link, TAKEOFF)
    assert result == "UNKNOWN", result


def test_failed_recovery_write_is_not_labelled_complete_or_incomplete(
    launch, clock, monkeypatch
):
    base = launch_stream({
        "alt_mm": 2000,
        "climb": False,
        "takeoff_results": [DENIED],
    })

    def default(link):
        message = base(link)
        if message is None:
            return None
        if link.commands and message.get_type() == "GLOBAL_POSITION_INT":
            return extended(IN_AIR)
        return message

    link = FakeLink(clock, default)
    original = link.set_mode

    def set_mode(mode_id):
        if mode_id == LAND:
            link.modes.append(mode_id)
            raise RuntimeError("set_mode failed before completion")
        original(mode_id)

    link.set_mode = set_mode
    result = run_launch(
        launch,
        monkeypatch,
        clock,
        link,
        auto_recovery_land=True,
    )

    assert LAND in link.modes
    recovery = result["recovery"]
    completed = recovery.get("write_completed", None)
    assert completed is not True and completed is not False, result
    assert recovery.get("land_confirmed") is False
