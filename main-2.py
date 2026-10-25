
from fastapi import FastAPI # loads the FastAPI framework for building the API
from pydantic import BaseModel 
from database import ( # imports the database functions
    initialize_database, save_telemetry, get_all_telemetry
)
from fastapi.middleware.cors import CORSMiddleware 

app = FastAPI() # creates our the FastAPI application

app.add_middleware( # enables Cross-Origin Resource Sharing
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.on_event("startup") 
def start_server(): #calls the function when the server starts
    initialize_database()

class Telemetry(BaseModel): #telemetry schema
    drone_id: str
    speed: float
    battery: float
    status: str
    mission_id: str

@app.get("/") 
def home(): # disaplay message at startup
    return {
        "message": "HawkEye local server is running"
    }


@app.post("/telemetry") 
def create_telemetry(data: Telemetry): #runs when a POST request is made to the /telemetry endpoint
    save_telemetry(data)
    return {
        "message": "Telemetry saved successfully",
        "telemetry": data
    }

@app.get("/telemetry") 
def read_telemetry(): # runs when a GET request is made to the /telemetry endpoint
    return get_all_telemetry()