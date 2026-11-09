"""Forgot-password flow.

POST /forgot-password  { email }                              -> emails a reset link
POST /reset-password   { badge_num, token, new_password }     -> sets the new password

The link points at the frontend's /reset-password page. Only a SHA-256 hash of
the token is stored, it expires after RESET_TOKEN_TTL_SECONDS, and it works once.

Email is sent with Amazon SES when SES_SENDER_EMAIL is set (the sender must be a
verified identity in SES). Without it -- e.g. local dev -- the link is printed
to the server log instead. Setup steps: deploy/README.md, "Password reset emails".

Send yourself a sample email to check SES works (no account needed):
    SES_SENDER_EMAIL=noreply@fly-hawkeye.com python password_reset.py you@example.com
"""

import hashlib
import html
import logging
import os
import secrets
import sys
import time
from email.utils import formataddr
from urllib.parse import urlencode

import bcrypt
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from passwords import check_password
from users_store import (
    UsersTableSchemaError,
    get_user_by_email,
    reset_password_with_token,
    save_password_reset_token,
)

router = APIRouter(tags=["users"])
logger = logging.getLogger("hawkeye.password_reset")

RESET_TOKEN_TTL_SECONDS = 30 * 60
RESEND_COOLDOWN_SECONDS = 60  # don't email the same account more than once a minute

FORGOT_MESSAGE = "If that email is registered, a reset link is on its way."


def frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def build_reset_email(badge_num: str, link: str) -> tuple[str, str, str]:
    """Return (subject, plain-text body, HTML body) for the reset email."""
    minutes = RESET_TOKEN_TTL_SECONDS // 60
    subject = "Reset your Hawkeye password"
    text = (
        f"Someone asked to reset the Hawkeye password for badge {badge_num}.\n\n"
        f"Reset it here (the link works once and expires in {minutes} minutes):\n"
        f"{link}\n\n"
        "If this wasn't you, you can ignore this email. Your password won't change."
    )
    safe_link = html.escape(link, quote=True)
    safe_badge = html.escape(badge_num)
    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:32px 16px;background:#000000;font-family:Arial,Helvetica,sans-serif;color:#ffffff;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr><td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;">
          <tr><td style="font-size:28px;padding-bottom:24px;text-align:center;">Hawkeye</td></tr>
          <tr><td style="font-size:16px;line-height:24px;color:#d9d9d9;padding-bottom:28px;">
            Someone asked to reset the password for badge <strong style="color:#ffffff;">{safe_badge}</strong>.
            The button works once and expires in {minutes} minutes.
          </td></tr>
          <tr><td align="center" style="padding-bottom:28px;">
            <a href="{safe_link}" style="display:inline-block;padding:16px 40px;border-radius:999px;background:#FF9F43;color:#000000;font-size:18px;font-weight:bold;text-decoration:none;">Reset password</a>
          </td></tr>
          <tr><td style="font-size:13px;line-height:20px;color:#a6a6a6;">
            Button not working? Paste this into your browser:<br>
            <a href="{safe_link}" style="color:#BD93F9;word-break:break-all;">{safe_link}</a>
          </td></tr>
          <tr><td style="font-size:13px;line-height:20px;color:#a6a6a6;padding-top:24px;">
            If this wasn't you, you can ignore this email. Your password won't change.
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>
"""
    return subject, text, html_body


def deliver_email(to_address: str, subject: str, text: str, html_body: str) -> None:
    """Send one email through Amazon SES. Raises on failure."""
    sender = os.environ["SES_SENDER_EMAIL"]
    sender_name = os.getenv("SES_SENDER_NAME", "Hawkeye")
    region = (
        os.getenv("SES_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1"
    )
    boto3.client("ses", region_name=region).send_email(
        Source=formataddr((sender_name, sender)),
        Destination={"ToAddresses": [to_address]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Text": {"Data": text, "Charset": "UTF-8"},
                "Html": {"Data": html_body, "Charset": "UTF-8"},
            },
        },
    )


def send_reset_email(email: str, badge_num: str, link: str) -> None:
    """Send the reset link with SES, or log it when SES isn't configured."""
    if not os.getenv("SES_SENDER_EMAIL"):
        logger.warning("SES_SENDER_EMAIL not set; reset link for %s: %s", badge_num, link)
        print(f"[password reset] {badge_num} <{email}>: {link}", flush=True)
        return

    subject, text, html_body = build_reset_email(badge_num, link)
    try:
        deliver_email(email, subject, text, html_body)
        logger.info("Sent password reset email for badge %s", badge_num)
    except (BotoCoreError, ClientError):
        # Runs after the response, so the user still sees the normal message; check the logs.
        logger.exception("Could not send the password reset email for %s", badge_num)


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    badge_num: str
    token: str
    new_password: str


@router.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest, background_tasks: BackgroundTasks):
    # Same answer whether or not the email exists, so it can't be used to find accounts.
    email = request.email.strip().lower()
    if not email:
        raise HTTPException(status_code=422, detail="Enter your email address")

    try:
        user = get_user_by_email(email)
        if user is None or user.get("status") != "active":
            return {"message": FORGOT_MESSAGE}

        now = int(time.time())
        if now - int(user.get("reset_requested_at", 0)) < RESEND_COOLDOWN_SECONDS:
            return {"message": FORGOT_MESSAGE}

        token = secrets.token_urlsafe(32)
        save_password_reset_token(
            user["badge_num"],
            hash_token(token),
            now + RESET_TOKEN_TTL_SECONDS,
        )
    except UsersTableSchemaError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(status_code=503, detail="Could not start the reset right now") from error

    query = urlencode({"badge": user["badge_num"], "token": token})
    link = f"{frontend_url()}/reset-password?{query}"
    # Send after responding so the response time doesn't reveal whether the email exists.
    background_tasks.add_task(send_reset_email, user["email"], user["badge_num"], link)
    return {"message": FORGOT_MESSAGE}


@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest):
    badge_num = request.badge_num.strip()
    if not badge_num or not request.token:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")
    if not request.new_password:
        raise HTTPException(status_code=422, detail="Enter a new password")
    check_password(request.new_password)

    password_hash = bcrypt.hashpw(request.new_password.encode(), bcrypt.gensalt()).decode()
    try:
        updated = reset_password_with_token(badge_num, hash_token(request.token), password_hash)
    except UsersTableSchemaError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (BotoCoreError, ClientError) as error:
        raise HTTPException(status_code=503, detail="Could not reset the password right now") from error

    if not updated:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")
    return {"message": "Password updated. You can log in now."}


if __name__ == "__main__":  # send a sample reset email to check the SES setup
    if len(sys.argv) != 2:
        sys.exit("Usage: python password_reset.py <your email>")
    if not os.getenv("SES_SENDER_EMAIL"):
        sys.exit("Set SES_SENDER_EMAIL to a sender verified in SES first.")
    to_address = sys.argv[1]
    subject, text, html_body = build_reset_email(
        "TEST", f"{frontend_url()}/reset-password?badge=TEST&token=sample-only"
    )
    try:
        deliver_email(to_address, "[Test] " + subject, text, html_body)
    except (BotoCoreError, ClientError) as error:
        sys.exit(f"SES did not send it: {error}")
    print(f"Sent a sample reset email to {to_address}. Check the inbox (and spam).")
