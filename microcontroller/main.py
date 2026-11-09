"""Coordinate one flight controller link.

Launch preparation and operator confirmation go through launch_handshake.py.
launch_sequence.py sends GUIDED, arm, and takeoff. landing_sequence.py flies
LAND. health_monitor.py watches for faults. backend_comms.py owns the
DynamoDB worker. This module connects those parts, starts landing once,
and closes the link on the way out.

The flight thread reads telemetry, applies worker results, and runs health.
It does not call DynamoDB. A pump after each read lets a fault or a landing
request stop launch before another command is sent.
"""

import os
import time

import health_monitor
import launch_handshake
import landing_sequence
from flight_controller import fc_connection
import backend_comms


def new_flight_state(flight_active=False):
    """Latch kept by the caller across loop iterations.

    landing_started is not recreated on each poll. following is set by
    the caller when follow mode is running and cleared here before landing.
    launch_phase holds the operator handshake without blocking the caller.
    """
    return {
        "flight_active": flight_active,
        "landing_started": False,
        "following": False,
        "trigger_reason": None,
        "launch_started": False,
        "launch_phase": None,
        "launch_mission_id": None,
        "confirm_deadline": None,
        "next_confirm_poll": None,
        "cache": None,
        "pending_landing": False,
        "pending_trigger": None,
        "abort_launch": False,
    }


def _authorized(execute_landing, simulation_confirmed, allow_hardware_landing):
    if not execute_landing:
        return "LANDING_DISABLED", "Landing execution is disabled."
    if simulation_confirmed == allow_hardware_landing:
        return "AUTHORIZATION_REQUIRED", "Select exactly one verified execution environment."
    return None, None


def _refused(state, reason, trigger_reason):
    return {
        "state": state,
        "reason": reason,
        "trigger_reason": trigger_reason,
        "request_attempted": False,
        "write_completed": False,
        "land_mode_confirmed": False,
        "touchdown_confirmed": False,
    }


def _begin(flight, trigger_reason):
    """Stop following and latch landing. False when this flight must not start."""
    if not isinstance(flight, dict) or not flight.get("flight_active"):
        return False
    if flight.get("landing_started"):
        flight["following"] = False
        return False
    flight["landing_started"] = True
    flight["following"] = False
    flight["trigger_reason"] = trigger_reason
    flight["pending_landing"] = False
    flight["abort_launch"] = True
    cache = flight.get("cache")
    if isinstance(cache, dict):
        cache["abort_launch"] = True
    launch_handshake.clear_launch_wait(flight)
    return True


def _flight_cache(flight, link):
    """Reuse the coordinator's cache so landing and launch share one reader."""
    return _shared_cache(flight, link, None)


def request_landing(
    flight,
    link,
    trigger_reason=None,
    table=None,
    drone_id=None,
    execute_landing=False,
    simulation_confirmed=False,
    allow_hardware_landing=False,
    pump=None,
):
    """Land once on this flight. Caller already accepted the website row or fault.

    trigger_reason None is a website request. A string is a local fault.
    A Drones field is never read here, so it cannot pretend to be that fault.
    Authorization is checked before the latch, so a refused call can be retried.
    """
    state, reason = _authorized(
        execute_landing, simulation_confirmed, allow_hardware_landing
    )
    if state:
        return _refused(state, reason, trigger_reason)
    if not _begin(flight, trigger_reason):
        return None
    progress = None if drone_id is None else _landing_progress(flight, table, drone_id)
    cache = _flight_cache(flight, link)
    return landing_sequence.run_landing(
        cache,
        progress=progress,
        trigger_reason=trigger_reason,
        pump=pump,
    )


def _shared_cache(flight, link, cache):
    if cache is not None:
        flight["cache"] = cache
        return cache
    if flight.get("cache") is not None:
        return flight["cache"]
    if link is None:
        return None
    flight["cache"] = fc_connection.cache_for(link)
    return flight["cache"]


def _provider_health(health_provider):
    if health_provider is None:
        return None
    try:
        supplied = health_provider()
    except Exception:
        return None
    if isinstance(supplied, dict):
        return supplied
    return None


def _landing_progress(flight, table, drone_id):
    """Queue landing writes. The worker performs them. The function stays for direct callers."""

    def progress(status, result):
        flight["last_landing_result"] = result
        request_id = backend_comms.new_request_id()
        seq = backend_comms.enqueue_landing_report(
            drone_id,
            flight.get("session_id"),
            status,
            request_id,
        )
        backend_comms.record_report_enqueue(result, seq)

    return progress


