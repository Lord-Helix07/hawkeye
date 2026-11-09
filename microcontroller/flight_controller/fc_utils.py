"""Command sending and bounded confirmation on the shared cache.

These helpers do not decide that a landing succeeded. They record whether
a mode write was attempted and whether delivery is certain, and they wait
until the caller-supplied condition is true. Link errors propagate.
A missing cache or link is a programming error and is not converted into
a flight result.
"""

import time

from pymavlink import mavutil

import fc_status as _fc

from flight_controller import fc_connection
from flight_controller import fc_status as status

SET_MODE = mavutil.mavlink.MAV_CMD_DO_SET_MODE


def emit_progress(progress, status, result):
    """Report one sequence update. A callback error is stored and does not replace the result."""
    if progress is None:
        return
    try:
        progress(status, result)
    except Exception as error:
        if "report_error" not in result:
            result["report_error"] = str(error)


def request_mode(cache, name):
    """Ask the flight controller for a mode. Does not wait for confirmation.

    write_completed is None when the write may have reached the controller.
    mode_id None means that mode is not in the controller's map. No write
    is attempted in that case.
    """
    link = cache["link"]
    mode_id = _fc.mode_number(link, name)
    if mode_id is None:
        return {
            "attempted": False,
            "write_completed": False,
            "mode_id": None,
            "error": None,
        }
    fc_connection.drain(cache)
    try:
        link.set_mode(mode_id)
    except Exception as error:
        return {
            "attempted": True,
            "write_completed": None,
            "mode_id": mode_id,
            "error": error,
        }
    return {
        "attempted": True,
        "write_completed": True,
        "mode_id": mode_id,
        "error": None,
    }


def rejected_set_mode(message):
    """True when this frame is a rejection of the mode command.

    IN_PROGRESS is not rejection. None and other frames are not rejection.
    """
    return _fc.ack_verdict(message, SET_MODE) == "REJECTED"


def wait_until(cache, timeout, ready, stop=None, pump=None):
    """Read until ready() is true or the timeout elapses.

    ready() inspects the cache. This does not decide a flight outcome.
    Returns True when ready() is true. Link errors propagate.
    pump() runs after every read, including a read that returns nothing.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        fc_connection.read(cache, min(0.2, max(0.0, remaining)))
        if pump is not None:
            pump()
        if stop is not None and stop():
            return False
        if ready():
            return True
    if stop is not None and stop():
        return False
    return bool(ready())


def rejected_command(message, command):
    """True when this frame rejects that command. IN_PROGRESS is not rejection."""
    return _fc.ack_verdict(message, command) == "REJECTED"


def _recent_rejection(cache, message, command):
    """True when this acknowledgement rejects the command for the current operation."""
    if command is None or message is None:
        return False
    started = cache.get("operation_at")
    ack_at = cache.get("ack_at")
    return (
        started is not None
        and ack_at is not None
        and ack_at >= started
        and rejected_command(message, command)
    )


#sends one MAVlink command to the FC, link, the specific command to the FC, *parameters are the parameters for the command
def send_command(cache, command, *parameters):
    """Write one COMMAND_LONG. Does not wait for an acknowledgement.

    write_completed is None when the write raised and delivery is uncertain.
    """
    link = cache["link"]
    fc_connection.drain(cache)
    try:
        link.mav.command_long_send(
            link.target_system,
            link.target_component,
            command,
            0,
            *parameters,
        )
    except Exception as error:
        return {"attempted": True, "write_completed": None, "error": error}
    return {"attempted": True, "write_completed": True, "error": None}


#link, desired mode, desired armed state, timeout
def wait_for_state(cache, mode, armed, timeout, command=None, stop=None, pump=None):
    """Read until the heartbeat shows this mode and armed flag, or reject.

    Returns "ready", "rejected", "changed", "aborted", or "timeout". Link errors propagate.
    A rejected acknowledgement stops the wait. It is not state confirmation.
    stop() lets the caller end the wait when landing has been requested.
    """
    #making sure its within the timeout
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        message = fc_connection.read(cache, min(0.2, max(0.0, remaining)))
        if pump is not None:
            pump()
        if stop is not None and stop():
            return "aborted"
        #if we dont get a heartbeat, or the message is not a heartbeat, continue
        if message is not None and message.get_type() == "COMMAND_ACK":
            if _recent_rejection(cache, message, command):
                return "rejected"
        if message is None or message.get_type() != "HEARTBEAT":
            continue
        now = time.monotonic()
        shot = status.snapshot(cache, now)
        #check if the drone is armed
        seen_armed = shot["armed"]
        #check if the drone is in the mode we want, and if it is armed
        if shot["mode"] == mode and seen_armed is armed:
            # A rejection or a newer heartbeat can already be buffered behind this one.
            fc_connection.drain(cache)
            now = time.monotonic()
            if _recent_rejection(cache, cache.get("ack"), command):
                return "rejected"
            shot = status.snapshot(cache, now)
            if shot["mode"] == mode and shot["armed"] is armed:
                #return no errors
                return "ready"
            return "changed"
    return "timeout"
