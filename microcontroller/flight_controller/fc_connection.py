"""The shared flight-controller connection and its one MAVLink reader.

open_link() and close_link() own the port. read() and drain() are the
only recv_match calls. An optional cache tick runs after a stored frame
so health monitoring can see telemetry during a blocking sequence.
HEARTBEAT frames are handed to heartbeat.py. This module does not decide
flight mode, arming, or landing.
"""

import time

from flight_controller import fc_config
from flight_controller import heartbeat


def open_link(address=None, baud=None):
    """Open the configured link and return its cache. The caller closes it."""
    from pymavlink import mavutil

    if address is None:
        address = fc_config.FC_PORT
    if baud is None:
        baud = fc_config.BAUD_RATE
    link = mavutil.mavlink_connection(address, baud=baud)
    return cache_for(link)


def close_link(cache):
    #finally, close the link
    if cache is None:
        return None
    link = cache.get("link")
    if link is None:
        return None
    try:
        link.close()
    except Exception as error:
        return str(error)
    return None


def cache_for(link):
    """Cache of the latest frames from this link.

    link is the connection the caller already owns. target_system, when
    the link has one, drops frames from any other flight controller.
    """
    if link is None:
        raise ValueError("Flight controller link is not connected.")
    return {
        "link": link,
        "target_system": getattr(link, "target_system", None),
        "heartbeat": heartbeat.new_tracker(),
        "extended": None,
        "extended_at": None,
        "gps": None,
        "gps_at": None,
        "position": None,
        "position_at": None,
        "sys_status": None,
        "sys_status_at": None,
        "battery": None,
        "battery_at": None,
        "ack": None,
        "ack_at": None,
        "operation_at": None,
    }


def mark_operation(cache):
    """Start the boundary for this command.

    Samples already in the cache keep their receipt times. A later check
    can ignore them because those times are before this mark. Samples
    read after the mark, including during mode confirmation, stay valid.
    A command acknowledgement from before the mark is dropped.
    """
    tracker = cache.get("heartbeat")
    receipt = tracker.get("receipt", 0) if isinstance(tracker, dict) else 0
    # Heartbeats stored up to this count were ingested before the write.
    cache["command_heartbeat_receipt"] = receipt
    cache["operation_at"] = time.monotonic()
    cache["ack"] = None
    cache["ack_at"] = None


def _from_target(cache, message):
    target = cache.get("target_system")
    get_src = getattr(message, "get_srcSystem", None)
    if target is None or not callable(get_src):
        return True
    system = get_src()
    if system in (None, 0):
        return True
    return system == target


def _store(cache, message, now):
    kind = message.get_type()
    if kind == "HEARTBEAT":
        #set the heartbeat and the time it was seen
        heartbeat.observe(cache["heartbeat"], message, now)
    elif kind == "EXTENDED_SYS_STATE":
        cache["extended"] = message
        cache["extended_at"] = now
    elif kind == "GPS_RAW_INT":
        #set the GPS and the time it was seen
        cache["gps"] = message
        cache["gps_at"] = now
    elif kind == "GLOBAL_POSITION_INT":
        cache["position"] = message
        cache["position_at"] = now
    elif kind == "SYS_STATUS":
        #set the status and the time it was seen
        cache["sys_status"] = message
        cache["sys_status_at"] = now
    elif kind == "BATTERY_STATUS":
        cache["battery"] = message
        cache["battery_at"] = now
    elif kind == "COMMAND_ACK":
        cache["ack"] = message
        cache["ack_at"] = now


def _recv(cache, blocking, timeout):
    """The only place this package reads MAVLink."""
    return cache["link"].recv_match(blocking=blocking, timeout=timeout)


def read(cache, timeout):
    """Store the next frame from the target flight controller.

    BAD_DATA and other-system frames are consumed and do not end the wait.
    None means the timeout elapsed. Link errors propagate.
    """
    if timeout < 0:
        timeout = 0
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining < 0:
            return None
        message = _recv(cache, True, min(0.2, remaining))
        now = time.monotonic()
        if message is None or message.get_type() == "BAD_DATA" or not _from_target(cache, message):
            if now >= deadline:
                return None
            continue
        _store(cache, message, now)
        tick = cache.get("tick")
        if tick is not None:
            tick(cache)
        return message


def drain(cache, window=None):
    """Discard frames already buffered before a new command.

    None from the link ends the drain. BAD_DATA does not. An old
    acknowledgement must not stay in the buffer ahead of the new command.
    """
    if window is None:
        window = fc_config.DRAIN_WINDOW
    deadline = time.monotonic() + window
    while time.monotonic() < deadline:
        message = _recv(cache, False, 0)
        if message is None:
            break
        if message.get_type() == "BAD_DATA" or not _from_target(cache, message):
            continue
        _store(cache, message, time.monotonic())
