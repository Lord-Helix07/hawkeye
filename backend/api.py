"""
Hawkeye backend: the ONE FastAPI app the frontend talks to.

Each feature keeps its routes in its own file (as an APIRouter) and gets
plugged in here, so everything runs on a single server at port 8000.

Start it (from the backend folder):
    uvicorn api:app --reload --port 8000

Then open http://localhost:8000/docs to see and try every route.

Website routes live in website/. Drone routes live in drone/.
Adding a new feature (e.g. login):
    1. In your file:   router = APIRouter()   and   @router.post("/login")
    2. Here:           from login import router as login_router
                       app.include_router(login_router)
"""

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# website/ and drone/ keep flat imports (from login import ..., from launch import ...).
_BACKEND_DIR = Path(__file__).resolve().parent
for _group in ("website", "drone"):
    _folder = str(_BACKEND_DIR / _group)
    if _folder not in sys.path:
        sys.path.insert(0, _folder)

from signup import router as signup_router
from view_mission_status import router as missions_router
from login import router as login_router
from password_reset import router as password_reset_router
from launch import router as launch_router
from telemetry import router as telemetry_router
from mission_status import router as mission_status_router

app = FastAPI(title="Hawkeye API")

# Allow the React frontend (Vite dev server) to call this API from the browser.
# This is set ONCE here for every route.
app.add_middleware(
    CORSMiddleware,
    # Allowed sites:
    #   - any localhost port (Vite moves to 5174, 5175... when 5173 is busy)
    #   - the live site: https://fly-hawkeye.com and https://www.fly-hawkeye.com
    allow_origin_regex=(
        r"http://(localhost|127\.0\.0\.1):\d+"
        r"|https://(www\.)?fly-hawkeye\.com"
    ),
    allow_methods=["*"],
    allow_headers=["*"],
)


class StripApiPrefix:
    """On Vercel, requests arrive as /api/login, /api/missions/... (vercel.json
    sends /api/* to this backend without removing the prefix). Our routes are
    /login, /missions/..., so drop the leading /api. Local dev without the
    prefix keeps working unchanged."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope["path"]
            if path == "/api" or path.startswith("/api/"):
                new_path = path[4:] or "/"
                scope = dict(scope, path=new_path, raw_path=new_path.encode())
        await self.app(scope, receive, send)


app.add_middleware(StripApiPrefix)

app.include_router(signup_router)  # POST /signup
app.include_router(missions_router)  # /missions/...
app.include_router(login_router)   # POST /login
app.include_router(password_reset_router)  # POST /forgot-password, /reset-password
app.include_router(mission_status_router)  # GET /missions/{id}/status (Dashboard)
app.include_router(launch_router)  # POST /missions/{id}/launch, confirm-launch, request-landing
app.include_router(telemetry_router)  # POST /telemetry, /flight-controller/status (Raspberry Pi)


@app.get("/server-status")
def server_status():
    """Quick check that the backend is running: http://localhost:8000/server-status"""
    return {"status": "running"}
