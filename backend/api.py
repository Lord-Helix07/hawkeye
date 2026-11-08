"""
Hawkeye backend: the ONE FastAPI app the frontend talks to.

Each feature keeps its routes in its own file (as an APIRouter) and gets
plugged in here, so everything runs on a single server at port 8000.

Start it (from the backend folder):
    uvicorn api:app --reload --port 8000

Then open http://localhost:8000/docs to see and try every route.

Adding a new feature (e.g. login):
    1. In your file:   router = APIRouter()   and   @router.post("/login")
    2. Here:           from login import router as login_router
                       app.include_router(login_router)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from signup import router as signup_router
from view_mission_status import router as missions_router
from login import router as login_router
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
    #   - Amplify's preview URLs (https://<branch>.<id>.amplifyapp.com)
    allow_origin_regex=(
        r"http://(localhost|127\.0\.0\.1):\d+"
        r"|https://(www\.)?fly-hawkeye\.com"
        r"|https://[a-z0-9.-]+\.amplifyapp\.com"
    ),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(signup_router)  # POST /signup
app.include_router(missions_router)  # /missions/...
app.include_router(login_router)   # POST /login
app.include_router(mission_status_router)  # GET /missions/{id}/status (Dashboard)
app.include_router(launch_router)  # POST /missions/{id}/launch, confirm-launch, request-landing
app.include_router(telemetry_router)  # POST /telemetry, /flight-controller/status (Raspberry Pi)


@app.get("/server-status")
def server_status():
    """Quick check that the backend is running: http://localhost:8000/server-status"""
    return {"status": "running"}
