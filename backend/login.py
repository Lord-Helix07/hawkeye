from getpass import getpass
import time

import bcrypt
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from users_store import (
    LoginLocked,
    UsersTableSchemaError,
    clear_expired_login_lock,
    get_user,
    record_failed_login,
    reset_login_attempts,
)


router = APIRouter(tags=["users"])


class LoginRequest(BaseModel):
    badge_num: str
    password: str


@router.post("/login") # Handle user login requests
def login(request: LoginRequest):
    badge_num = request.badge_num.strip()
    generic_error = "Invalid badge number or password"

    if not badge_num or not request.password: # Check if badge number or password is missing
        raise HTTPException(status_code=401, detail=generic_error)

    try:
        user = get_user(badge_num) # Retrieve the user by badge number

        if user is None or user.get("status") != "active": # Check if user exists and is active
            raise HTTPException(status_code=401, detail=generic_error)

        now = int(time.time()) 
        locked_until = int(user.get("locked_until", 0)) # Get the lock expiration time
        if locked_until > now: # Check if the account is currently locked
            raise HTTPException(
                status_code=429,
                detail={
                    "message": "Too many failed attempts. Try again later.",
                    "retry_after_seconds": locked_until - now,
                },
            )
        if locked_until: # Clear the lock if it has expired
            clear_expired_login_lock(badge_num)

        password_matches = bcrypt.checkpw( # Verify the provided password against the stored hash
            request.password.encode(),
            user["password_hash"].encode(),
        )

        if not password_matches:
            result = record_failed_login(badge_num)
            if result["locked"]:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "message": "Too many failed attempts. Try again later.",
                        "retry_after_seconds": result["retry_after_seconds"],
                    },
                )

            detail = {"message": generic_error} 
            if result["attempts_remaining"] <= 5:
                detail["attempts_remaining"] = result["attempts_remaining"]
            raise HTTPException(status_code=401, detail=detail)

        reset_login_attempts(badge_num)
        return {"message": "Login successful", "badge_num": badge_num}

    except HTTPException: 
        raise
    except LoginLocked as error:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Too many failed attempts. Try again later.",
                "retry_after_seconds": error.retry_after_seconds,
            },
        ) from error
    except UsersTableSchemaError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(
            status_code=503,
            detail="Could not check the login right now",
        ) from error


if __name__ == "__main__":
    badge_num = input("Badge number: ")
    password = getpass("Password: ")

    from fastapi.testclient import TestClient
    from api import app

    client = TestClient(app)
    response = client.post(
        "/login",
        json={"badge_num": badge_num, "password": password},
    )
    print(response.status_code, response.json())
