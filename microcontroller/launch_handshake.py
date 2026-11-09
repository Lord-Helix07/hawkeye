"""Launch preparation and the operator-confirmation handshake.

This module does not send GUIDED, arm, or takeoff. Those commands stay in
launch_sequence.py. DynamoDB calls are queued through backend_comms.
"""

import time

import backend_comms
import health_monitor
import launch_sequence
from flight_controller import fc_connection
from flight_controller import fc_status
from flight_controller import fc_utils
from flight_controller import heartbeat

HEARTBEAT_WAIT = 10


def preparation_result(state, drone_id, reason, reasons=None):
    """Handshake result. No command write fields."""
    return {
        "state": state,
        "drone_id": drone_id,
        "reason": reason,
        "reasons": reasons if reasons is not None else [reason],
        "arm_requested": False,
        "takeoff_requested": False,
        "handoff": None,
        "commands_started": False,
    }


def _awaiting_confirmation(drone_id, reason):
    return preparation_result("AWAITING_CONFIRMATION", drone_id, reason)


def clear_launch_wait(flight):
    flight["launch_phase"] = None
    flight["launch_mission_id"] = None
    flight["confirm_deadline"] = None
    flight["next_confirm_poll"] = None
    backend_comms.set_launch_context(None, None)


def launch_stop(flight, cache):
    """True when a landing trigger has asked this launch to stop."""
    if flight.get("pending_landing") or flight.get("abort_launch"):
        return True
    return bool(isinstance(cache, dict) and cache.get("abort_launch"))


def assess_readiness(cache, stop=None, pump=None, timeout=None):
    """Read until heartbeat, GPS, and pre-arm are all fresh, then ask health."""
    if timeout is None:
        timeout = launch_sequence.READINESS_TIMEOUT
    #initialize the variables for the heartbeat, GPS, and status
    # The shared cache holds the samples. This loop does not call recv_match.
    #while u still have time b4 timeout corner

    def samples_ready():
        #how much time is left before timeout corner
        #read the heartbeat, GPS, and status from the drone, if it is not old data
        now = time.monotonic()
        status = fc_status.snapshot(cache, now)
        #if the message is not bad data and exists
        #get the type of the message
        #we have all the values we need
        # each timestamp must be recent; one stale sample
        # decide only after all three samples exist and are freshe vals form our readiness reasons
        return fc_status.launch_samples_ready(status)

    reached = fc_utils.wait_until(
        cache, timeout, samples_ready, stop=stop, pump=pump
    )
    if stop is not None and stop():
        return None
    now = time.monotonic()
    status = fc_status.snapshot(cache, now)
    reasons = health_monitor.launch_readiness(status)
    # if len(reasons) == 0, there are NO reasons, drone is ready, if len isnt 0 ready is false
    ready = bool(reached) and len(reasons) == 0
    #either true, and no reasons, or false, and reasons
    if not reached:
        #times up return false and reasons
        return False, reasons
    return ready, reasons


def _report(flight, mission_id, status, reason, reasons, result):
    """Queue one launch write. Enqueue success is not a completed write."""
    request_id = backend_comms.new_request_id()
    seq = backend_comms.enqueue_launch_report(
        mission_id,
        flight.get("session_id"),
        status,
        reason,
        reasons,
        request_id,
    )
    queued = backend_comms.record_report_enqueue(result, seq)
    flight["last_launch_result"] = result
    return queued


def _not_ready(flight, mission_id, drone_id, reason, reasons):
    result = preparation_result("NOT_READY", drone_id, reason, reasons)
    _report(
        flight,
        mission_id,
        backend_comms.LAUNCH_NOT_READY,
        reason,
        reasons,
        result,
    )
    clear_launch_wait(flight)
    flight["launch_row"] = None
    flight["prelaunch_checked"] = False
    return result


def apply_lifecycle(flight, result):
    if result is None:
        return
    if result.get("commands_started") or result.get("state") == "LAUNCH_SUCCEEDED":
        flight["launch_started"] = True
    # hand off only after the climb is verified
    if result.get("state") == "LAUNCH_SUCCEEDED":
        flight["following"] = True


