"""Service layer.

Both the REST API and the voice-agent tool handler call into this module, so
the agent cannot take a shortcut around validation or write to the database in
a way the API would not allow.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CallTranscript, Patient
from app.schemas import PatientCreate, PatientUpdate


def list_patients(
    db: Session,
    *,
    last_name: str | None = None,
    date_of_birth: str | None = None,
    phone_number: str | None = None,
    include_deleted: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[Patient]:
    stmt = select(Patient)

    if not include_deleted:
        stmt = stmt.where(Patient.deleted_at.is_(None))
    if last_name:
        stmt = stmt.where(func.lower(Patient.last_name) == last_name.lower())
    if date_of_birth:
        stmt = stmt.where(Patient.date_of_birth == date_of_birth)
    if phone_number:
        stmt = stmt.where(Patient.phone_number == phone_number)

    stmt = stmt.order_by(Patient.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars())


def get_patient(db: Session, patient_id: str, *, include_deleted: bool = False):
    stmt = select(Patient).where(Patient.patient_id == patient_id)
    if not include_deleted:
        stmt = stmt.where(Patient.deleted_at.is_(None))
    return db.execute(stmt).scalar_one_or_none()


def find_by_phone(db: Session, phone_number: str):
    """Used for duplicate detection when a known number calls in."""
    stmt = (
        select(Patient)
        .where(Patient.phone_number == phone_number)
        .where(Patient.deleted_at.is_(None))
        .order_by(Patient.created_at.desc())
    )
    return db.execute(stmt).scalars().first()


def create_patient(db: Session, payload: PatientCreate, *, source: str = "api") -> Patient:
    patient = Patient(**payload.model_dump(), source=source)
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


def update_patient(db: Session, patient: Patient, payload: PatientUpdate) -> Patient:
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in changes.items():
        setattr(patient, key, value)
    patient.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(patient)
    return patient


def soft_delete_patient(db: Session, patient: Patient) -> Patient:
    """Stamp deleted_at. Rows are never removed from the table."""
    patient.deleted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(patient)
    return patient


def find_call_by_vapi_id(db: Session, call_id: str | None) -> CallTranscript | None:
    if not call_id:
        return None
    stmt = select(CallTranscript).where(CallTranscript.call_id == call_id)
    return db.execute(stmt).scalar_one_or_none()


def upsert_call(
    db: Session,
    *,
    call_id: str | None = None,
    caller_number: str | None = None,
    patient_id: str | None = None,
    customer_name: str | None = None,
    summary: str | None = None,
    transcript: str | None = None,
    ended_reason: str | None = None,
    duration_seconds: int | None = None,
    direction: str | None = None,
    status: str | None = None,
) -> CallTranscript:
    record = find_call_by_vapi_id(db, call_id)
    if record is None:
        record = CallTranscript(call_id=call_id)
        db.add(record)

    if caller_number is not None:
        record.caller_number = caller_number
    if patient_id is not None:
        record.patient_id = patient_id
    if customer_name is not None:
        record.customer_name = customer_name
    if summary is not None:
        record.summary = summary
    if transcript is not None:
        record.transcript = transcript
    if ended_reason is not None:
        record.ended_reason = ended_reason
    if duration_seconds is not None:
        record.duration_seconds = duration_seconds
    if direction is not None:
        record.direction = direction
    if status is not None:
        record.status = status

    db.commit()
    db.refresh(record)
    return record


def save_transcript(
    db: Session,
    *,
    call_id: str | None,
    caller_number: str | None,
    patient_id: str | None,
    summary: str | None,
    transcript: str | None,
    ended_reason: str | None,
    duration_seconds: int | None,
    direction: str | None = None,
    status: str | None = None,
    customer_name: str | None = None,
) -> CallTranscript:
    return upsert_call(
        db,
        call_id=call_id,
        caller_number=caller_number,
        patient_id=patient_id,
        customer_name=customer_name,
        summary=summary,
        transcript=transcript,
        ended_reason=ended_reason,
        duration_seconds=duration_seconds,
        direction=direction,
        status=status or "ended",
    )


def list_transcripts(
    db: Session,
    limit: int = 50,
    direction: str | None = None,
) -> list[CallTranscript]:
    stmt = select(CallTranscript)
    if direction:
        stmt = stmt.where(CallTranscript.direction == direction)
    stmt = stmt.order_by(CallTranscript.created_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars())


def stats(db: Session) -> dict:
    total = db.execute(
        select(func.count()).select_from(Patient).where(Patient.deleted_at.is_(None))
    ).scalar_one()
    by_voice = db.execute(
        select(func.count())
        .select_from(Patient)
        .where(Patient.deleted_at.is_(None), Patient.source == "voice")
    ).scalar_one()
    calls = db.execute(select(func.count()).select_from(CallTranscript)).scalar_one()
    outbound = db.execute(
        select(func.count())
        .select_from(CallTranscript)
        .where(CallTranscript.direction == "outbound")
    ).scalar_one()
    inbound = db.execute(
        select(func.count())
        .select_from(CallTranscript)
        .where(CallTranscript.direction == "inbound")
    ).scalar_one()
    total_duration = db.execute(
        select(func.coalesce(func.sum(CallTranscript.duration_seconds), 0))
    ).scalar_one()
    with_duration = db.execute(
        select(func.count())
        .select_from(CallTranscript)
        .where(CallTranscript.duration_seconds.is_not(None))
    ).scalar_one()
    average = int(total_duration / with_duration) if with_duration else 0
    return {
        "patients": total,
        "from_calls": by_voice,
        "calls_logged": calls,
        "outbound_calls": outbound,
        "inbound_calls": inbound,
        "total_duration_seconds": int(total_duration or 0),
        "average_duration_seconds": average,
    }
