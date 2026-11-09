"""Existing flight-controller settings from the root fc_status module.

Each lookup reads the current value, so tests can patch fc_status.
Landing timeouts are not flight-controller settings and stay with landing.
"""

import fc_status as _fc

_NAMES = (
    "FC_PORT",
    "BAUD_RATE",
    "HEARTBEAT_TIMEOUT",
    "FRESH_SECONDS",
    "DRAIN_WINDOW",
    "MOCK_MODE",
)


def __getattr__(name):
    if name in _NAMES:
        return getattr(_fc, name)
    raise AttributeError(name)
