from getpass import getpass
import re
import uuid
import bcrypt
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from users_store import BadgeNumTaken, EmailTaken, UsersTableSchemaError, create_user

# The sign-up routes. They're plugged into the one backend app in api.py
# (start it with: uvicorn api:app --reload --port 8000).
router = APIRouter(tags=["users"])

# Stand-in database until AWS works. Maps user_id -> user info.
# fake_users = {}


class SignUpRequest(BaseModel): #Schema
    badge_num: str
    password: str
    email: str
    confirm_email: str


@router.post("/signup", status_code=201)
def signup(request: SignUpRequest): #frontend handler for sign-up
    badge_num = request.badge_num.strip()
    email = request.email.strip().lower()
    confirm_email = request.confirm_email.strip().lower()

    if not badge_num:
        raise HTTPException(status_code=422, detail="Badge number is required")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if email != confirm_email:
        raise HTTPException(status_code=422, detail="Email addresses do not match")

    # check for duplicates
    # if user["username"] == request.username or user["email"] == request.email:
    

    # generate a unique user id
    #user_id = str(uuid.uuid4())

    # hash password
    password_hash = bcrypt.hashpw(request.password.encode(), bcrypt.gensalt()).decode()

    try:
        create_user(
            badge_num=badge_num,
            password_hash=password_hash,
            email=email,
        )
    except BadgeNumTaken:
        raise HTTPException(status_code=409, detail="Badge number already registered")
    except EmailTaken:
        raise HTTPException(status_code=409, detail="Email address already registered")
    except UsersTableSchemaError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(status_code=503, detail=f"Could not save the user: {error}") from error
    # send back user without password hash
    return {"badge_num": badge_num, "email": email}


if __name__ == "__main__": #manual test script for sign-up
    badge_num = input("Badge number: ")
    password = getpass("Password: ")
    email = input("Email: ")
    confirm_email = input("Confirm email: ")

    from fastapi.testclient import TestClient
    from api import app

    client = TestClient(app)
    response = client.post(
        "/signup",
        json={
            "badge_num": badge_num,
            "password": password,
            "email": email,
            "confirm_email": confirm_email,
        },
    )

    if response.status_code == 201:
        print("User created!")
        print(response.json())
    else:
        print("Error", response.status_code, ":", response.json()["detail"])
