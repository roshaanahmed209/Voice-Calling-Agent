"""Database models.

The schema mirrors the minimum demographic dataset a U.S. provider collects at
registration. Constraints live here as well as in the Pydantic layer so that a
bad write is rejected even if it arrives from something other than our own API.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

SEX_VALUES = ("Male", "Female", "Other", "Decline to Answer")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_uuid
    )

    # --- Required demographics --------------------------------------------
    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False)
    date_of_birth: Mapped[str] = mapped_column(String(10), nullable=False)  # ISO YYYY-MM-DD
    sex: Mapped[str] = mapped_column(
        SAEnum(*SEX_VALUES, name="sex_enum", native_enum=False), nullable=False
    )
    phone_number: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    address_line_1: Mapped[str] = mapped_column(String(200), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False)

    # --- Optional ----------------------------------------------------------
    email: Mapped[str | None] = mapped_column(String(254))
    address_line_2: Mapped[str | None] = mapped_column(String(200))
    insurance_provider: Mapped[str | None] = mapped_column(String(120))
    insurance_member_id: Mapped[str | None] = mapped_column(String(60))
    preferred_language: Mapped[str] = mapped_column(String(50), default="English")
    emergency_contact_name: Mapped[str | None] = mapped_column(String(120))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(10))
    next_appointment: Mapped[str | None] = mapped_column(String(120))

    # --- Bookkeeping -------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    # Soft delete: rows are never removed, only stamped.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Where the record came from — useful when reviewing what the agent wrote.
    source: Mapped[str] = mapped_column(String(20), default="api")

    __table_args__ = (
        CheckConstraint("length(phone_number) = 10", name="ck_phone_length"),
        CheckConstraint("length(state) = 2", name="ck_state_length"),
        Index("ix_patients_last_name_lower", "last_name"),
        Index("ix_patients_dob", "date_of_birth"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Patient {self.patient_id} {self.first_name} {self.last_name}>"


class CallTranscript(Base):
    """Bonus: transcript/summary of each call, linked to a patient when known."""

    __tablename__ = "call_transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    call_id: Mapped[str | None] = mapped_column(String(80), index=True)
    caller_number: Mapped[str | None] = mapped_column(String(20))
    patient_id: Mapped[str | None] = mapped_column(String(36), index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    ended_reason: Mapped[str | None] = mapped_column(String(80))
    duration_seconds: Mapped[int | None] = mapped_column()
    direction: Mapped[str] = mapped_column(String(20), default="inbound")
    status: Mapped[str] = mapped_column(String(20), default="ended")
    customer_name: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
