"""Mission numbers for the MVP: a short random code like HWK-07-2410.

That code is also the mission_id. The Deploy page shows one, then sends it
back when the officer presses Deploy so the saved mission matches the screen.
"""

import random
import re

MISSION_ID_PATTERN = re.compile(r"^HWK-\d{2}-\d{4}$")


def new_mission_id() -> str:
    """A code like HWK-07-2410."""
    group = random.randint(0, 99)
    number = random.randint(0, 9999)
    return f"HWK-{group:02d}-{number:04d}"


def usable_mission_id(mission_id) -> str | None:
    """The id if it matches HWK-07-2410, otherwise None."""
    if not isinstance(mission_id, str):
        return None
    mission_id = mission_id.strip()
    if MISSION_ID_PATTERN.fullmatch(mission_id):
        return mission_id
    return None
