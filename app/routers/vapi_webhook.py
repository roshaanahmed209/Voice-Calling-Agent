"""Vapi webhook — the bridge between the voice agent and the database.

Vapi posts here whenever the assistant invokes one of its tools mid-call, and
again with an end-of-call report. Tool handlers call the same service layer the
REST API uses, so a record created by phone is validated identically to one
created by POST /patients.

Expected inbound shape (tool call):

    {"message": {"type": "tool-calls",
                 "call": {"id": "...", "customer": {"number": "+14155550199"}},
                 "toolCallList": [{"id": "abc", "name": "create_patient",
                                   "arguments": {...}}]}}

Expected reply:

    {"results": [{"toolCallId": "abc", "result": "…text the LLM will read…"}]}

The result string is fed straight back to the model, so it is written as a
short instruction to the agent rather than as raw JSON.
"""

import json
import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import crud
from app.config import settings
from app.database import get_db
from app.schemas import PatientCreate, PatientUpdate, normalize_phone

logger = logging.getLogger("vapi")

router = APIRouter(prefix="/vapi", tags=["voice-agent"])


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

def verify_secret(x_vapi_secret: str | None = Header(default=None)) -> None:
    """Reject anything that does not carry the shared secret.

    Configure the same value in the Vapi assistant under Server URL Secret.
    If VAPI_SECRET is left blank the check is skipped, which is convenient for
    local development but should not be done in a deployed environment.
    """
    if not settings.vapi_secret:
        logger.warning("VAPI_SECRET is not set — webhook is unauthenticated.")
        return
    if not x_vapi_secret or not secrets.compare_digest(x_vapi_secret, settings.vapi_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook secret.")


# ---------------------------------------------------------------------------
# Payload helpers — Vapi has shipped a few shapes for this; accept all of them.
# ---------------------------------------------------------------------------

def extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    raw = (
        message.get("toolCallList")
        or message.get("toolCalls")
        or message.get("tool_calls")
        or []
    )
    calls = []
    for item in raw:
        name = item.get("name") or item.get("function", {}).get("name")
        args = item.get("arguments")
        if args is None:
            args = item.get("function", {}).get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append({"id": item.get("id"), "name": name, "arguments": args or {}})

    # Legacy single-function shape.
    if not calls and message.get("functionCall"):
        fc = message["functionCall"]
        args = fc.get("parameters") or fc.get("arguments") or {}
        if isinstance(args, str):
            args = json.loads(args)
        calls.append({"id": fc.get("id"), "name": fc.get("name"), "arguments": args})

    return calls


def caller_number(message: dict[str, Any]) -> str | None:
    call = message.get("call") or {}
    number = (call.get("customer") or {}).get("number")
    if not number:
        return None
    try:
        return normalize_phone(number)
    except ValueError:
        return None


def field_errors(exc: ValidationError) -> dict[str, str]:
    """Flatten Pydantic errors into {field: human message} for the agent."""
    out: dict[str, str] = {}
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "payload"
        msg = err["msg"].removeprefix("Value error, ")
        out[field] = msg
    return out


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def tool_lookup_patient(db: Session, args: dict, fallback_phone: str | None) -> str:
    raw = args.get("phone_number") or fallback_phone
    if not raw:
        return "No phone number available. Ask the caller for their number."
    try:
        phone = normalize_phone(raw)
    except ValueError as exc:
        return f"That number is not valid: {exc} Ask the caller to repeat it."

    patient = crud.find_by_phone(db, phone)
    if patient is None:
        return (
            "No existing record found for that number. "
            "Continue with a new registration."
        )
    return (
        f"An existing record was found. patient_id={patient.patient_id}, "
        f"name={patient.first_name} {patient.last_name}, "
        f"date_of_birth={patient.date_of_birth}. "
        "Tell the caller we already have a record for them and ask whether "
        "they would like to update it instead of creating a new one."
    )


def tool_create_patient(db: Session, args: dict, fallback_phone: str | None) -> str:
    if not args.get("phone_number") and fallback_phone:
        args["phone_number"] = fallback_phone

    try:
        payload = PatientCreate(**args)
    except ValidationError as exc:
        errors = field_errors(exc)
        logger.info("voice.create.rejected errors=%s", errors)
        detail = "; ".join(f"{k}: {v}" for k, v in errors.items())
        return (
            f"The record was not saved because some fields need correcting: {detail}. "
            "Ask the caller only about those specific fields, then try again."
        )

    try:
        patient = crud.create_patient(db, payload, source="voice")
    except Exception:
        logger.exception("voice.create.db_error")
        return (
            "The database could not be reached. Apologise to the caller, tell "
            "them their information was not saved, and ask them to call back "
            "in a few minutes. Do not claim the registration succeeded."
        )

    logger.info(
        "voice.create.ok id=%s payload=%s",
        patient.patient_id, json.dumps(payload.model_dump(), default=str),
    )
    return (
        f"Saved successfully. patient_id={patient.patient_id}. "
        f"Confirm to the caller that {patient.first_name} is registered, then "
        "close the call warmly."
    )


def tool_update_patient(db: Session, args: dict, fallback_phone: str | None) -> str:
    patient_id = args.pop("patient_id", None)
    patient = None

    if patient_id:
        patient = crud.get_patient(db, patient_id)
    if patient is None:
        lookup = args.get("phone_number") or fallback_phone
        if lookup:
            try:
                patient = crud.find_by_phone(db, normalize_phone(lookup))
            except ValueError:
                patient = None
    if patient is None:
        return (
            "No matching record was found to update. "
            "Offer to register the caller as a new patient instead."
        )

    try:
        payload = PatientUpdate(**args)
    except ValidationError as exc:
        detail = "; ".join(f"{k}: {v}" for k, v in field_errors(exc).items())
        return f"Could not update: {detail}. Re-ask for those fields only."

    try:
        patient = crud.update_patient(db, patient, payload)
    except Exception:
        logger.exception("voice.update.db_error")
        return (
            "The update could not be saved. Tell the caller their changes were "
            "not stored and ask them to try again shortly."
        )

    logger.info("voice.update.ok id=%s fields=%s", patient.patient_id,
                list(payload.model_dump(exclude_unset=True).keys()))
    return (
        f"Record updated for {patient.first_name} {patient.last_name}. "
        "Confirm the change to the caller and close the call."
    )


HANDLERS = {
    "lookup_patient": tool_lookup_patient,
    "lookup_patient_by_phone": tool_lookup_patient,
    "create_patient": tool_create_patient,
    "update_patient": tool_update_patient,
}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/webhook", dependencies=[Depends(verify_secret)])
async def vapi_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    message = body.get("message", body)
    event = message.get("type", "unknown")

    if event in ("tool-calls", "function-call"):
        fallback = caller_number(message)
        results = []
        for call in extract_tool_calls(message):
            handler = HANDLERS.get(call["name"])
            if handler is None:
                logger.warning("voice.tool.unknown name=%s", call["name"])
                result = f"Unknown tool '{call['name']}'."
            else:
                logger.info("voice.tool name=%s args=%s", call["name"],
                            json.dumps(call["arguments"], default=str))
                result = handler(db, dict(call["arguments"]), fallback)
            results.append({"toolCallId": call["id"], "result": result})
        return {"results": results}

    if event == "end-of-call-report":
        artifact = message.get("artifact") or {}
        transcript = message.get("transcript") or artifact.get("transcript")
        summary = message.get("summary") or artifact.get("summary")
        phone = caller_number(message)
        patient = crud.find_by_phone(db, phone) if phone else None
        call = message.get("call") or {}
        call_type = str(call.get("type") or "").lower()
        direction = "outbound" if ("outbound" in call_type or "web" in call_type) else "inbound"
        crud.save_transcript(
            db,
            call_id=call.get("id"),
            caller_number=phone,
            patient_id=patient.patient_id if patient else None,
            customer_name=(call.get("customer") or {}).get("name"),
            summary=summary,
            transcript=transcript if isinstance(transcript, str) else json.dumps(transcript),
            ended_reason=message.get("endedReason"),
            duration_seconds=int(message.get("durationSeconds") or 0) or None,
            direction=direction,
            status="ended",
        )
        logger.info("voice.call.ended reason=%s direction=%s", message.get("endedReason"), direction)
        return {"received": True}

    if event == "status-update":
        call = message.get("call") or {}
        call_id = call.get("id") or message.get("callId")
        if not call_id:
            return {"received": True}
        phone = caller_number(message)
        call_type = str(call.get("type") or "").lower()
        direction = "outbound" if ("outbound" in call_type or "web" in call_type) else None
        crud.upsert_call(
            db,
            call_id=call_id,
            caller_number=phone,
            direction=direction,
            status=message.get("status") or call.get("status"),
        )
        logger.info("voice.call.status status=%s", message.get("status"))
        return {"received": True}

    # speech-update, conversation-update etc. — acknowledge only.
    logger.debug("voice.event ignored type=%s", event)
    return {"received": True}
