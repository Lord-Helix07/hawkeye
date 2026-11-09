"""Status snapshot from the shared cache. This module does not read the link.

Heartbeat mode, arming, and freshness come from heartbeat.py. GPS,
altitude, battery, and landed-state frames come from the cache
fc_connection fills. A fresh heartbeat confirms communication only.
"""

from pymavlink import mavutil

import fc_status as _fc

from flight_controller import heartbeat

fresh = _fc.fresh
ON_GROUND = mavutil.mavlink.MAV_LANDED_STATE_ON_GROUND
PREARM = mavutil.mavlink.MAV_SYS_STATUS_PREARM_CHECK


def snapshot(cache, now):
    """One coherent view. Nothing here is read from the serial port."""
    beat = heartbeat.view(cache["heartbeat"], now)
    extended_at = cache.get("extended_at")
    extended = cache.get("extended")
    extended_fresh = fresh(extended_at, now)
    on_ground = None
    if extended is not None and extended_fresh:
        on_ground = extended.landed_state == ON_GROUND
    gps = cache.get("gps")
    gps_fresh = fresh(cache.get("gps_at"), now)
    gps_fix = getattr(gps, "fix_type", None) if gps is not None and gps_fresh else None
    sys_status = cache.get("sys_status")
    sys_status_fresh = fresh(cache.get("sys_status_at"), now)
    prearm_passed = None
    if sys_status is not None and sys_status_fresh:
        bits = getattr(sys_status, "onboard_control_sensors_health", 0)
        prearm_passed = (bits & PREARM) != 0
    position = cache.get("position")
    position_fresh = fresh(cache.get("position_at"), now)
    relative_altitude_m = None
    if position is not None and position_fresh:
        relative_altitude_m = position.relative_alt / 1000.0
    return {
        "communication_confirmed": beat["fresh"],
        "heartbeat": beat,
        "mode": beat["mode"],
        "armed": beat["armed"],
        "on_ground": on_ground,
        "extended_fresh": extended_fresh,
        "gps_fresh": gps_fresh,
        "gps_fix": gps_fix,
        "position_fresh": position_fresh,
        "relative_altitude_m": relative_altitude_m,
        "battery_fresh": fresh(cache.get("battery_at"), now),
        "sys_status_fresh": sys_status_fresh,
        "prearm_passed": prearm_passed,
    }


def mode_is(cache, name, now):
    """True when the heartbeat tracker has a fresh sample of this mode.

    This does not apply the operation boundary and does not mean the
    aircraft is healthy or landed.
    """
    beat = heartbeat.view(cache["heartbeat"], now)
    return beat["fresh"] and beat["mode"] == name


def touchdown(cache, now):
    """True when disarm and ON_GROUND are both fresh and from this operation.

    Disarm comes from the heartbeat tracker. ON_GROUND comes from
    EXTENDED_SYS_STATE. Arrival order does not matter. Receipt times
    before operation_at were cached before this command and do not count.
    """
    beat = heartbeat.sample(cache["heartbeat"])
    extended = cache.get("extended")
    extended_at = cache.get("extended_at")
    started = cache.get("operation_at")
    if beat["seen_at"] is None or extended is None or started is None:
        return False
    if not fresh(beat["seen_at"], now) or not fresh(extended_at, now):
        return False
    if beat["seen_at"] < started or extended_at < started:
        return False
    boundary = cache.get("command_heartbeat_receipt")
    if boundary is not None and beat.get("receipt", 0) <= boundary:
        return False
    if beat["armed"]:
        return False
    return extended.landed_state == ON_GROUND


def stale_landing_reason(cache, now):
    """Why touchdown cannot be judged, or None when both readings are fresh.

    Fresh here is age only. The operation boundary is touchdown()'s check.
    """
    beat = heartbeat.sample(cache["heartbeat"])
    if not fresh(beat["seen_at"], now):
        return "Landing completion could not be verified: heartbeat missing or stale."
    if not fresh(cache.get("extended_at"), now):
        return "Landing completion could not be verified: landed-state telemetry missing or stale."
    return None


def launch_samples_ready(snapshot):
    """True when heartbeat, GPS, and pre-arm are present and fresh."""
    if not isinstance(snapshot, dict):
        return False
    return bool(
        snapshot.get("communication_confirmed")
        and snapshot.get("gps_fix") is not None
        and snapshot.get("prearm_passed") is not None
        and snapshot.get("gps_fresh")
        and snapshot.get("sys_status_fresh")
    )


def commanded_mode(cache, name, now):
    """True when a fresh heartbeat of this mode was stored after the write.

    command_heartbeat_receipt is the last heartbeat ingested before the
    write returned. An equal timestamp does not qualify. Freshness is
    still required.
    """
    beat = heartbeat.sample(cache["heartbeat"])
    boundary = cache.get("command_heartbeat_receipt")
    if boundary is None or beat.get("seen_at") is None:
        return False
    if beat.get("receipt", 0) <= boundary:
        return False
    if not fresh(beat["seen_at"], now):
        return False
    return beat.get("mode") == name
