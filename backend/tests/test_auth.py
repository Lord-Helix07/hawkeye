"""Signup, login (badge + password) and forgot/reset password, against a fake DynamoDB (moto)."""

import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _BACKEND)
sys.path.insert(0, os.path.join(_BACKEND, "website"))
sys.path.insert(0, os.path.join(_BACKEND, "drone"))

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


def approve(badge="1234"):
    from users_store import add_approved_badge

    add_approved_badge(badge)


def signup(client, badge="1234", email="officer@example.com", password="hunter22", approved=True):
    if approved:
        approve(badge)
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

    bad = client.post("/reset-password", json={"badge_num": "1234", "token": "nope", "new_password": "newpass1"})
    assert bad.status_code == 400

    ok = client.post("/reset-password", json={"badge_num": "1234", "token": token, "new_password": "newpass1"})
    assert ok.status_code == 200
    assert login(client).status_code == 401
    assert login(client, password="newpass1").status_code == 200

    # single use
    again = client.post("/reset-password", json={"badge_num": "1234", "token": token, "new_password": "otherpass1"})
    assert again.status_code == 400


def test_reset_token_expires(client, monkeypatch):
    import password_reset

    signup(client)
    monkeypatch.setattr(password_reset, "RESET_TOKEN_TTL_SECONDS", -1)
    client.post("/forgot-password", json={"email": "officer@example.com"})
    _, token = token_from(client.sent_emails[0][2])
    response = client.post("/reset-password", json={"badge_num": "1234", "token": token, "new_password": "newpass1"})
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


def test_signup_rejects_short_or_too_long_password(client):
    assert signup(client, password="").status_code == 422
    assert signup(client, password="short12").status_code == 422  # 7 characters
    assert signup(client, password="x" * 73).status_code == 422  # over bcrypt's 72 bytes
    assert signup(client, password="exactly8").status_code == 201


def test_reset_password_rejects_short_password(client):
    signup(client)
    client.post("/forgot-password", json={"email": "officer@example.com"})
    _, _, link = client.sent_emails[0]
    _, token = token_from(link)

    short = client.post("/reset-password", json={"badge_num": "1234", "token": token, "new_password": "short"})
    assert short.status_code == 422
    # the token wasn't used up by the rejected attempt
    ok = client.post("/reset-password", json={"badge_num": "1234", "token": token, "new_password": "newpass1"})
    assert ok.status_code == 200


NOT_APPROVED = "isn't valid"


def test_signup_needs_an_approved_badge(client):
    response = signup(client, approved=False)
    assert response.status_code == 403
    assert NOT_APPROVED in response.json()["detail"]
    assert login(client).status_code == 401  # no account was made


def test_approved_badge_works_with_any_email(client):
    approve("1234")
    assert signup(client, email="anyone@gmail.com", approved=False).status_code == 201
    assert login(client).status_code == 200
    # still only one account per badge
    assert signup(client, email="other@gmail.com", approved=False).status_code == 409


def test_removed_badge_can_no_longer_log_in(client):
    from users_store import remove_approved_badge

    signup(client)
    assert login(client).status_code == 200
    assert remove_approved_badge("1234") is True
    assert login(client).status_code == 401
    assert remove_approved_badge("1234") is False


def test_approved_badge_is_marked_claimed(client):
    from users_store import get_approved_badge

    signup(client)
    assert get_approved_badge("1234").get("claimed_at")


def test_manage_badges_script(client, capsys):
    import manage_badges

    assert manage_badges.main(["add", "5555", "6666"]) == 0
    signup(client, badge="6666", approved=False)
    assert manage_badges.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "5555         not registered yet" in out
    assert "6666         registered" in out

    assert manage_badges.main(["remove", "5555"]) == 0
    assert manage_badges.main(["remove", "5555"]) == 1


def test_approve_existing_keeps_current_accounts_working(client):
    import manage_badges
    from users_store import remove_approved_badge

    signup(client)
    remove_approved_badge("1234")  # like an account made before the approved list existed
    assert login(client).status_code == 401
    assert manage_badges.main(["approve-existing"]) == 0
    assert login(client).status_code == 200


def test_generate_badges(client, tmp_path, capsys):
    import manage_badges
    from users_store import list_approved_badges

    out_file = tmp_path / "badges.txt"
    assert manage_badges.main(["generate", "25", "--out", str(out_file)]) == 0
    badges = out_file.read_text().split()
    assert len(badges) == len(set(badges)) == 25
    assert all(len(badge) == 8 and badge.isdigit() for badge in badges)
    assert {item["badge_num"] for item in list_approved_badges()} == set(badges)
    assert capsys.readouterr().out.split() == badges  # printed too

    # a generated badge can register with any email
    assert signup(client, badge=badges[0], email="new.officer@gmail.com", approved=False).status_code == 201
