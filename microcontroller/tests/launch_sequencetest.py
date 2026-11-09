"""Launch procedure on the shared flight-controller cache. No live link."""

import inspect

from pymavlink import mavutil

import launch_sequence
from fakes import (
    ACCEPTED,
    ARM,
    DENIED,
    FAILED,
    GUIDED,
    IN_PROGRESS,
    LAND,
    STABILIZE,
    TAKEOFF,
    FakeLink,
    Msg,
    ack,
    commands_named,
    heartbeat,
    launch_stream,
    position,
)
from flight_controller import fc_connection

SET_MODE = mavutil.mavlink.MAV_CMD_DO_SET_MODE


def run(link, **kwargs):
    cache = None if link is None else fc_connection.cache_for(link)
    return launch_sequence.run_launch(cache, "drone-1", **kwargs)


def test_launch_does_not_read_mavlink_or_open_a_connection(clock):
    source = inspect.getsource(launch_sequence)
    assert "recv_match" not in source
    assert "mavlink_connection" not in source
    assert "boto3" not in source
    link = FakeLink(clock, launch_stream({"climb": True, "takeoff_results": [ACCEPTED]}))
    seen = []

    def recv_match(*args, **kwargs):
        caller = inspect.stack()[1].filename
        seen.append(caller)
        assert caller.endswith("fc_connection.py")
        return FakeLink.recv_match(link, *args, **kwargs)

    link.recv_match = recv_match
    result = run(link)
    assert result["state"] == "LAUNCH_SUCCEEDED", result
    assert seen
    assert link.close_count == 0
    assert link.modes == [GUIDED]
    assert commands_named(link, ARM)
    assert commands_named(link, TAKEOFF)
    assert abs(commands_named(link, TAKEOFF)[0][10] - 9.144) < 1e-6
    assert result["altitude_m"] >= 9.144 - launch_sequence.ALTITUDE_TOLERANCE
    assert result["handoff"] == "autonomous"
    assert result["reason"] == "Climb confirmed"


def test_progress_matches_the_result_and_a_report_error_does_not_erase_it(clock):
    link = FakeLink(clock, launch_stream({"climb": True, "takeoff_results": [ACCEPTED]}))
    seen = []

    def progress(status, result):
        seen.append((status, result["state"], result["reason"]))
        raise RuntimeError("backend down")

    result = run(link, progress=progress)
    assert result["state"] == "LAUNCH_SUCCEEDED", result
    assert seen == [("LAUNCH_SUCCEEDED", "LAUNCH_SUCCEEDED", "Climb confirmed")]
    assert result["report_error"] == "backend down"


def test_guided_unavailable_sends_nothing(clock):
    link = FakeLink(clock, launch_stream({}))
    link.mode_mapping = lambda: {}
    result = run(link)
    assert result["state"] == "NOT_READY", result
    assert result["reason"] == "GUIDED mode unavailable"
    assert result["reasons"] == ["GUIDED mode unavailable"]
    assert result["commands_started"] is False
    assert result["arm_requested"] is False
    assert result["takeoff_requested"] is False
    assert result["handoff"] is None
    assert link.modes == []
    assert link.commands == []


def test_uncertain_mode_write_is_not_success(clock):
    link = FakeLink(clock, launch_stream({}))
    link.fail_set_mode = True
    cache = fc_connection.cache_for(link)
    result = launch_sequence.run_launch(cache, "drone-1")
    assert result["state"] == "LAUNCH_FAILED", result
    assert result["write_completed"] is None
    assert "GUIDED frame was not sent" in result["reason"]
    assert result["reasons"] == [result["reason"]]
    assert result["commands_started"] is True
    assert result["arm_requested"] is False
    assert result["takeoff_requested"] is False
    assert cache["commands_started"] is True
    assert link.commands == []


