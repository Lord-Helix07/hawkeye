from getpass import getpass
import uuid
import bcrypt
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from users_store import BadgeNumTaken, UsersTableSchemaError, create_user

# The sign-up routes. They're plugged into the one backend app in api.py
# (start it with: uvicorn api:app --reload --port 8000).
router = APIRouter(tags=["users"])

# Stand-in database until AWS works. Maps user_id -> user info.
# fake_users = {}


class SignUpRequest(BaseModel):
    badge_num: str
    password: str


@router.post("/signup", status_code=201)
def signup(request: SignUpRequest):
    # check for duplicates
    # for user in fake_users.values():
    #     if user["username"] == request.username or user["email"] == request.email:
    #         raise HTTPException(status_code=409, detail="Username or email already taken")

    # generate a unique user id
    #user_id = str(uuid.uuid4())

    # hash password
    password_hash = bcrypt.hashpw(request.password.encode(), bcrypt.gensalt()).decode()

    # save the new user
    # fake_users[user_id] = {
    #     "user_id": user_id,
    #     "username": request.username,
    #     "email": request.email,
    #     "password_hash": password_hash,
    # }

    try:
        create_user(
            badge_num=request.badge_num,
            password_hash=password_hash,
        )
    except BadgeNumTaken:
        raise HTTPException(status_code=409, detail="Badge number already registered")
    except UsersTableSchemaError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(status_code=503, detail="Could not save the user") from error
    # send back user without password hash
    return { "badge_num": request.badge_num }


if __name__ == "__main__":
    badge_num = input("Badge number: ")
    password = getpass("Password: ")

    from fastapi.testclient import TestClient
    from api import app

    client = TestClient(app)
    response = client.post(
        "/signup",
        json={"badge_num": badge_num, "password": password},
    )

    if response.status_code == 201:
        print("User created!")
        print(response.json())
    else:
        print("Error", response.status_code, ":", response.json()["detail"])
