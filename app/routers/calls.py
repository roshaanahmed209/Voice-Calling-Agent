"""Call log and outbound dialing."""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import crud
from app.auth import require_login
from app.config import settings
from app.database import get_db
from app.schemas import OutboundCallCreate, TranscriptOut

logger = logging.getLogger("api.calls")

router = APIRouter(
    prefix="/calls",
    tags=["voice-agent"],
    dependencies=[Depends(require_login)],
)


def _serialize_call(db: Session, record) -> dict:
    data = TranscriptOut.model_validate(record).model_dump(mode="json")
    if record.patient_id:
        patient = crud.get_patient(db, record.patient_id, include_deleted=True)
        if patient:
            data["patient_name"] = f"{patient.first_name} {patient.last_name}"
    return data


def _vapi_error_message(res: httpx.Response) -> str:
    try:
        payload = res.json()
    except ValueError:
        payload = {}
    raw = payload.get("message") or payload.get("error") or res.text
    if isinstance(raw, list):
        raw = "; ".join(str(part) for part in raw)
    text = str(raw or "").strip()
    lowered = text.lower()
    if "daily outbound call limit" in lowered or "daily outbound-call limit" in lowered:
        return (
            "This Vapi number has hit today's daily outbound-call limit. "
            "Inbound calls still work — have someone dial +1 (516) 583-1185. "
            "To place more outbound calls today, import a Twilio number in Vapi, "
            "or use Call from this browser."
        )
    if text:
        return text
    return "Vapi could not start the call. Check the number and try again."


@router.get("/dial-config", summary="Public keys needed to start a browser call")
def dial_config():
    if not settings.vapi_public_key or not settings.vapi_assistant_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "VAPI_PUBLIC_KEY and VAPI_ASSISTANT_ID must be set for browser calls.",
        )
    return {
        "data": {
            "public_key": settings.vapi_public_key,
            "assistant_id": settings.vapi_assistant_id,
        },
        "error": None,
    }


@router.get("", summary="Recent call log")
def list_calls(
    limit: int = Query(100, ge=1, le=500),
    direction: str | None = Query(None, pattern="^(inbound|outbound)$"),
    db: Session = Depends(get_db),
):
    records = crud.list_transcripts(db, limit=limit, direction=direction)
    return {"data": [_serialize_call(db, r) for r in records], "error": None}


@router.post("/outbound", status_code=status.HTTP_201_CREATED, summary="Place an outbound call")
def start_outbound(payload: OutboundCallCreate, db: Session = Depends(get_db)):
    if not settings.vapi_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "VAPI_API_KEY is not configured.")
    if not settings.vapi_phone_number_id or not settings.vapi_assistant_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "VAPI_PHONE_NUMBER_ID and VAPI_ASSISTANT_ID must be set to place a call.",
        )

    e164 = f"+1{payload.phone_number}"
    patient = crud.find_by_phone(db, payload.phone_number)
    customer_name = payload.customer_name
    if patient and not customer_name:
        customer_name = f"{patient.first_name} {patient.last_name}"

    body = {
        "assistantId": settings.vapi_assistant_id,
        "phoneNumberId": settings.vapi_phone_number_id,
        "customer": {"number": e164},
    }
    if customer_name:
        body["customer"]["name"] = customer_name

    try:
        with httpx.Client(timeout=30) as client:
            res = client.post(
                "https://api.vapi.ai/call",
                headers={
                    "Authorization": f"Bearer {settings.vapi_api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except httpx.HTTPError:
        logger.exception("outbound.vapi_unreachable")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Could not reach Vapi to start the call.",
        ) from None

    if res.status_code >= 400:
        logger.warning("outbound.vapi_rejected status=%s body=%s", res.status_code, res.text[:500])
        detail = _vapi_error_message(res)
        code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if "daily outbound-call limit" in detail.lower()
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(code, detail)

    vapi_call = res.json()
    call_id = vapi_call.get("id")
    record = crud.upsert_call(
        db,
        call_id=call_id,
        caller_number=payload.phone_number,
        patient_id=patient.patient_id if patient else None,
        customer_name=customer_name,
        direction="outbound",
        status=vapi_call.get("status") or "queued",
    )
    logger.info("outbound.started id=%s number=%s", call_id, payload.phone_number)
    return {"data": _serialize_call(db, record), "error": None}


@router.post("/web", status_code=status.HTTP_201_CREATED, summary="Log a browser call")
def start_web_call(db: Session = Depends(get_db)):
    record = crud.upsert_call(
        db,
        caller_number=None,
        customer_name="Browser",
        direction="outbound",
        status="in-progress",
    )
    return {"data": _serialize_call(db, record), "error": None}
