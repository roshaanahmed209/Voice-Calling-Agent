"""Start uvicorn using PORT from the environment.

Railway injects PORT but does not expand it in start commands.
Running this file as scripts/start.py would otherwise put scripts/ on
sys.path and hide the app package, so we force the project root first.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import uvicorn

from app.logging_config import configure_logging
from app.seed import seed_if_needed


def main() -> None:
    configure_logging()
    seed_if_needed()
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, app_dir=str(ROOT))


if __name__ == "__main__":
    main()