def _dispatch(flight, cache, mission_id, drone_id, stop, pump):
    if stop is not None and stop():
        return None

    def progress(status, result):
        if status == "LAUNCH_SUCCEEDED":
            website = backend_comms.LAUNCH_FINISHED
            reason = result.get("reason") or "Climb confirmed"
            reasons = None
        elif status == "NOT_READY":
            website = backend_comms.LAUNCH_NOT_READY
            reason = result.get("reason")
            reasons = result.get("reasons") or [reason]
        elif status in ("LAUNCH_FAILED", "LAUNCH_INTERRUPTED"):
            website = backend_comms.LAUNCH_FAILED_STATUS
            reason = result.get("reason")
            reasons = result.get("reasons") or [reason]
        else:
            return
        _report(flight, mission_id, website, reason, reasons, result)

    result = launch_sequence.run_launch(
        cache, drone_id, progress=progress, stop=stop, pump=pump
    )
    if result is None:
        return None
    clear_launch_wait(flight)
    apply_lifecycle(flight, result)
    return result


def _continue_launch_confirmation(flight, cache, drone_id, stop, pump):
    mission_id = flight.get("launch_mission_id")
    outcome = flight.pop("confirm_outcome", None)
    if outcome == "confirmed":
        flight["operator_confirmed"] = True
        # the wait can be long, so the pre-arm check has to pass again
        assessed = assess_readiness(cache, stop=stop, pump=pump)
        if stop is not None and stop():
            return None
        if assessed is None:
            return None
        ready, reasons = assessed
        # readiness failed, so stop. this does not retry
        if not ready:
            return _not_ready(
                flight,
                mission_id,
                drone_id,
                "Flight controller is not ready",
                reasons,
            )
        return _dispatch(flight, cache, mission_id, drone_id, stop, pump)
    if outcome not in (None, "waiting", "read_failed"):
        clear_launch_wait(flight)
        return preparation_result(
            "CONFIRMATION_CANCELLED",
            drone_id,
            "Operator confirmation was cleared",
            reasons=None,
        )
    now = time.monotonic()
    if now >= flight.get("confirm_deadline", now):
        flight["ready_suppressed"] = mission_id
        clear_launch_wait(flight)
        return _awaiting_confirmation(drone_id, "Operator has not confirmed")
    # One telemetry read so the handshake wait does not starve the cache.
    fc_connection.read(cache, 0.2)
    if pump is not None:
        pump()
    if stop is not None and stop():
        return None
    now = time.monotonic()
    if not heartbeat.view(cache["heartbeat"], now)["fresh"]:
        reason = "Communication lost while waiting for operator confirmation"
        return _not_ready(flight, mission_id, drone_id, reason, [reason])
    if outcome == "read_failed":
        return _awaiting_confirmation(drone_id, "Could not read operator confirmation")
    if now < flight.get("next_confirm_poll", now) or flight.get("confirm_inflight"):
        return _awaiting_confirmation(drone_id, "Operator has not confirmed")
    request_id = backend_comms.new_request_id()
    session_id, launch_token = backend_comms.current_tokens()
    queued = backend_comms.enqueue_launch_confirm(
        mission_id, session_id, launch_token, request_id
    )
    flight["next_confirm_poll"] = now + backend_comms.CONFIRM_POLL_SECONDS
    if queued:
        flight["confirm_inflight"] = request_id
    return _awaiting_confirmation(drone_id, "Operator has not confirmed")


