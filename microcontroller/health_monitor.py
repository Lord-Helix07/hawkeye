"""Detect a critical fault and return a landing request reason.

watch() is the continuous pass. consider_fault_landing() records the first
fault and, when the coordinator supplies start_landing, starts landing
once. This module does not command the flight controller or write the
backend. Numeric limits stay None until a verified value is supplied. A
missing reading does not pass a configured comparison.

No camera, inference, temperature, battery, or link producer in this
repository fills the health snapshot. A dead Pi cannot run this file.
The flight controller still needs its own lost-control failsafe set to
LAND. This file does not write flight-controller parameters.
"""

import time

from flight_controller import fc_status


def fault_limits():
    """Named limits. None means that number has not been supplied.

    A None limit skips that numeric comparison. It is not a guessed
    voltage, temperature, confidence, or timeout. This repository has
    no verified value for any of these fields. component_temp_max_c
    lists only components that actually report temperature.
    """
    return {
        "battery_min_pct": None,
        "battery_min_mv": None,
        "pi_temp_max_c": None,
        "component_temp_max_c": {},
        "undervoltage_now_critical": None,
        "undervoltage_repeat_limit": None,
        "camera_max_age_s": None,
        "inference_max_age_s": None,
        "target_min_confidence": None,
        "target_min_identity": None,
        "control_max_age_s": None,
        "cpu_max_pct": None,
        "ram_max_pct": None,
        "telemetry_max_age_s": None,
        "required_telemetry": (),
        "link_loss_timeout_s": None,
    }