def test_uncertain_arm_write_is_not_success(clock):
    link = FakeLink(clock, launch_stream({}))
    link.fail_command = True
    result = run(link)
    assert result["state"] == "LAUNCH_FAILED", result
    assert result["write_completed"] is None
    assert result["arm_requested"] is False
    assert result["takeoff_requested"] is False
    assert result["commands_started"] is True
    assert "Arm frame was not sent" in result["reason"]
    assert result["reasons"] == [result["reason"]]
    assert commands_named(link, TAKEOFF) == []


def test_rejected_arm_does_not_take_off(clock):
    link = FakeLink(clock, launch_stream({"arm_result": DENIED}))
    result = run(link, arm_timeout=1)
    assert result["state"] == "LAUNCH_FAILED", result
    assert "rejected the arm command" in result["reason"]
    assert commands_named(link, TAKEOFF) == []


def test_takeoff_is_not_sent_after_mode_leaves_guided(clock):
    link = FakeLink(clock, launch_stream({"mode_after_arm": 0}))
    result = run(link, arm_timeout=0.6)
    assert commands_named(link, ARM)
    assert commands_named(link, TAKEOFF) == []
    assert result["state"] != "LAUNCH_SUCCEEDED"


def test_rejected_takeoff_is_not_success_at_target_altitude(clock):
    link = FakeLink(clock, launch_stream({
        "alt_mm": 9200,
        "climb": False,
        "takeoff_results": [IN_PROGRESS, FAILED],
    }))
    result = run(link, altitude_timeout=2, progress_timeout=1)
    assert result["state"] != "LAUNCH_SUCCEEDED", result
    assert "rejected the takeoff command" in result["reason"]


def test_in_progress_without_a_final_ack_can_still_climb(clock):
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
    assert "left GUIDED" in result["reason"]


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


def test_buffered_rejection_does_not_decide_the_new_takeoff(clock):
    link = FakeLink(
        clock,
        launch_stream({"climb": True, "takeoff_results": [ACCEPTED]}),
        queued=[Msg("BAD_DATA"), ack(TAKEOFF, DENIED)],
    )
    result = run(link)
    assert result["state"] == "LAUNCH_SUCCEEDED", result
    assert commands_named(link, TAKEOFF)


def test_stale_altitude_is_not_success(clock, monkeypatch):
    import fc_status

    monkeypatch.setattr(fc_status, "FRESH_SECONDS", 0.2)
    base = launch_stream({"takeoff_results": [ACCEPTED]})

    def default(link):
        if commands_named(link, TAKEOFF):
            return heartbeat(GUIDED, True)
        return base(link)

    link = FakeLink(clock, default)
    result = run(link, altitude_timeout=2, progress_timeout=2)
    assert result["state"] != "LAUNCH_SUCCEEDED", result
    assert "Altitude telemetry missing or stale" in result["reason"]


def test_no_altitude_progress_is_not_success(clock):
    link = FakeLink(clock, launch_stream({
        "alt_mm": 300,
        "climb": False,
        "takeoff_results": [ACCEPTED],
    }))
    result = run(link, altitude_timeout=2, progress_timeout=0.3)
    assert result["state"] != "LAUNCH_SUCCEEDED", result
    assert result["reason"] == "No altitude progress"


def test_missing_cache_does_not_command(clock):
    result = launch_sequence.run_launch(None, "drone-1")
    assert result["state"] == "NOT_READY"
    assert "not connected" in result["reason"]


def _once_before_write(link, ready, frame):
    """Return one already-buffered frame from the non-blocking drain before a write."""
    seen = []
    original = link.recv_match

    def recv_match(*args, **kwargs):
        timeout = kwargs.get("timeout", args[1] if len(args) > 1 else None)
        if timeout == 0 and ready() and not seen:
            seen.append(frame)
            link.queued.insert(0, frame)
        return original(*args, **kwargs)

    link.recv_match = recv_match
    return seen


