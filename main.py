
from fastapi import FastAPI
from pydantic import BaseModel
from database import (
    initialize_database, save_telemetry, get_all_telemetry
)
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.on_event("startup")
def start_server():
    initialize_database()

class Telemetry(BaseModel):
    drone_id: str
    speed: float
    battery: float
    status: str
    mission_id: str

@app.get("/")
def home():
    return {
        "message": "HawkEye local server is running"
    }


@app.post("/telemetry")
def create_telemetry(data: Telemetry):
    save_telemetry(data)
    return {
        "message": "Telemetry saved successfully",
        "telemetry": data
    }

@app.get("/telemetry")
def read_telemetry():
    return get_all_telemetry()