"""Dashboard login and session endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.auth import (
    COOKIE_NAME,
    SESSION_TTL_SECONDS,
    credentials_configured,
    create_session_token,
    passwords_match,
    require_login,
)
from app.config import settings
from app.schemas import LoginRequest

logger = logging.getLogger("api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    if not credentials_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "DASHBOARD_USERNAME and DASHBOARD_PASSWORD are not set.",
        )
    if not (
        passwords_match(payload.username, settings.dashboard_username)
        and passwords_match(payload.password, settings.dashboard_password)
    ):
        logger.info("login.failed user=%s", payload.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password.")

    response.set_cookie(
        key=COOKIE_NAME,
        value=create_session_token(settings.dashboard_username),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    logger.info("login.ok user=%s", settings.dashboard_username)
    return {"data": {"username": settings.dashboard_username}, "error": None}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"data": {"signed_out": True}, "error": None}


@router.get("/me")
def me(username: str = Depends(require_login)):
    return {"data": {"username": username}, "error": None}
