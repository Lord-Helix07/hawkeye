"""Start the API from the backend folder: uvicorn api:app --reload --port 8000.

The app lives in website/api.py. This file keeps that command, and the Vercel
entrypoint, pointed at the moved module.
"""

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent
for _folder in (_BACKEND, _BACKEND / "website", _BACKEND / "drone"):
    _path = str(_folder)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from website.api import app

__all__ = ["app"]
