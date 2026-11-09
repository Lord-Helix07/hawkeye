"""Password rules, shared by signup and reset-password.

Keep MIN_LENGTH in sync with the website (frontend/src/services/auth.js).
"""

from fastapi import HTTPException

MIN_LENGTH = 8
# bcrypt only uses the first 72 bytes of a password (newer versions refuse longer ones).
MAX_BYTES = 72


def check_password(password: str) -> None:
    """Raise HTTP 422 if the password breaks a rule."""
    if len(password) < MIN_LENGTH:
        raise HTTPException(status_code=422, detail=f"Password must be at least {MIN_LENGTH} characters")
    if len(password.encode()) > MAX_BYTES:
        raise HTTPException(status_code=422, detail="Password is too long (72 characters max)")