def _queue_ready(flight, mission_id, drone_id):
    request_id = backend_comms.new_request_id()
    seq = backend_comms.enqueue_launch_report(
        mission_id,
        flight.get("session_id"),
        backend_comms.LAUNCH_READY,
        "Flight controller is ready",
        None,
        request_id,
    )
    if not seq:
        result = preparation_result(
            "NOT_READY",
            drone_id,
            "Could not report ready to the operator",
            reasons=None,
        )
        result["report_state"] = "failed"
        result["report_error"] = "report queue full"
        return result
    flight["ready_report_seq"] = seq
    flight["ready_report_failed"] = None
    flight["launch_phase"] = "reporting_ready"
    flight["launch_mission_id"] = mission_id
    backend_comms.set_launch_context(mission_id, "reporting_ready")
    # stay here until the operator confirms. takeoff is still not sent.
    return preparation_result(
        "REPORT_PENDING",
        drone_id,
        "Ready report has not been written",
        reasons=None,
    )


def poll(flight, cache, missions, drone_id, stop=None, pump=None):
    """One slice of the launch handshake or the takeoff itself.

    Confirmation does not block inside this call. The caller keeps calling
    poll_flight, which keeps reading telemetry between confirmation checks.
    A landing trigger recorded during a read ends this slice before another
    launch command is sent.
    """
    if cache is None or not isinstance(flight, dict) or not flight.get("flight_active"):
        return None
    if flight.get("landing_started") or flight.get("launch_started"):
        return None
    if stop is not None and stop():
        clear_launch_wait(flight)
        return None

    phase = flight.get("launch_phase")
    if phase == "reporting_ready":
        failed = flight.get("ready_report_failed")
        if failed:
            flight["ready_report_failed"] = None
            result = preparation_result(
                "NOT_READY",
                drone_id,
                "Could not report ready to the operator",
                reasons=None,
            )
            error = failed.get("error") or failed.get("reason") or "report outcome uncertain"
            result["report_error"] = error
            result["report_state"] = failed.get("state")
            clear_launch_wait(flight)
            return result
        return preparation_result(
            "REPORT_PENDING",
            drone_id,
            "Ready report has not been written",
            reasons=None,
        )
    if phase == "awaiting_confirmation":
        return _continue_launch_confirmation(flight, cache, drone_id, stop, pump)

    #set table value
    if missions is None:
        return None

    # pending, active, visual_contact_lost, and completed are mission states.
    # Only launch_status starts this sequence.
    row = flight.get("launch_row")
    if not row:
        now = time.monotonic()
        if not flight.get("scan_inflight") and now >= flight.get("next_scan_poll", 0):
            request_id = backend_comms.new_request_id()
            session_id, launch_token = backend_comms.current_tokens()
            queued = backend_comms.enqueue_launch_scan(
                drone_id, session_id, launch_token, request_id
            )
            flight["next_scan_poll"] = now + backend_comms.CONFIRM_POLL_SECONDS
            if queued:
                flight["scan_inflight"] = request_id
        return None

    mission_id = row["mission_id"]
    if not flight.get("prelaunch_checked"):
        #if we dont get a heartbeat, --> send the result as NOT READY
        fc_utils.wait_until(
            cache,
            HEARTBEAT_WAIT,
            lambda: heartbeat.view(cache["heartbeat"], time.monotonic())["fresh"],
            stop=stop,
            pump=pump,
        )
        if stop is not None and stop():
            return None
        if not heartbeat.view(cache["heartbeat"], time.monotonic())["fresh"]:
            reason = "Flight controller heartbeat missing"
            return _not_ready(flight, mission_id, drone_id, reason, [reason])

        # heartbeat, GPS, and pre-arm must all pass before any command is sent
        assessed = assess_readiness(cache, stop=stop, pump=pump)
        if assessed is None or (stop is not None and stop()):
            return None
        ready, reasons = assessed
        flight["prelaunch_checked"] = True
        # readiness failed, so stop. this does not retry
        if not ready:
            return _not_ready(
                flight,
                mission_id,
                drone_id,
                "Flight controller is not ready",
                reasons,
            )

    # A row that is already confirmed has passed this wait on an earlier call.
    if row.get("launch_status") != backend_comms.LAUNCH_CONFIRMED and not flight.get("operator_confirmed"):
        if flight.get("ready_suppressed") == mission_id:
            return None
        return _queue_ready(flight, mission_id, drone_id)
    return _dispatch(flight, cache, mission_id, drone_id, stop, pump)