def test_arm_is_not_sent_after_guided_was_already_lost(clock):
    counts = {"n": 0}

    def guided_until_arm_sent(link):
        if commands_named(link, ARM):
            return heartbeat(STABILIZE, False)
        counts["n"] += 1
        if counts["n"] % 2:
            return heartbeat(GUIDED, False)
        return position(300)

    link = FakeLink(clock, guided_until_arm_sent)
    seen = _once_before_write(
        link,
        lambda: link.modes and not commands_named(link, ARM),
        heartbeat(STABILIZE, False),
    )
    result = run(link, mode_timeout=1.5, arm_timeout=1)
    assert seen, result
    assert commands_named(link, ARM) == [], (result, link.modes)
    assert commands_named(link, TAKEOFF) == []
    assert result["state"] != "LAUNCH_SUCCEEDED"


def test_takeoff_is_not_sent_after_disarm_was_already_buffered(clock):
    link = FakeLink(clock, launch_stream({
        "climb": False,
        "alt_mm": 300,
        "takeoff_results": [ACCEPTED],
        "disarm_after_takeoff": True,
    }))
    seen = _once_before_write(
        link,
        lambda: commands_named(link, ARM) and not commands_named(link, TAKEOFF),
        heartbeat(GUIDED, False),
    )
    result = run(link, arm_timeout=2, altitude_timeout=1.5, progress_timeout=0.8)
    assert seen, result
    assert commands_named(link, TAKEOFF) == [], result
    assert result["state"] != "LAUNCH_SUCCEEDED"
    assert LAND not in link.modes
    disarms = [args for args in commands_named(link, ARM) if args[4] == 0]
    assert disarms == []


def _buffer_after_takeoff(link, frames):
    original = link.recv_match
    armed = {"done": False}

    def recv_match(*args, **kwargs):
        timeout = kwargs.get("timeout", args[1] if len(args) > 1 else None)
        if (
            not armed["done"]
            and commands_named(link, TAKEOFF)
            and timeout not in (0, None)
        ):
            armed["done"] = True
            link.queued = list(frames) + list(link.queued)
        return original(*args, **kwargs)

    link.recv_match = recv_match
    return armed


def test_buffered_takeoff_rejection_is_not_climb_success(clock):
    link = FakeLink(clock, launch_stream({"climb": True, "takeoff_results": [ACCEPTED]}))
    rejection = ack(TAKEOFF, FAILED)
    _buffer_after_takeoff(link, [position(9200), rejection])
    result = run(link, altitude_timeout=2, progress_timeout=2)
    assert result["state"] != "LAUNCH_SUCCEEDED", (result, link.queued)
    assert "rejected the takeoff command" in result["reason"]
    assert result["handoff"] is None
    assert LAND not in link.modes


def test_buffered_mode_change_is_not_climb_success(clock):
    link = FakeLink(clock, launch_stream({
        "climb": False,
        "alt_mm": 100,
        "takeoff_results": [ACCEPTED],
    }))
    _buffer_after_takeoff(link, [position(9200), heartbeat(STABILIZE, True)])
    result = run(link, altitude_timeout=2, progress_timeout=2)
    assert result["state"] != "LAUNCH_SUCCEEDED", result
    assert "left GUIDED" in result["reason"]
    assert result["handoff"] is None
    assert LAND not in link.modes


def test_buffered_disarm_is_not_climb_success(clock):
    link = FakeLink(clock, launch_stream({
        "climb": False,
        "alt_mm": 100,
        "takeoff_results": [ACCEPTED],
    }))
    _buffer_after_takeoff(link, [position(9200), heartbeat(GUIDED, False)])
    result = run(link, altitude_timeout=2, progress_timeout=2)
    assert result["state"] != "LAUNCH_SUCCEEDED", result
    assert "disarmed" in result["reason"]
    assert result["handoff"] is None
    disarms = [args for args in commands_named(link, ARM) if args[4] == 0]
    assert disarms == []


