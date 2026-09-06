#!/usr/bin/env python3
"""Create or update the Vapi assistant from vapi/assistant.json.

Optional convenience — you can do all of this by hand in the Vapi dashboard.
The script exists so the assistant config is version-controlled rather than
living only in someone's browser.

Usage:
    python scripts/provision_vapi.py            # create or update the assistant
    python scripts/provision_vapi.py --attach   # also point your phone number at it

Requires in .env:
    VAPI_API_KEY          your Vapi private key
    PUBLIC_BASE_URL       https://your-app.up.railway.app  (no trailing slash)
    VAPI_SECRET           shared secret for webhook auth
    VAPI_PHONE_NUMBER_ID  only needed for --attach
"""

import argparse
import json
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

import os  # noqa: E402  (must follow load_dotenv)

API = "https://api.vapi.ai"
API_KEY = os.getenv("VAPI_API_KEY", "")
BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
SECRET = os.getenv("VAPI_SECRET", "")
PHONE_ID = os.getenv("VAPI_PHONE_NUMBER_ID", "")
ASSISTANT_ID = os.getenv("VAPI_ASSISTANT_ID", "")


def load_config() -> dict:
    if not API_KEY:
        sys.exit("VAPI_API_KEY is not set in .env")
    if not BASE_URL.startswith("https://"):
        sys.exit("PUBLIC_BASE_URL must be a public https URL (Vapi cannot reach localhost)")

    raw = (ROOT / "vapi" / "assistant.json").read_text(encoding="utf-8")
    raw = raw.replace("__PUBLIC_BASE_URL__", BASE_URL).replace("__VAPI_SECRET__", SECRET)
    config = json.loads(raw)
    config.pop("_comment", None)

    # Pull the prompt out of the markdown file so there is one source of truth.
    md = (ROOT / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
    prompt = md.split("## Prompt", 1)[1].strip() if "## Prompt" in md else md
    prompt = re.sub(r"^-{3,}\s*", "", prompt).strip()
    config["model"]["messages"][0]["content"] = prompt

    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attach", action="store_true",
                        help="point VAPI_PHONE_NUMBER_ID at this assistant")
    args = parser.parse_args()

    config = load_config()
    headers = {"Authorization": f"Bearer {API_KEY}"}

    with httpx.Client(base_url=API, headers=headers, timeout=30) as client:
        existing = client.get("/assistant").raise_for_status().json()
        match = None
        if ASSISTANT_ID:
            match = next((a for a in existing if a.get("id") == ASSISTANT_ID), None)
            if match is None:
                sys.exit(f"VAPI_ASSISTANT_ID {ASSISTANT_ID} was not found in this account.")
        else:
            match = next((a for a in existing if a.get("name") == config["name"]), None)

        if match:
            res = client.patch(f"/assistant/{match['id']}", json=config)
            action = "Updated"
        else:
            res = client.post("/assistant", json=config)
            action = "Created"

        if res.status_code >= 400:
            sys.exit(f"Vapi rejected the config ({res.status_code}):\n{res.text}")

        assistant = res.json()
        print(f"{action} assistant {assistant['id']} — {assistant['name']}")
        print(f"Webhook: {BASE_URL}/vapi/webhook")

        if args.attach:
            if not PHONE_ID:
                sys.exit("VAPI_PHONE_NUMBER_ID is not set — cannot attach.")
            res = client.patch(f"/phone-number/{PHONE_ID}",
                               json={"assistantId": assistant["id"]})
            if res.status_code >= 400:
                sys.exit(f"Could not attach the number ({res.status_code}):\n{res.text}")
            print(f"Attached to {res.json().get('number', PHONE_ID)}")


if __name__ == "__main__":
    main()
