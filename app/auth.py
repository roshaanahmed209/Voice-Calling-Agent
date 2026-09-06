"""Cookie session login for the dashboard and protected API routes."""

import hashlib
import hmac
import time

from fastapi import Cookie, HTTPException, status

from app.config import settings

COOKIE_NAME = "cc_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


def credentials_configured() -> bool:
    return bool(settings.dashboard_username and settings.dashboard_password)


def _secret() -> bytes:
    raw = settings.dashboard_session_secret or settings.vapi_secret or "dev-only-session"
    return raw.encode("utf-8")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def passwords_match(given: str, expected: str) -> bool:
    return hmac.compare_digest(_digest(given or ""), _digest(expected or ""))


def create_session_token(username: str) -> str:
    expires = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"{username}:{expires}"
    signature = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def read_session_token(token: str | None) -> str | None:
    if not token:
        return None
    parts = token.split(":")
    if len(parts) != 3:
        return None
    username, expires_raw, signature = parts
    try:
        expires = int(expires_raw)
    except ValueError:
        return None
    payload = f"{username}:{expires}"
    expected = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    if expires < int(time.time()):
        return None
    return username


def require_login(cc_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> str:
    username = read_session_token(cc_session)
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required.")
    return username
