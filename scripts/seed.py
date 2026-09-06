#!/usr/bin/env python3
"""Insert two demonstration records so the dashboard and API are not empty.

Safe to run repeatedly — it skips numbers that already exist.

    python scripts/seed.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crud  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.schemas import PatientCreate  # noqa: E402

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


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        added = 0
        for record in DEMO:
            if crud.find_by_phone(db, record.phone_number):
                print(f"skip  {record.first_name} {record.last_name} (already present)")
                continue
            patient = crud.create_patient(db, record, source="seed")
            print(f"added {patient.first_name} {patient.last_name}  {patient.patient_id}")
            added += 1
        print(f"\n{added} record(s) inserted.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
