from getpass import getpass
from datetime import datetime, timedelta, timezone
import os
import time

import bcrypt
import jwt
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from users_store import (
    LoginLocked,
    UsersTableSchemaError,
    clear_expired_login_lock,
    ensure_users_table,
    get_dynamodb_resource,
    record_failed_login,
    reset_login_attempts,
)


router = APIRouter(tags=["users"])
ACCESS_TOKEN_EXPIRE_MINUTES = 60
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "hawkeye-api"
bearer_scheme = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel): #schema for the login 
    badge_num: str
    password: str


class LoginResponse(BaseModel): #schema for the login response
    message: str
    badge_num: str
    access_token: str
    token_type: str
    expires_in: int


def _jwt_secret() -> str: # make sure the JWT secret is properly configured
    """Return the configured signing secret or fail with a server error."""
    secret_key = os.getenv("JWT_SECRET_KEY")
    if not secret_key or len(secret_key) < 32:
        raise HTTPException(
            status_code=503,
            detail="Login is not configured with a valid JWT secret",
        )
    return secret_key


def _create_access_token(badge_num: str, secret_key: str) -> tuple[str, int]: # create the access token for the user
    """Create the bearer token returned after a successful DynamoDB login."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    token = jwt.encode(
        {
            "sub": badge_num,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "iss": JWT_ISSUER,
            "typ": "access",
        },
        secret_key,
        algorithm=JWT_ALGORITHM,
    )
    return token, expires_in


def _get_user_from_dynamodb(badge_num: str) -> dict | None: # lookup the user from DynamoDB
    """Read the login record directly from DynamoDB by badge number."""
    dynamodb = get_dynamodb_resource()
    table = ensure_users_table(dynamodb)
    response = table.get_item(
        Key={"badge_num": badge_num.strip()},
        ConsistentRead=True,
    )
    return response.get("Item")


def get_current_user( # verify the current user from the JWT token
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Verify a bearer JWT and load the current active user from DynamoDB."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer token required")

    try:
        claims = jwt.decode(
            credentials.credentials,
            _jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
        )
    except jwt.ExpiredSignatureError as error:
        raise HTTPException(status_code=401, detail="Access token has expired") from error
    except jwt.InvalidTokenError as error:
        raise HTTPException(status_code=401, detail="Invalid access token") from error

    badge_num = claims.get("sub")
    if (
        not isinstance(badge_num, str)
        or not badge_num
        or claims.get("typ") != "access"
    ):
        raise HTTPException(status_code=401, detail="Invalid access token")

    try:
        user = _get_user_from_dynamodb(badge_num)
    except UsersTableSchemaError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(status_code=503, detail="Could not check the logged-in user") from error

    if user is None or user.get("status") != "active":
        raise HTTPException(status_code=401, detail="User is not active")
    return user


@router.post("/login", response_model=LoginResponse) # Handle user login requests and return an access token
def login(request: LoginRequest): # handle the login process for user
    badge_num = request.badge_num.strip()
    generic_error = "Invalid badge number or password"

    if not badge_num or not request.password: # Check if badge number or password is missing
        raise HTTPException(status_code=401, detail=generic_error)

    secret_key = _jwt_secret()

    try:
        user = _get_user_from_dynamodb(badge_num) # Retrieve the user directly from DynamoDB

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
        access_token, expires_in = _create_access_token(badge_num, secret_key)
        return {
            "message": "Login successful",
            "badge_num": badge_num,
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": expires_in,
        }

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


@router.get("/auth/me")
def current_user(user: dict = Depends(get_current_user)): #api response after get_current_user verification
    """Verify the login token and return the active user without its password hash."""
    return {"badge_num": user["badge_num"], "email": user.get("email")}


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
