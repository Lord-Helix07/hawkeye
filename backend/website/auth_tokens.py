"""
Login tokens: proof that a request comes from a logged-in officer.

POST /login returns a signed token (a JWT). The website sends it back on every
request as   Authorization: Bearer <token>   and the officer-only routes check
it with the require_officer dependency (wired up in api.py).

Set AUTH_SECRET on the server (any long random string, e.g. the output of
`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Every server
instance must share the same value, or tokens made by one won't work on another.
Without it -- e.g. local dev -- a random secret is made at startup, so
restarting the backend logs everyone out.
"""

import logging
import os
import secrets
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

TOKEN_TTL_SECONDS = 12 * 60 * 60  # matches the website's 12-hour login
ALGORITHM = "HS256"

_dev_secret = None


def _secret() -> str:
    global _dev_secret
    secret = os.getenv("AUTH_SECRET")
    if secret:
        return secret
    if _dev_secret is None:
        logger.warning("AUTH_SECRET not set; using a random secret (logins reset on restart)")
        _dev_secret = secrets.token_urlsafe(48)
    return _dev_secret


def create_token(badge_num: str, now: int | None = None) -> str:
    """Make a login token for this officer, valid for TOKEN_TTL_SECONDS."""
    now = int(time.time()) if now is None else now
    claims = {"sub": badge_num, "iat": now, "exp": now + TOKEN_TTL_SECONDS}
    return jwt.encode(claims, _secret(), algorithm=ALGORITHM)


def badge_from_token(token: str) -> str:
    """Return the badge number in a valid token. Raises HTTP 401 otherwise."""
    try:
        claims = jwt.decode(token, _secret(), algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError as error:
        raise HTTPException(status_code=401, detail="Your login expired. Log in again.") from error
    except jwt.InvalidTokenError as error:
        raise HTTPException(status_code=401, detail="Log in to continue.") from error
    return claims["sub"]


_bearer = HTTPBearer(auto_error=False)


def require_officer(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """FastAPI dependency: the request must carry a valid login token."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Log in to continue.")
    return badge_from_token(credentials.credentials)
