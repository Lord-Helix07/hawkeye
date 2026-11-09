"""Launch regressions that used to target the old launch entry point.

The working tree no longer has OperatorInput, prepare_command, or a
recovery LAND. These tests keep the behaviors that still belong to
takeoff: no takeoff after leaving GUIDED, rejection is not success,
an in-progress acknowledgement can still climb, a buffered acknowledgement
does not decide the new takeoff, and launch does not disarm or command LAND.
"""

from fakes import (
    ACCEPTED,
    ARM,
    DENIED,
    FAILED,
    GUIDED,
    IN_PROGRESS,
    LAND,
    TAKEOFF,
    FakeLink,
    Msg,
    ack,
    commands_named,
    launch_stream,
)
from launch_sequencetest import run


def test_launch_module_under_test_is_the_working_tree():
    import launch_sequence
    from pathlib import Path

    assert Path(launch_sequence.__file__).name == "launch_sequence.py"
    assert hasattr(launch_sequence, "run_launch")
    assert hasattr(launch_sequence, "confirm_climb")


def test_takeoff_is_not_sent_after_mode_leaves_guided(clock):
    link = FakeLink(clock, launch_stream({"mode_after_arm": 0}))
    result = run(link, arm_timeout=0.6)
    assert commands_named(link, ARM)
    assert commands_named(link, TAKEOFF) == []
    assert result["state"] != "LAUNCH_SUCCEEDED"


def test_buffered_ack_is_not_the_new_takeoff_result(clock):
    link = FakeLink(
        clock,
        launch_stream({"climb": True, "takeoff_results": [ACCEPTED]}),
        queued=[ack(TAKEOFF, DENIED)],
    )
    result = run(link)
    assert commands_named(link, TAKEOFF)
    assert result["state"] == "LAUNCH_SUCCEEDED", result


def test_failure_after_in_progress_is_rejection(clock):
    link = FakeLink(clock, launch_stream({
        "climb": False,
        "alt_mm": 9200,
        "takeoff_results": [IN_PROGRESS, FAILED],
    }))
    result = run(link, altitude_timeout=2, progress_timeout=1)
    assert result["state"] != "LAUNCH_SUCCEEDED"
    assert "rejected the takeoff command" in result["reason"]


def test_rejected_takeoff_is_not_success_at_target_relative_altitude(clock):
    link = FakeLink(clock, launch_stream({
        "alt_mm": 9200,
        "climb": False,
        "takeoff_results": [IN_PROGRESS, FAILED],
    }))
    result = run(link, altitude_timeout=2, progress_timeout=1)
    assert result["state"] != "LAUNCH_SUCCEEDED", result


def test_in_progress_without_a_final_ack_can_still_reach_altitude(clock):
    link = FakeLink(clock, launch_stream({
        "climb": True,
        "takeoff_results": [IN_PROGRESS],
    }))
    result = run(link)
    assert result["state"] == "LAUNCH_SUCCEEDED", result
    assert commands_named(link, TAKEOFF)


def test_mode_change_during_climb_does_not_command_land(clock):
    link = FakeLink(clock, launch_stream({
        "alt_mm": 2000,
        "climb": False,
        "takeoff_results": [ACCEPTED],
        "mode_after_takeoff": 0,
    }))
    result = run(link, altitude_timeout=2)
    assert result["state"] != "LAUNCH_SUCCEEDED"
    assert LAND not in link.modes


def test_low_relative_altitude_does_not_disarm(clock):
    link = FakeLink(clock, launch_stream({
        "alt_mm": 100,
        "climb": False,
        "disarm_after_takeoff": True,
        "takeoff_results": [DENIED],
    }))
    result = run(link, altitude_timeout=2)
    disarms = [args for args in commands_named(link, ARM) if args[4] == 0]
    assert disarms == []
    assert result["state"] != "LAUNCH_SUCCEEDED"


def test_bad_data_does_not_let_a_buffered_ack_decide_takeoff(clock):
    link = FakeLink(
        clock,
        launch_stream({"climb": True, "takeoff_results": [ACCEPTED]}),
        queued=[Msg("BAD_DATA"), ack(TAKEOFF, DENIED)],
    )
    result = run(link)
    assert commands_named(link, TAKEOFF)
    assert result["state"] == "LAUNCH_SUCCEEDED", result


def test_uncertain_takeoff_write_is_not_labelled_complete(clock):
    link = FakeLink(clock, launch_stream({}))
    original = link.mav.command_long_send

    def command_long_send(*args):
        if args[2] == TAKEOFF:
            raise RuntimeError("command write failed")
        original(*args)

    link.mav.command_long_send = command_long_send
    result = run(link)
    assert result["state"] == "LAUNCH_INTERRUPTED", result
    assert result["write_completed"] is None
    assert result["write_completed"] is not True
    assert result["arm_requested"] is True
    assert result["takeoff_requested"] is False
    assert result["commands_started"] is True
    assert result["reasons"] == [result["reason"]]
    assert "Takeoff frame was not sent" in result["reason"]
    assert LAND not in link.modes
