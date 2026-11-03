from getpass import getpass
import uuid
import bcrypt
from datetime import datetime, timezone
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from users_store import UsernameOrEmailTaken, UsersTableSchemaError, create_user

app = FastAPI()

# Stand-in database until AWS works. Maps user_id -> user info.
# fake_users = {}


class SignUpRequest(BaseModel):
    badge_num: str
    username: str
    password: str
    name: str
    officer_unit: str


@app.post("/signup", status_code=201)
def signup(request: SignUpRequest):
    # check for duplicates
    # for user in fake_users.values():
    #     if user["username"] == request.username or user["email"] == request.email:
    #         raise HTTPException(status_code=409, detail="Username or email already taken")

    # generate a unique user id
    user_id = "usr-" + str(uuid.uuid4())[:8]

    # hash password
    password_hash = bcrypt.hashpw(request.password.encode(), bcrypt.gensalt()).decode()
    role = "operator"
    status = "active"
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # save the new user
    # fake_users[user_id] = {
    #     "user_id": user_id,
    #     "username": request.username,
    #     "email": request.email,
    #     "password_hash": password_hash,
    # }
    
    try:
        create_user(
            user_id=user_id,
            username=request.username,
            email=request.email,
            password_hash=password_hash,
        )
    except UsernameOrEmailTaken:
        raise HTTPException(status_code=409, detail="Username or email already taken")
    except UsersTableSchemaError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(status_code=503, detail="Could not save the user") from error

    # send back user without password hash
    return {"user_id": user_id, "username": request.username, "email": request.email}


if __name__ == "__main__":
    username = input("Username: ")
    email = input("Email: ")
    password = getpass("Password: ")

    client = TestClient(app)
    response = client.post(
        "/signup",
        json={"username": username, "email": email, "password": password},
    )

    if response.status_code == 201:
        print("User created!")
        print(response.json())
    else:
        print("Error", response.status_code, ":", response.json()["detail"])
