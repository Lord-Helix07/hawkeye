import bcrypt
import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import login


def test_login_returns_jwt_after_successful_authentication(monkeypatch): # verifies password and returns a JWT
    secret = "test-secret-key-with-at-least-32-characters"
    password_hash = bcrypt.hashpw(b"password", bcrypt.gensalt()).decode()
    monkeypatch.setenv("JWT_SECRET_KEY", secret)
    monkeypatch.setattr(
        login,
        "_get_user_from_dynamodb",
        lambda badge_num: {
            "status": "active",
            "password_hash": password_hash,
        },
    )
    monkeypatch.setattr(login, "reset_login_attempts", lambda badge_num: None)

    result = login.login(
        login.LoginRequest(badge_num="  badge-123 ", password="password")
    )

    claims = jwt.decode(result["access_token"], secret, algorithms=["HS256"])
    assert result["badge_num"] == "badge-123"
    assert result["token_type"] == "bearer"
    assert result["expires_in"] == 3600
    assert claims["sub"] == "badge-123"
    assert claims["exp"] > claims["iat"]


def test_login_requires_configured_jwt_secret(monkeypatch): # verifies that login fails if JWT secret is not configured
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setattr(
        login,
        "_get_user_from_dynamodb",
        lambda badge_num: pytest.fail("DynamoDB should not be queried"),
    )

    with pytest.raises(HTTPException) as error:
        login.login(login.LoginRequest(badge_num="badge-123", password="password"))

    assert error.value.status_code == 503


def test_auth_me_verifies_token_and_reads_active_user_from_dynamodb(monkeypatch): # verifies that the token is valid and the user is active in DynamoDB
    secret = "test-secret-key-with-at-least-32-characters"
    monkeypatch.setenv("JWT_SECRET_KEY", secret)
    looked_up_badges = []

    def fake_get_user(badge_num):
        looked_up_badges.append(badge_num)
        return {
            "badge_num": badge_num,
            "email": "pilot@example.com",
            "status": "active",
        }

    monkeypatch.setattr(login, "_get_user_from_dynamodb", fake_get_user)
    token, _ = login._create_access_token("badge-123", secret)

    user = login.get_current_user(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    )

    assert user["badge_num"] == "badge-123"
    assert looked_up_badges == ["badge-123"]
