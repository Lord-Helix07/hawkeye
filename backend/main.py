import logging #records events and errors in the application
from pathlib import Path 
from typing import Annotated # a tool for validating types 

from botocore.exceptions import BotoCoreError, ClientError # Error types used to handle DynamoDB and AWS SDK failures.
from fastapi import Depends, FastAPI, Request # core FastAPI components for building hawkEye API
from fastapi.responses import FileResponse, JSONResponse # return with HTTP responses
from pydantic import BaseModel, ConfigDict, StringConstraintsok #Define models and validation rules for the API
from database import AssignmentError, AssignmentStore, local_client # Database-related classes and functions 

app = FastAPI(title='HawkEye Assign Drone — Local Starter') # creates api application


def get_store():
    return AssignmentStore(local_client()) # client gets passed to database helper


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] #rules for string

class AssignmentRequest(BaseModel): #request schema
    model_config = ConfigDict(extra='forbid')
    mission_id: Identifier


@app.exception_handler(AssignmentError) # handles AssignmentError exceptions into JSON responses
async def assignment_error(request: Request, error: AssignmentError):
    return JSONResponse(status_code=error.status, content={'detail': str(error)})


async def database_error(request: Request, error: Exception): # handles database-related exceptions into JSON responses
    logging.getLogger(__name__).error('Database request failed: %s', error)
    return JSONResponse(status_code=503, content={'detail':
        'Database operation could not be confirmed. Check DynamoDB Local and run setup_db.py. Refresh before retrying; a write may already have committed.'})


app.add_exception_handler(BotoCoreError, database_error) #log BotoCoreError exceptions
app.add_exception_handler(ClientError, database_error) #log ClientError exceptions

@app.get('/missions') #GET all missions and return
def missions(store: AssignmentStore = Depends(get_store)):
    return store.list_items(store.missions)


@app.get('/drones') #GET all drones and return
def drones(store: AssignmentStore = Depends(get_store)):
    return store.list_items(store.drones)


@app.post('/assignments') #assign a drone to a mission
def assign_drone(data: AssignmentRequest, store: AssignmentStore = Depends(get_store)):
    return store.assign(data.mission_id)
