"""REST endpoints for patient records.

Every response uses the {"data": ..., "error": ...} envelope, including errors
(see the exception handlers in app/main.py).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app import crud
from app.auth import require_login
from app.database import get_db
from app.schemas import (
    PatientCreate,
    PatientOut,
    PatientUpdate,
    normalize_dob,
    normalize_phone,
)

logger = logging.getLogger("api.patients")

router = APIRouter(
    prefix="/patients",
    tags=["patients"],
    dependencies=[Depends(require_login)],
)


@router.get("", summary="List patients")
def list_patients(
    last_name: str | None = Query(None),
    date_of_birth: str | None = Query(None, description="MM/DD/YYYY or YYYY-MM-DD"),
    phone_number: str | None = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    # Normalize filters so that ?phone_number=(415)555-0199 matches stored digits.
    try:
        if phone_number:
            phone_number = normalize_phone(phone_number)
        if date_of_birth:
            date_of_birth = normalize_dob(date_of_birth)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    patients = crud.list_patients(
        db,
        last_name=last_name,
        date_of_birth=date_of_birth,
        phone_number=phone_number,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [PatientOut.model_validate(p).model_dump(mode="json") for p in patients],
        "error": None,
    }


@router.get("/{patient_id}", summary="Get one patient")
def get_patient(patient_id: str, db: Session = Depends(get_db)):
    patient = crud.get_patient(db, patient_id)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No patient with that id.")
    return {"data": PatientOut.model_validate(patient).model_dump(mode="json"), "error": None}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a patient")
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    patient = crud.create_patient(db, payload)
    logger.info(
        "patient.created id=%s name=%s %s phone=%s",
        patient.patient_id, patient.first_name, patient.last_name, patient.phone_number,
    )
    return {"data": PatientOut.model_validate(patient).model_dump(mode="json"), "error": None}


@router.put("/{patient_id}", summary="Update a patient (partial allowed)")
def update_patient(patient_id: str, payload: PatientUpdate, db: Session = Depends(get_db)):
    patient = crud.get_patient(db, patient_id)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No patient with that id.")
    patient = crud.update_patient(db, patient, payload)
    logger.info("patient.updated id=%s", patient.patient_id)
    return {"data": PatientOut.model_validate(patient).model_dump(mode="json"), "error": None}


@router.delete("/{patient_id}", summary="Soft-delete a patient")
def delete_patient(patient_id: str, response: Response, db: Session = Depends(get_db)):
    patient = crud.get_patient(db, patient_id)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No patient with that id.")
    patient = crud.soft_delete_patient(db, patient)
    logger.info("patient.soft_deleted id=%s", patient.patient_id)
    return {
        "data": {
            "patient_id": patient.patient_id,
            "deleted_at": patient.deleted_at.isoformat(),
        },
        "error": None,
    }