def _clear_match(flight, field, request_id):
    if request_id is not None and flight.get(field) == request_id:
        flight[field] = None


def _attach_report(flight, result):
    target = flight.get("last_launch_result") if result.get("kind") == "launch_report" else flight.get("last_landing_result")
    if not isinstance(target, dict) or target.get("report_seq") != result.get("seq"):
        return
    state = result.get("state")
    target["report_state"] = state
    if state == "completed":
        return
    if state == "uncertain":
        message = result.get("error") or result.get("reason") or "report outcome uncertain"
    else:
        message = result.get("error") or result.get("reason") or "report was not sent"
    if "report_error" not in target:
        target["report_error"] = message


def _apply(flight, result):
    """Apply one worker result. The flight thread is the only caller."""
    if not isinstance(result, dict) or result.get("session_id") != flight.get("session_id"):
        return
    kind = result.get("kind")
    _, token = backend_comms.current_tokens()
    if kind in ("launch_scan", "launch_confirm") and result.get("launch_token") != token:
        if kind == "launch_scan":
            _clear_match(flight, "scan_inflight", result.get("request_id"))
        else:
            _clear_match(flight, "confirm_inflight", result.get("request_id"))
        return
    if kind == "landing_check":
        _clear_match(flight, "landing_inflight", result.get("request_id"))
        flight["landing_answered"] = True
        if result.get("state") == "completed":
            flight["landing_requested"] = bool(result.get("requested"))
        else:
            flight["backend_error"] = result.get("error") or result.get("reason")
        return
    if kind == "launch_scan":
        _clear_match(flight, "scan_inflight", result.get("request_id"))
        if result.get("state") == "completed":
            flight["launch_row"] = result.get("item")
        else:
            flight["backend_error"] = result.get("error") or result.get("reason")
        return
    if kind == "launch_confirm":
        _clear_match(flight, "confirm_inflight", result.get("request_id"))
        if result.get("state") == "completed":
            flight["confirm_outcome"] = result.get("outcome")
        else:
            flight["confirm_outcome"] = "read_failed"
        return
    if kind in ("launch_report", "landing_report"):
        _attach_report(flight, result)
        if (
            kind == "launch_report"
            and flight.get("launch_phase") == "reporting_ready"
            and result.get("seq") == flight.get("ready_report_seq")
        ):
            if result.get("state") == "completed":
                now = time.monotonic()
                flight["launch_phase"] = "awaiting_confirmation"
                flight["confirm_deadline"] = now + backend_comms.CONFIRM_TIMEOUT
                flight["next_confirm_poll"] = now
                backend_comms.set_launch_context(
                    flight.get("launch_mission_id"),
                    "awaiting_confirmation",
                )
            else:
                flight["ready_report_failed"] = result


def _maybe_landing_check(flight, table, drone_id, force=False):
    if table is None or drone_id is None or flight.get("landing_started"):
        return
    if flight.get("landing_inflight"):
        return
    now = time.monotonic()
    if not force and now < flight.get("next_landing_poll", 0):
        return
    request_id = backend_comms.new_request_id()
    queued = backend_comms.enqueue_landing_check(
        drone_id,
        flight.get("session_id"),
        request_id,
    )
    flight["next_landing_poll"] = now + backend_comms.CONFIRM_POLL_SECONDS
    if queued:
        flight["landing_inflight"] = request_id


def _watch(flight, cache, limits, health_provider):
    """Connect the cache reader to health monitoring for this flight."""
    try:
        website = bool(flight.get("landing_requested"))
        monitor_link = bool(
            flight.get("launch_started")
            or flight.get("following")
            or (isinstance(cache, dict) and cache.get("commands_started"))
        )
        health_monitor.watch(
            flight,
            cache,
            limits,
            health_provider,
            website,
            monitor_link,
        )
    except Exception:
        return


def _landing_priority(
    flight,
    link,
    table,
    drone_id,
    health,
    limits,
    execute_landing,
    simulation_confirmed,
    allow_hardware_landing,
    pump=None,
):
    """Land for a recorded fault, a new fault, or a website row. Otherwise None."""

    def start(reason):
        return request_landing(
            flight,
            link,
            trigger_reason=reason,
            table=table,
            drone_id=drone_id,
            execute_landing=execute_landing,
            simulation_confirmed=simulation_confirmed,
            allow_hardware_landing=allow_hardware_landing,
            pump=pump,
        )

    pending = flight.get("pending_trigger")
    if flight.get("pending_landing") and isinstance(pending, str) and pending:
        return health_monitor.consider_fault_landing(flight, health, limits, start)

    if health is not None:
        result = health_monitor.consider_fault_landing(flight, health, limits, start)
        if result is not None or flight.get("landing_started"):
            return result

    if flight.get("pending_landing") or flight.get("landing_requested"):
        return start(None)
    return None