def _number(value):
    """A finite number, or None. Booleans are not sensor readings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value == float("inf") or value == float("-inf"):
        return None
    return value


def _age(source, key, now):
    """Seconds since a producer timestamp, or None when it cannot be used.

    source[key] is the producer's monotonic time, not the time this loop
    noticed the sample. The same old stamp grows older as now moves, so
    copying the snapshot again does not refresh a watchdog.
    """
    if now is None or not isinstance(source, dict):
        return None
    stamp = _number(source.get(key))
    if stamp is None or stamp > now:
        return None
    return now - stamp


def check_for_critical_faults(health, limits):
    """Return a fault reason, or None when no configured critical fault is present.

    health is a snapshot from the application. This function does not
    read sensors. now, camera_frame_at, inference_at, control_at, and
    telemetry sample at values are monotonic producer times.

    Battery status LOW or CRITICAL is a fault. Numeric battery,
    temperature, confidence, age, CPU, and RAM checks run only when that
    limit is set. A missing or invalid reading does not pass a numeric
    comparison. pi_undervoltage_occurred is historical and is ignored.
    CPU or RAM percentage alone is not a fault unless its limit is set.
    A missed control deadline is its own fault.

    Configured component temperatures that are absent are reported
    unavailable. Components without a configured limit are not checked.
    """
    if not isinstance(health, dict) or not isinstance(limits, dict):
        return "Health snapshot or limits are missing."
    fc = health.get("fc_status")
    if isinstance(fc, dict) and fc.get("communication_confirmed") is False:
        # A stale heartbeat means the flight controller is not confirmed
        # to be communicating. It does not by itself prove the aircraft
        # landed. If the link is already dead, ArduPilot's onboard
        # failsafe has to land. This process cannot rely on that command.
        return "Flight controller heartbeat is stale."
    now = _number(health.get("now"))

    status = health.get("battery_status")
    if isinstance(status, str) and status.strip().upper() in ("LOW", "CRITICAL"):
        return f"Flight battery status is {status.strip().upper()}."
    if limits.get("battery_min_pct") is not None:
        pct = _number(health.get("battery_pct"))
        if pct is None:
            return "Flight battery percentage is missing or invalid."
        if pct <= limits["battery_min_pct"]:
            return "Flight battery percentage is at or below the configured limit."
    if limits.get("battery_min_mv") is not None:
        mv = _number(health.get("battery_mv"))
        if mv is None:
            return "Flight battery voltage is missing or invalid."
        if mv <= limits["battery_min_mv"]:
            return "Flight battery voltage is at or below the configured limit."

    if limits.get("pi_temp_max_c") is not None:
        temp = _number(health.get("pi_temp_c"))
        if temp is None:
            return "Pi temperature is missing or invalid."
        if temp > limits["pi_temp_max_c"]:
            return "Pi temperature is above the configured critical limit."
    caps = limits.get("component_temp_max_c") or {}
    if isinstance(caps, dict):
        temps = health.get("component_temp_c")
        for name, limit in caps.items():
            if limit is None:
                continue
            reading = None if not isinstance(temps, dict) else temps.get(name)
            if _number(reading) is None:
                return f"{name} temperature is unavailable."
            if reading > limit:
                return f"{name} temperature is above its configured limit."

    if limits.get("undervoltage_now_critical") is True:
        current = health.get("pi_undervoltage_now")
        if current is True:
            return "Current Pi undervoltage is active."
        # Historical pi_undervoltage_occurred is not this flag.
        if current is not False:
            return "Current Pi undervoltage state is unavailable."
    repeat_limit = limits.get("undervoltage_repeat_limit")
    if repeat_limit is not None:
        count = _number(health.get("pi_undervoltage_count"))
        if count is None:
            return "Pi undervoltage repeat count is missing or invalid."
        if count >= repeat_limit:
            return "Pi undervoltage repeat count met the configured limit."

    if health.get("camera_ok") is False:
        return "Camera failure."
    if health.get("camera_frames_missing") is True:
        return "Camera frames are missing."
    if health.get("camera_frozen") is True:
        return "Camera capture timestamp is frozen."
    camera_limit = limits.get("camera_max_age_s")
    if camera_limit is not None:
        camera_age = _age(health, "camera_frame_at", now)
        if camera_age is None:
            return "Camera frame timestamp is missing or invalid."
        if camera_age > camera_limit:
            return "Camera frame is older than the configured limit."

    if health.get("inference_ok") is False:
        return "Inference failure."
    if health.get("inference_deadline_missed") is True:
        return "Inference deadline missed."
    inference_limit = limits.get("inference_max_age_s")
    if inference_limit is not None:
        inference_age = _age(health, "inference_at", now)
        if inference_age is None:
            return "Inference result timestamp is missing or invalid."
        if inference_age > inference_limit:
            return "Inference result is stale."

    if health.get("target_lost") is True:
        return "Target lost."
    if limits.get("target_min_confidence") is not None:
        confidence = _number(health.get("target_confidence"))
        if confidence is None:
            return "Target confidence is missing or invalid."
        if confidence < limits["target_min_confidence"]:
            return "Target confidence is below the configured limit."
    if limits.get("target_min_identity") is not None:
        identity = _number(health.get("target_identity"))
        if identity is None:
            return "Target identity certainty is missing or invalid."
        if identity < limits["target_min_identity"]:
            return "Target identity certainty is below the configured limit."

    if health.get("controller_ok") is False:
        return "Following controller failure."
    if health.get("controller_command_valid") is False:
        return "Following controller command is invalid."
    if health.get("control_deadline_missed") is True:
        return "Control deadline missed."
    control_limit = limits.get("control_max_age_s")
    if control_limit is not None:
        control_age = _age(health, "control_at", now)
        if control_age is None:
            return "Following control timestamp is missing or invalid."
        if control_age > control_limit:
            return "Following control update is stale."

    # Percentage alone is ignored unless the application set that limit.
    # A missed deadline is handled above and does not need a CPU number.
    if limits.get("cpu_max_pct") is not None:
        cpu = _number(health.get("cpu_pct"))
        if cpu is None:
            return "CPU reading is missing or invalid."
        if cpu > limits["cpu_max_pct"]:
            return "CPU usage is above the configured critical limit."
    if limits.get("ram_max_pct") is not None:
        ram = _number(health.get("ram_pct"))
        if ram is None:
            return "Memory reading is missing or invalid."
        if ram > limits["ram_max_pct"]:
            return "Memory usage is above the configured critical limit."

    if health.get("telemetry_ok") is False:
        return "Required telemetry is missing."
    required = limits.get("required_telemetry") or ()
    telemetry_limit = limits.get("telemetry_max_age_s")
    if required:
        samples = health.get("telemetry")
        if not isinstance(samples, dict):
            return "Required telemetry is missing."
        for name in required:
            sample = samples.get(name)
            if not isinstance(sample, dict) or sample.get("value") is None:
                return f"Required telemetry {name} is missing."
            if telemetry_limit is not None:
                sample_age = _age(sample, "at", now)
                if sample_age is None:
                    return f"Required telemetry {name} is missing."
                if sample_age > telemetry_limit:
                    return f"Required telemetry {name} is stale."
    elif telemetry_limit is not None:
        telemetry_age = _age(health, "telemetry_at", now)
        if telemetry_age is None:
            return "Required telemetry is missing."
        if telemetry_age > telemetry_limit:
            return "Required telemetry is stale."

    link_timeout = limits.get("link_loss_timeout_s")
    if link_timeout is not None:
        link_ok = health.get("link_ok")
        down_since = health.get("link_down_since")
        if link_ok is True and down_since is None:
            pass
        elif link_ok is False or down_since is not None:
            down_for = _age(health, "link_down_since", now)
            if down_for is None:
                return "Modem, Wi-Fi, or backend link state is unavailable."
            if down_for > link_timeout:
                return "Modem, Wi-Fi, or backend link has exceeded the configured timeout."
        else:
            return "Modem, Wi-Fi, or backend link state is unavailable."
    return None


#check if the drone is ready to launch, return a list of reasons why it is NOT ready
def launch_readiness(status):
    """Reasons the shared status is not ready to launch. Empty means ready.

    status is a flight_controller snapshot. This does not read MAVLink,
    arm, or command takeoff. A fresh heartbeat is not itself readiness.
    """
    reasons = []
    #hella ifs
    if not isinstance(status, dict) or not status.get("communication_confirmed"):
        reasons.append("Heartbeat missing or stale")
    elif status.get("armed"):
        reasons.append("Flight controller is already armed")
    gps_fix = None if not isinstance(status, dict) else status.get("gps_fix")
    if gps_fix is None:
        reasons.append("GPS telemetry missing or stale")
    elif gps_fix < 3:
        reasons.append("GPS fix is not 3D")
    prearm = None if not isinstance(status, dict) else status.get("prearm_passed")
    if prearm is None:
        reasons.append("Pre-arm status missing or stale")
    elif not prearm:
        reasons.append("Pre-arm checks have not passed")
    return reasons


def landing_request(health, limits=None):
    """Return the fault reason main should land for, or None.

    None limits use fault_limits(), whose numbers are unset. That does
    not by itself request landing. Boolean fault flags still do.
    """
    if limits is None:
        limits = fault_limits()
    return check_for_critical_faults(health, limits)


def _mark_abort(flight):
    flight["abort_launch"] = True
    cache = flight.get("cache") if isinstance(flight, dict) else None
    if isinstance(cache, dict):
        cache["abort_launch"] = True


def consider_fault_landing(flight, health, limits=None, start_landing=None):
    """Start or record landing for the first critical fault.

    start_landing(reason) runs the landing sequence. Without it, the fault
    is stored on the flight and launch is asked to stop. A landing that has
    already started, or a fault already stored, does not start another one.
    """
    if not isinstance(flight, dict) or flight.get("landing_started"):
        return None
    pending = flight.get("pending_trigger")
    if flight.get("pending_landing") and isinstance(pending, str) and pending:
        reason = pending
    elif not isinstance(health, dict):
        return None
    else:
        reason = landing_request(health, limits)
        if not reason:
            return None
        flight["pending_landing"] = True
        flight["pending_trigger"] = reason
    _mark_abort(flight)
    if start_landing is None:
        return reason
    return start_landing(reason)


def watch(flight, cache, limits=None, health_provider=None, landing_requested=False, monitor_link=False):
    """One monitoring pass over the latest health and an optional landing row.

    Link faults are included only after a launch command has started or the
    aircraft is following. Before that, a missing heartbeat stays a launch
    readiness failure. This does not run the landing sequence.
    """
    if not isinstance(flight, dict) or flight.get("landing_started") or flight.get("pending_landing"):
        return None
    now = time.monotonic()
    health = {"now": now}
    if health_provider is not None:
        try:
            supplied = health_provider()
        except Exception:
            supplied = None
        if isinstance(supplied, dict):
            health.update(supplied)
            health.setdefault("now", now)
    if monitor_link and isinstance(cache, dict):
        health["fc_status"] = fc_status.snapshot(cache, now)
    reason = consider_fault_landing(flight, health, limits)
    if not flight.get("pending_landing") and landing_requested:
        flight["pending_landing"] = True
        flight["pending_trigger"] = None
        flight["abort_launch"] = True
        reason = None
    if flight.get("pending_landing") and isinstance(cache, dict):
        cache["abort_launch"] = True
        flight["abort_launch"] = True
        if flight.get("cache") is None:
            flight["cache"] = cache
    return reason