def test_fresh_post_command_altitude_is_kept_when_heartbeat_returns(clock, monkeypatch):
    import fc_status

    monkeypatch.setattr(fc_status, "FRESH_SECONDS", 0.35)
    state = {"phase": 0, "pre": 0, "low": 0}

    def samples(link):
        arm_sent = bool(commands_named(link, ARM))
        takeoff_sent = bool(commands_named(link, TAKEOFF))
        if arm_sent and state["phase"] == 0:
            state["phase"] = 1
            return ack(ARM, ACCEPTED)
        if state["phase"] == 1:
            state["phase"] = 2
            return heartbeat(GUIDED, True)
        if takeoff_sent and state["phase"] == 2:
            state["low"] += 1
            if state["low"] <= 8:
                return position(400 + state["low"])
            if state["low"] == 9:
                return position(9500)
            return heartbeat(GUIDED, True)
        state["pre"] += 1
        if state["pre"] % 2:
            return heartbeat(GUIDED, False)
        return position(300)

    link = FakeLink(clock, samples)
    result = run(link, mode_timeout=2, arm_timeout=2, altitude_timeout=3, progress_timeout=3)
    assert result["state"] == "LAUNCH_SUCCEEDED", result
    assert result["altitude_m"] == 9.5
    assert result["handoff"] == "autonomous"


def _climb_if_takeoff_sent(link, state):
    """Enough of a climb to expose a rejection that was allowed to continue."""
    if not commands_named(link, TAKEOFF):
        return None
    state["n"] += 1
    if state["n"] == 1:
        return ack(TAKEOFF, ACCEPTED)
    if state["n"] % 2:
        return heartbeat(GUIDED, True)
    return position(min(300 + state["n"] * 1500, 9500))


def test_mode_rejection_buffered_behind_guided_heartbeat_does_not_arm(clock):
    queued = {"done": False}
    state = {"n": 0}

    def samples(link):
        climb = _climb_if_takeoff_sent(link, state)
        if climb is not None:
            return climb
        if link.modes and not queued["done"] and not commands_named(link, ARM):
            queued["done"] = True
            link.queued.append(ack(SET_MODE, DENIED))
            return heartbeat(GUIDED, False)
        if commands_named(link, ARM):
            return heartbeat(GUIDED, True)
        state["n"] += 1
        if state["n"] % 2:
            return heartbeat(GUIDED, False)
        return position(300)

    link = FakeLink(clock, samples)
    result = run(link, mode_timeout=2, arm_timeout=2, altitude_timeout=3, progress_timeout=2)
    assert queued["done"], result
    assert commands_named(link, ARM) == [], result
    assert commands_named(link, TAKEOFF) == []
    assert result["state"] != "LAUNCH_SUCCEEDED"
    assert "rejected GUIDED" in result["reason"]
    assert result["handoff"] is None
    assert LAND not in link.modes


def test_arm_rejection_buffered_behind_armed_heartbeat_does_not_take_off(clock):
    queued = {"done": False}
    state = {"n": 0}

    def samples(link):
        climb = _climb_if_takeoff_sent(link, state)
        if climb is not None:
            return climb
        if commands_named(link, ARM) and not queued["done"]:
            queued["done"] = True
            link.queued.append(ack(ARM, DENIED))
            return heartbeat(GUIDED, True)
        state["n"] += 1
        if state["n"] % 2:
            return heartbeat(GUIDED, False)
        return position(300)

    link = FakeLink(clock, samples)
    result = run(link, mode_timeout=2, arm_timeout=2, altitude_timeout=3, progress_timeout=2)
    assert queued["done"], result
    assert commands_named(link, ARM)
    assert commands_named(link, TAKEOFF) == [], result
    assert result["state"] != "LAUNCH_SUCCEEDED"
    assert "rejected the arm command" in result["reason"]
    assert result["handoff"] is None
    assert LAND not in link.modes
    disarms = [args for args in commands_named(link, ARM) if args[4] == 0]
    assert disarms == []
