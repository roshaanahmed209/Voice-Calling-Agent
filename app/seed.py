"""Idempotent demo patients. Safe to run on every boot."""

import logging

from app import crud
from app.database import SessionLocal, init_db
from app.schemas import PatientCreate

logger = logging.getLogger("app.seed")

DEMO = [
    PatientCreate(
        first_name="Maria",
        last_name="Alvarez",
        date_of_birth="03/14/1985",
        sex="Female",
        phone_number="4155550142",
        email="maria.alvarez@example.com",
        address_line_1="220 Bayview Street",
        address_line_2="Apt 4B",
        city="Oakland",
        state="CA",
        zip_code="94612",
        insurance_provider="Blue Shield of California",
        insurance_member_id="BSC884120397",
        preferred_language="Spanish",
        emergency_contact_name="Luis Alvarez",
        emergency_contact_phone="4155550188",
    ),
    PatientCreate(
        first_name="Desmond",
        last_name="Okafor",
        date_of_birth="11/02/1971",
        sex="Male",
        phone_number="2125550119",
        address_line_1="1450 Amsterdam Avenue",
        city="New York",
        state="NY",
        zip_code="10027-3312",
        preferred_language="English",
    ),
]


def seed_if_needed() -> int:
    """Insert demo rows that are not already present. Returns how many were added."""
    init_db()
    db = SessionLocal()
    added = 0
    try:
        for record in DEMO:
            if crud.find_by_phone(db, record.phone_number):
                logger.info("seed.skip %s %s", record.first_name, record.last_name)
                continue
            patient = crud.create_patient(db, record, source="seed")
            added += 1
            logger.info(
                "seed.added %s %s id=%s",
                patient.first_name, patient.last_name, patient.patient_id,
            )
        logger.info("seed.done inserted=%s", added)
        return added
    finally:
        db.close()
