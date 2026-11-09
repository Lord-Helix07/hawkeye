import time
from flight_controller import fc_config
from flight_controller import fc_connection
from flight_controller import fc_status
from flight_controller import fc_utils
from flight_controller import heartbeat

LANDING = "LANDING"
LANDED = "LANDED"
MODE_TIMEOUT = 10
LANDING_TIMEOUT = 90
# How long to look for an already-active LAND mode before commanding it.
STATUS_TIMEOUT = 5


def _result(state, trigger_reason, **extra):
    """One landing result. trigger_reason stays the caller's reason."""
    result = {
        "state": state,
        "reason": None,
        "trigger_reason": trigger_reason,
        "request_attempted": False,
        "write_completed": False,
        "land_mode_confirmed": False,
        "touchdown_confirmed": False,
    }
    result.update(extra)
    return result


def _emit(progress, status, result):
    if progress is None:
        return
    try:
        progress(status, result)
    except Exception as error:
        if "report_error" not in result:
            result["report_error"] = str(error)


def _set(result, state, reason, mode_confirmed, touchdown):
    result["state"] = state
    result["reason"] = reason
    result["land_mode_confirmed"] = mode_confirmed
    result["touchdown_confirmed"] = touchdown
    return result


def _show_landing(result):
    """Make the LANDING snapshot agree before main reports it."""
    result["state"] = LANDING
    result["land_mode_confirmed"] = True
    result["touchdown_confirmed"] = False


def _monitor(cache, result, confirm_mode, progress, mode_timeout, landing_timeout):
    fc_connection.mark_operation(cache)
    started = cache["operation_at"]
    deadline = started + (mode_timeout if confirm_mode else landing_timeout)
    mode_confirmed = not confirm_mode
    touchdown_mark = None if confirm_mode else started
    reported_landing = False

    if mode_confirmed:
        _show_landing(result)
        _emit(progress, LANDING, result)
        reported_landing = True

    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            message = fc_connection.read(cache, min(0.2, remaining))
        except (RuntimeError, OSError, TimeoutError):
            reason = (
                "Landing completion could not be verified."
                if mode_confirmed
                else "LAND mode was not confirmed."
            )
            return _set(result, "LANDING_OUTCOME_UNKNOWN", reason, mode_confirmed, False)
        now = time.monotonic()
        kind = None if message is None else message.get_type()

        if confirm_mode and fc_status.mode_is(cache, "LAND", now):
            confirm_mode = False
            mode_confirmed = True
            touchdown_mark = now
            deadline = now + landing_timeout
            if not reported_landing:
                _show_landing(result)
                _emit(progress, LANDING, result)
                reported_landing = True
        elif kind == "COMMAND_ACK" and not mode_confirmed:
            if fc_utils.rejected_set_mode(message):
                return _set(
                    result,
                    "LANDING_REJECTED",
                    "ArduPilot rejected LAND mode.",
                    False,
                    False,
                )

        if not mode_confirmed:
            continue
        if fc_status.touchdown(cache, now):
            result = _set(result, LANDED, "Touchdown and disarm confirmed.", True, True)
            return result
        if kind == "HEARTBEAT" and not fc_status.mode_is(cache, "LAND", now):
            return _set(
                result,
                "LANDING_INTERRUPTED",
                "Flight controller left LAND mode. No new command sent.",
                True,
                False,
            )
        if touchdown_mark is not None and now - touchdown_mark > fc_config.FRESH_SECONDS:
            reason = fc_status.stale_landing_reason(cache, now)
            if reason:
                return _set(result, "LANDING_OUTCOME_UNKNOWN", reason, True, False)

    reason = (
        "LAND mode was not confirmed."
        if not mode_confirmed
        else "Landing completion could not be verified."
    )
    return _set(result, "LANDING_OUTCOME_UNKNOWN", reason, mode_confirmed, False)


def _attempt(cache, progress, trigger_reason, mode_timeout, landing_timeout, status_timeout):
    attempted = False
    try:
        # Stop at the first fresh heartbeat. Waiting until the mode is
        # LAND would consume the messages that belong to confirmation.
        fc_utils.wait_until(
            cache,
            status_timeout,
            lambda: heartbeat.view(cache["heartbeat"], time.monotonic())["fresh"],
        )
        already_landing = fc_status.mode_is(cache, "LAND", time.monotonic())
        if already_landing:
            # Drop touchdown samples buffered before this request.
            fc_connection.drain(cache)
            delivery = {"attempted": False, "write_completed": False}
        else:
            delivery = fc_utils.request_mode(cache, "LAND")
            if delivery["mode_id"] is None:
                return _result(
                    "LANDING_NOT_AVAILABLE",
                    trigger_reason,
                    reason="LAND mode is unavailable.",
                )
            attempted = delivery["attempted"]
            if delivery["write_completed"] is None:
                return _result(
                    "LANDING_OUTCOME_UNKNOWN",
                    trigger_reason,
                    reason=f"LAND write outcome uncertain: {delivery['error']}",
                    request_attempted=True,
                    write_completed=None,
                )

        result = _result(
            "LANDING_OUTCOME_UNKNOWN",
            trigger_reason,
            request_attempted=delivery["attempted"],
            write_completed=delivery["write_completed"],
            land_mode_confirmed=already_landing,
        )
        return _monitor(
            cache,
            result,
            confirm_mode=not already_landing,
            progress=progress,
            mode_timeout=mode_timeout,
            landing_timeout=landing_timeout,
        )
    except (RuntimeError, OSError, TimeoutError) as error:
        return _result(
            "LANDING_OUTCOME_UNKNOWN" if attempted else "LANDING_FAILED_TO_START",
            trigger_reason,
            reason=str(error),
            request_attempted=attempted,
            write_completed=None if attempted else False,
        )


def run_landing(
    cache,
    progress=None,
    trigger_reason=None,
    mode_timeout=None,
    landing_timeout=None,
    status_timeout=None,
):

    if mode_timeout is None:
        mode_timeout = MODE_TIMEOUT
    if landing_timeout is None:
        landing_timeout = LANDING_TIMEOUT
    if status_timeout is None:
        status_timeout = STATUS_TIMEOUT
    if cache is None:
        result = _result(
            "LANDING_FAILED_TO_START",
            trigger_reason,
            reason="Flight controller link is not connected.",
        )
    else:
        result = _attempt(
            cache,
            progress,
            trigger_reason,
            mode_timeout,
            landing_timeout,
            status_timeout,
        )
    if result["state"] == LANDED and not (
        result["land_mode_confirmed"] and result["touchdown_confirmed"]
    ):
        raise RuntimeError("LANDED result does not match the confirmation flags.")
    _emit(progress, result["state"], result)
    return result
