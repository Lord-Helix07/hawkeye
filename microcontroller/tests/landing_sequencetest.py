"""Landing procedure defects and the paths around them.

External I/O is a scripted link. The production flight-controller helpers
parse and store the frames.
"""

import inspect

from pymavlink import mavutil

import landing_sequence
from fakes import (
    ACCEPTED,
    DENIED,
    GUIDED,
    IN_AIR,
    IN_PROGRESS,
    LAND,
    LOITER,
    ON_GROUND,
    FakeLink,
    ack,
    extended,
    heartbeat,
    position,
)
from flight_controller import fc_connection

SET_MODE = mavutil.mavlink.MAV_CMD_DO_SET_MODE


def run(link, **kwargs):
    cache = fc_connection.cache_for(link)
    progress = kwargs.pop("progress", None)
    return landing_sequence.run_landing(cache, progress=progress, **kwargs)


def test_newer_buffered_mode_is_not_treated_as_already_land(clock):
    """A LAND heartbeat is not current if a newer heartbeat is already buffered."""
    events = []

    def progress(status, result):
        events.append(
            (
                status,
                result["state"],
                result["land_mode_confirmed"],
                result["touchdown_confirmed"],
            )
        )

    link = FakeLink(
        clock,
        lambda link: None,
        queued=[heartbeat(LAND, True), heartbeat(LOITER, True)],
    )
    result = run(
        link,
        progress=progress,
        status_timeout=1,
        mode_timeout=0.4,
        landing_timeout=0.4,
    )

    assert link.modes == [LAND] or result["land_mode_confirmed"] is False, result
    assert events == [] or events[0][2] is False
    assert result["state"] != "LANDED"


def test_precommand_land_heartbeat_does_not_confirm_the_write(clock):
    """Mode confirmation has to be a heartbeat from after the LAND write."""
    seen_after_write = []

    link = FakeLink(
        clock,
        lambda link: None,
        queued=[heartbeat(GUIDED, True), heartbeat(LAND, True)],
    )
    original = link.recv_match

    def recv_match(*args, **kwargs):
        message = original(*args, **kwargs)
        if link.modes:
            seen_after_write.append(None if message is None else message.get_type())
        return message

    link.recv_match = recv_match
    result = run(link, mode_timeout=0.5, landing_timeout=0.5, status_timeout=1)

    assert link.modes == [LAND]
    assert "HEARTBEAT" not in seen_after_write
    assert result["land_mode_confirmed"] is False, result
    assert result["state"] != "LANDED"


def test_commanded_land_still_completes_from_later_telemetry(clock):
    step = {"n": 0}

    def default(link):
        if not link.modes:
            return heartbeat(GUIDED, True)
        step["n"] += 1
        slot = step["n"] % 3
        if slot == 1:
            return heartbeat(LAND, False)
        if slot == 2:
            return extended(ON_GROUND)
        return heartbeat(LAND, False)

    link = FakeLink(clock, default)
    events = []

    def progress(status, result):
        events.append(
            (
                status,
                result["state"],
                result["land_mode_confirmed"],
                result["touchdown_confirmed"],
                result["request_attempted"],
                result["write_completed"],
            )
        )

    result = run(link, progress=progress)
    assert result["state"] == "LANDED", result
    assert result["request_attempted"] is True
    assert result["write_completed"] is True
    assert events[0] == ("LANDING", "LANDING", True, False, True, True)
    assert events[-1][0] == "LANDED"
    assert events[-1][2] is True and events[-1][3] is True
    assert link.close_count == 0
    assert "recv_match" not in inspect.getsource(landing_sequence)


def test_touchdown_either_order_and_not_altitude_or_ack(clock):
    def sequence(first, second):
        pending = [heartbeat(GUIDED, True), first, second]

        def default(link):
            if pending:
                return pending.pop(0)
            return None

        link = FakeLink(clock, default)
        return run(link, mode_timeout=2, landing_timeout=2)

    disarmed = heartbeat(LAND, False)
    ground = extended(ON_GROUND)
    assert sequence(disarmed, ground)["state"] == "LANDED"
    assert sequence(ground, disarmed)["state"] == "LANDED"

    low = position(0)
    accepted = ack(SET_MODE, ACCEPTED)
    assert sequence(low, accepted)["state"] != "LANDED"
    assert sequence(heartbeat(LAND, True), extended(IN_AIR))["state"] != "LANDED"
    assert sequence(accepted, low)["state"] != "LANDED"


def test_rejection_uncertain_write_and_later_read_error(clock):
    denied = FakeLink(
        clock,
        lambda link: ack(SET_MODE, DENIED) if link.modes else heartbeat(GUIDED, True),
    )
    rejected = run(denied, mode_timeout=1, landing_timeout=1)
    assert rejected["state"] == "LANDING_REJECTED", rejected
    assert rejected["request_attempted"] is True
    assert rejected["write_completed"] is True
    assert rejected["land_mode_confirmed"] is False

    progress_only = FakeLink(
        clock,
        lambda link: ack(SET_MODE, IN_PROGRESS) if link.modes else heartbeat(GUIDED, True),
    )
    waiting = run(progress_only, mode_timeout=0.4, landing_timeout=0.4)
    assert waiting["state"] != "LANDED"
    assert waiting["land_mode_confirmed"] is False

    uncertain = FakeLink(clock, lambda link: heartbeat(GUIDED, True))
    uncertain.fail_set_mode = True
    failed_write = run(uncertain, mode_timeout=0.4)
    assert failed_write["state"] == "LANDING_OUTCOME_UNKNOWN", failed_write
    assert failed_write["request_attempted"] is True
    assert failed_write["write_completed"] is None

    broken = FakeLink(clock, lambda link: heartbeat(GUIDED, True))
    original = broken.set_mode

    def set_mode(mode_id):
        original(mode_id)
        broken.raise_on_read = True

    broken.set_mode = set_mode
    lost = run(broken, mode_timeout=1, landing_timeout=1)
    assert lost["state"] == "LANDING_OUTCOME_UNKNOWN", lost
    assert lost["request_attempted"] is True
    assert lost["write_completed"] is True
    assert lost["state"] != "LANDED"


def test_callback_failure_does_not_change_a_completed_landing(clock):
    step = {"n": 0}

    def default(link):
        if not link.modes:
            return heartbeat(GUIDED, True)
        step["n"] += 1
        if step["n"] == 1:
            return heartbeat(LAND, True)
        if step["n"] == 2:
            return extended(ON_GROUND)
        return heartbeat(LAND, False)

    link = FakeLink(clock, default)

    def progress(status, result):
        raise RuntimeError("backend down")

    result = run(link, progress=progress)
    assert result["state"] == "LANDED", result
    assert result["land_mode_confirmed"] is True
    assert result["touchdown_confirmed"] is True
    assert result["report_error"] == "backend down"
    assert link.close_count == 0
