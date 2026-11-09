"""Signup, login (badge + password) and forgot/reset password, against a fake DynamoDB (moto)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

moto = pytest.importorskip("moto")


@pytest.fixture
def client(monkeypatch):
    for name, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("DYNAMODB_ENDPOINT_URL", raising=False)

    with moto.mock_aws():
        from fastapi.testclient import TestClient

        import password_reset
        from api import app

        sent = []
        monkeypatch.setattr(
            password_reset,
            "send_reset_email",
            lambda email, badge, link: sent.append((email, badge, link)),
        )
        test_client = TestClient(app)
        test_client.sent_emails = sent
        yield test_client


def signup(client, badge="1234", email="officer@example.com", password="hunter22"):
    return client.post(
        "/signup",
        json={"badge_num": badge, "email": email, "confirm_email": email, "password": password},
    )


def login(client, badge="1234", password="hunter22"):
    return client.post("/login", json={"badge_num": badge, "password": password})


def token_from(link):
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(link).query)
    return query["badge"][0], query["token"][0]


def test_login_with_badge_and_password(client):
    assert signup(client).status_code == 201
    assert login(client).status_code == 200
    assert login(client, password="wrong").status_code == 401
    assert login(client, badge="9999").status_code == 401


def test_login_token_unlocks_mission_routes(client):
    signup(client)
    body = login(client).json()
    assert body["badge_num"] == "1234" and body["token"]

    # no token, a junk token, and a different scheme are all turned away
    assert client.get("/missions/next-number").status_code == 401
    assert client.get("/missions/next-number", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert client.post("/missions/0001/request-landing", headers={"Authorization": f"Basic {body['token']}"}).status_code == 401

    # the token from /login gets through (mission 0001 doesn't exist, so 404, not 401)
    auth = {"Authorization": f"Bearer {body['token']}"}
    assert client.get("/missions/next-number", headers=auth).status_code == 200
    assert client.get("/missions/0001/status", headers=auth).status_code == 404


def test_expired_or_forged_token_is_rejected(client, monkeypatch):
    import time

    import auth_tokens

    old = auth_tokens.create_token("1234", now=int(time.time()) - auth_tokens.TOKEN_TTL_SECONDS - 60)
    response = client.get("/missions/next-number", headers={"Authorization": f"Bearer {old}"})
    assert response.status_code == 401
    assert "expired" in response.json()["detail"]

    monkeypatch.setenv("AUTH_SECRET", "someone-elses-secret")
    forged = auth_tokens.create_token("1234")
    monkeypatch.setenv("AUTH_SECRET", "the-real-secret")
    assert client.get("/missions/next-number", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_drone_telemetry_needs_no_login(client):
    # the Raspberry Pi has no officer login, so its routes must stay open (422 = reached the route)
    assert client.post("/telemetry", json={}).status_code != 401
    assert client.post("/flight-controller/status", json={}).status_code != 401


def test_forgot_password_unknown_email_looks_the_same(client):
    signup(client)
    known = client.post("/forgot-password", json={"email": "officer@example.com"})
    unknown = client.post("/forgot-password", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert len(client.sent_emails) == 1


def test_reset_password_flow(client):
    signup(client)
    client.post("/forgot-password", json={"email": "officer@example.com"})
    email, badge, link = client.sent_emails[0]
    assert email == "officer@example.com"
    link_badge, token = token_from(link)
    assert link_badge == badge == "1234"

    bad = client.post("/reset-password", json={"badge_num": "1234", "token": "nope", "new_password": "x"})
    assert bad.status_code == 400

    ok = client.post("/reset-password", json={"badge_num": "1234", "token": token, "new_password": "newpass1"})
    assert ok.status_code == 200
    assert login(client).status_code == 401
    assert login(client, password="newpass1").status_code == 200

    # single use
    again = client.post("/reset-password", json={"badge_num": "1234", "token": token, "new_password": "other"})
    assert again.status_code == 400


def test_reset_token_expires(client, monkeypatch):
    import password_reset

    signup(client)
    monkeypatch.setattr(password_reset, "RESET_TOKEN_TTL_SECONDS", -1)
    client.post("/forgot-password", json={"email": "officer@example.com"})
    _, token = token_from(client.sent_emails[0][2])
    response = client.post("/reset-password", json={"badge_num": "1234", "token": token, "new_password": "x"})
    assert response.status_code == 400


def test_forgot_password_cooldown(client):
    signup(client)
    client.post("/forgot-password", json={"email": "officer@example.com"})
    client.post("/forgot-password", json={"email": "officer@example.com"})
    assert len(client.sent_emails) == 1


def test_reset_email_is_sent_through_ses(monkeypatch):
    """With SES_SENDER_EMAIL set, the real send path delivers through SES (faked by moto)."""
    import boto3

    for name, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
        "SES_SENDER_EMAIL": "noreply@fly-hawkeye.com",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("SES_REGION", raising=False)

    with moto.mock_aws():
        import password_reset

        ses = boto3.client("ses", region_name="us-east-1")
        ses.verify_email_identity(EmailAddress="noreply@fly-hawkeye.com")
        password_reset.send_reset_email(
            "officer@example.com", "1234", "https://fly-hawkeye.com/reset-password?badge=1234&token=abc"
        )
        assert int(ses.get_send_quota()["SentLast24Hours"]) == 1


def test_reset_email_escapes_link():
    import password_reset

    subject, text, html_body = password_reset.build_reset_email("12<34", "https://x.test/r?a=1&b=2")
    assert "https://x.test/r?a=1&b=2" in text
    assert "a=1&amp;b=2" in html_body
    assert "12&lt;34" in html_body