def poll_flight(
    flight,
    link,
    table,
    drone_id,
    health=None,
    limits=None,
    execute_landing=False,
    simulation_confirmed=False,
    allow_hardware_landing=False,
    missions=None,
    cache=None,
    health_provider=None,
):
    """One coordination pass. Landing and faults preempt launch.

    An in-progress launch handshake is cancelled when a landing trigger is
    already waiting. A trigger recorded while launch is blocked is taken
    as soon as that call returns, and only one landing is started.
    """
    if not isinstance(flight, dict) or not flight.get("flight_active"):
        return None
    if not flight.get("session_id"):
        flight["session_id"] = backend_comms.begin_session()
    backend_comms.ensure_worker(missions, table)

    def pump(force_check=False):
        for item in backend_comms.poll_results():
            _apply(flight, item)
        _maybe_landing_check(flight, table, drone_id, force=force_check)
        _watch(flight, flight.get("cache"), limits, health_provider)

    pump(True)
    if flight.get("landing_started"):
        flight["following"] = False
        return None

    shared = _shared_cache(flight, link, cache)
    landing = _landing_priority(
        flight,
        link,
        table,
        drone_id,
        health,
        limits,
        execute_landing,
        simulation_confirmed,
        allow_hardware_landing,
        pump,
    )
    if landing is not None or flight.get("landing_started"):
        return landing
    # The first landing answer has to win over the first launch command.
    # Later checks stay in the background so a slow read cannot freeze launch.
    if (
        flight.get("landing_inflight")
        and not flight.get("landing_answered")
        and not flight.get("launch_started")
    ):
        return None

    def stop():
        return launch_handshake.launch_stop(flight, shared)

    result = launch_handshake.poll(flight, shared, missions, drone_id, stop, pump)
    landing = _landing_priority(
        flight,
        link,
        table,
        drone_id,
        health,
        limits,
        execute_landing,
        simulation_confirmed,
        allow_hardware_landing,
        pump,
    )
    if landing is not None or flight.get("landing_started"):
        return landing
    return result


def run(
    drone_id,
    execute_landing=False,
    simulation_confirmed=False,
    allow_hardware_landing=False,
    address=None,
    baud=None,
    missions=None,
    table=None,
    health_provider=None,
    limits=None,
    max_cycles=None,
):
    """Open the link, run until landing finishes or the flight stops, then close it."""
    cache = None
    flight = new_flight_state(True)
    try:
        if missions is None:
            missions = backend_comms.missions_table()
        if table is None:
            table = backend_comms.drones_table()
        flight["session_id"] = backend_comms.begin_session()
        backend_comms.ensure_worker(missions, table)
        cache = fc_connection.open_link(address, baud)
        flight["cache"] = cache
        cycles = 0
        while flight.get("flight_active") and not flight.get("landing_started"):
            if max_cycles is not None and cycles >= max_cycles:
                break
            cycles += 1
            if not flight.get("launch_phase"):
                fc_connection.read(cache, 0.2)
            if flight.get("landing_started"):
                break
            poll_flight(
                flight,
                cache.get("link"),
                table,
                drone_id,
                health=_provider_health(health_provider),
                limits=limits,
                execute_landing=execute_landing,
                simulation_confirmed=simulation_confirmed,
                allow_hardware_landing=allow_hardware_landing,
                missions=missions,
                cache=cache,
                health_provider=health_provider,
            )
        return flight
    finally:
        try:
            if cache is not None:
                fc_connection.close_link(cache)
        finally:
            leftovers = backend_comms.stop_worker() or []
            for item in leftovers:
                _apply(flight, item)
            flight["backend_shutdown"] = leftovers


def main():
    drone_id = os.environ.get("DRONE_ID")
    if not drone_id:
        raise SystemExit("DRONE_ID is required")
    try:
        run(
            drone_id,
            execute_landing=os.environ.get("EXECUTE_LANDING") == "1",
            simulation_confirmed=os.environ.get("SIMULATION_CONFIRMED") == "1",
            allow_hardware_landing=os.environ.get("ALLOW_HARDWARE_LANDING") == "1",
        )
    except SystemExit:
        raise
    except Exception as error:
        raise SystemExit(str(error))


if __name__ == "__main__":
    main()
