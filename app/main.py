"""Application entrypoint.

Wires together the REST API, the Vapi webhook, the dashboard, and the error
handlers that keep every response inside the {"data": ..., "error": ...}
envelope — including failures.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import crud
from app.auth import require_login
from app.config import settings
from app.database import get_db, init_db
from app.logging_config import configure_logging
from app.routers import auth, calls, patients, vapi_webhook
from app.seed import seed_if_needed

configure_logging()
logger = logging.getLogger("app")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_if_needed()
    logger.info("Started. db=%s env=%s",
                settings.normalized_database_url.split("@")[-1], settings.environment)
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Patient registration collected over the phone by a voice AI agent, "
        "persisted to a database and exposed over REST."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dashboard is served from the same origin; open for testing
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Error handlers — consistent envelope and correct status codes
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    fields = {}
    for err in exc.errors():
        key = ".".join(str(p) for p in err["loc"] if p != "body") or "body"
        fields[key] = err["msg"].removeprefix("Value error, ")
    logger.info("422 %s %s", request.url.path, fields)
    return JSONResponse(
        status_code=422,
        content={
            "data": None,
            "error": {
                "code": "validation_error",
                "message": "One or more fields are invalid.",
                "fields": fields,
            },
        },
    )


# Registered against Starlette's HTTPException, not FastAPI's. FastAPI's class
# subclasses it, so this catches both — including the 404s and 405s Starlette
# raises for unmatched routes, which would otherwise skip the envelope and
# return a bare {"detail": ...}.
@app.exception_handler(StarletteHTTPException)
async def http_handler(request: Request, exc: StarletteHTTPException):
    codes = {
        400: "bad_request",
        401: "unauthorized",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        429: "rate_limited",
    }
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "data": None,
            "error": {
                "code": codes.get(exc.status_code, "error"),
                "message": exc.detail,
            },
        },
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.exception("500 on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "data": None,
            "error": {
                "code": "internal_error",
                "message": "Something went wrong on our end.",
            },
        },
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(auth.router)
app.include_router(patients.router)
app.include_router(calls.router)
app.include_router(vapi_webhook.router)


@app.get("/health", tags=["meta"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        logger.exception("health check: database unreachable")
        db_ok = False
    return {"data": {"status": "ok" if db_ok else "degraded", "database": db_ok},
            "error": None}


@app.get("/stats", tags=["meta"])
def get_stats(db: Session = Depends(get_db), _: str = Depends(require_login)):
    return {"data": crud.stats(db), "error": None}


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/daily-shim.js", include_in_schema=False)
def daily_shim():
    """ESM shim so the Vapi web SDK uses the official Daily IIFE, not a CDN rewrite."""
    return FileResponse(STATIC_DIR / "daily-shim.js", media_type="text/javascript")
