#!/usr/bin/env python3
"""Insert two demonstration records. Safe to run repeatedly.

    python scripts/seed.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.seed import seed_if_needed  # noqa: E402


def main() -> None:
    added = seed_if_needed()
    print(f"{added} record(s) inserted.")


if __name__ == "__main__":
    main()
