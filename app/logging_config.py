"""Logging setup.

Requirement: log the collected data payload for every call. Everything goes to
stdout (so `railway logs` shows it) and to logs/app.log when the filesystem is
writable.
"""

import logging
import os
import sys

from app.config import settings

FORMAT = "%(asctime)s %(levelname)-7s %(name)-18s %(message)s"


def configure_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    try:
        os.makedirs("logs", exist_ok=True)
        handlers.append(logging.FileHandler("logs/app.log", encoding="utf-8"))
    except OSError:
        # Read-only container filesystem — stdout alone is fine.
        pass

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=FORMAT,
        handlers=handlers,
        force=True,
    )

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
