"""Latest flight-controller heartbeat. This file does not read MAVLink.

fc_connection updates the tracker when it receives a HEARTBEAT. A fresh
heartbeat means ArduPilot has communicated recently. It does not mean the
aircraft is healthy, safe to launch, or on the ground.

The tracked fields are the receipt time, flight mode, armed flag, and the
flight controller's system status. receipt counts stored heartbeats and
stays on the sample when two heartbeats share a timestamp.
"""

import fc_status as _fc


def new_tracker():
    """Empty tracker. seen_at stays None until a heartbeat is observed."""
    return {
        "message": None,
        "seen_at": None,
        "mode": None,
        "armed": None,
        "system_status": None,
        "receipt": 0,
    }


def observe(tracker, message, now):
    """Record one HEARTBEAT. now is the monotonic time it was received."""
    tracker["message"] = message
    tracker["seen_at"] = now
    tracker["receipt"] = tracker.get("receipt", 0) + 1
    tracker["mode"] = _fc.mode_name(message)
    tracker["armed"] = _fc.armed(message)
    tracker["system_status"] = getattr(message, "system_status", None)


def sample(tracker):
    """Latest observed values, including a heartbeat that is no longer fresh."""
    return {
        "message": tracker.get("message"),
        "seen_at": tracker.get("seen_at"),
        "mode": tracker.get("mode"),
        "armed": tracker.get("armed"),
        "system_status": tracker.get("system_status"),
        "receipt": tracker.get("receipt", 0),
    }


def view(tracker, now):
    """Current heartbeat view. Mode and armed are present only while fresh.

    stale is true when no heartbeat has arrived or the last one is older
    than the shared freshness window. last_mode and last_armed keep the
    most recent observation for an emergency decision after it goes stale.
    """
    latest = sample(tracker)
    is_fresh = _fc.fresh(latest["seen_at"], now)
    latest["fresh"] = is_fresh
    latest["stale"] = not is_fresh
    latest["last_mode"] = latest["mode"]
    latest["last_armed"] = latest["armed"]
    if not is_fresh:
        latest["mode"] = None
        latest["armed"] = None
        latest["system_status"] = None
    return latest
