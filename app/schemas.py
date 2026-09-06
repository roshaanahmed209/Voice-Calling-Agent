"""Request/response schemas.

All validation lives here rather than in the voice agent. The agent is a
convenience layer; anything it sends is treated as untrusted input. Normalizers
also absorb the messiness of speech-to-text — "(415) 555-0199", "March 3rd
1990" and "Calif." all arrive here and leave in canonical form.
"""

import re
from datetime import date, datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

T = TypeVar("T")

SexLiteral = Literal["Male", "Female", "Other", "Decline to Answer"]

NAME_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ\-' ]{0,49}$")
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC", "PR", "VI", "GU", "AS", "MP",
}

STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "washington dc": "DC", "puerto rico": "PR",
}

SEX_ALIASES = {
    "m": "Male", "male": "Male", "man": "Male", "boy": "Male",
    "f": "Female", "female": "Female", "woman": "Female", "girl": "Female",
    "o": "Other", "other": "Other", "non-binary": "Other", "nonbinary": "Other",
    "x": "Other",
    "decline": "Decline to Answer", "decline to answer": "Decline to Answer",
    "prefer not to say": "Decline to Answer", "n/a": "Decline to Answer",
    "unspecified": "Decline to Answer",
}


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------

def normalize_phone(raw: str) -> str:
    """Reduce any spoken/typed U.S. number to 10 digits.

    Accepts "(415) 555-0199", "+1 415 555 0199", "415.555.0199".
    Raises ValueError on anything that is not a plausible U.S. number.
    """
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError(
            "Phone number must be a 10-digit U.S. number "
            f"(received {len(digits)} digits)."
        )
    if digits[0] in "01":
        raise ValueError("U.S. area codes cannot begin with 0 or 1.")
    if digits[3] in "01":
        raise ValueError("Invalid U.S. exchange code.")
    return digits


def normalize_dob(raw: str) -> str:
    """Return an ISO date string, rejecting future and implausible dates.

    Accepts MM/DD/YYYY (what the agent is told to send), YYYY-MM-DD,
    MM-DD-YYYY and a few written forms such as "March 3, 1990".
    """
    value = str(raw).strip()
    parsed: date | None = None

    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y",
                "%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y",
                "%d %B %Y"):
        try:
            parsed = datetime.strptime(value, fmt).date()
            break
        except ValueError:
            continue

    if parsed is None:
        raise ValueError("Date of birth must be a valid date in MM/DD/YYYY format.")

    today = date.today()
    if parsed > today:
        raise ValueError("Date of birth cannot be in the future.")
    if parsed.year < 1900:
        raise ValueError("Date of birth must be after 1900.")
    return parsed.isoformat()


def normalize_state(raw: str) -> str:
    value = str(raw).strip()
    if len(value) == 2 and value.upper() in US_STATES:
        return value.upper()
    key = value.lower().replace(".", "").strip()
    if key in STATE_NAMES:
        return STATE_NAMES[key]
    raise ValueError(f"'{raw}' is not a valid U.S. state.")


def normalize_sex(raw: str) -> str:
    value = str(raw).strip()
    if value in ("Male", "Female", "Other", "Decline to Answer"):
        return value
    key = value.lower()
    if key in SEX_ALIASES:
        return SEX_ALIASES[key]
    raise ValueError(
        "Sex must be one of: Male, Female, Other, Decline to Answer."
    )


def normalize_name(raw: str) -> str:
    """Collapse whitespace and repair letter-by-letter spellings.

    Callers who spell out a name land in the transcript as "D A V I S" or
    "D-A-V-I-S"; both collapse to "Davis" here.
    """
    value = re.sub(r"\s+", " ", str(raw).strip())
    if not value:
        raise ValueError("Name cannot be empty.")

    letters_only = value.replace("-", " ").replace(".", " ").split()
    if len(letters_only) > 1 and all(len(part) == 1 for part in letters_only):
        # "D-A-V-I-S" and "D A V I S" both become "Davis".
        value = "".join(letters_only).capitalize()

    if not NAME_RE.match(value):
        raise ValueError(
            "Name must be 1-50 characters, letters plus hyphens or apostrophes."
        )
    return value[0].upper() + value[1:]


def normalize_zip(raw: str) -> str:
    value = re.sub(r"[^\d-]", "", str(raw).strip())
    if len(value) == 9 and "-" not in value:
        value = f"{value[:5]}-{value[5:]}"
    if not ZIP_RE.match(value):
        raise ValueError("ZIP code must be 5 digits or ZIP+4 (12345-6789).")
    return value


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

class Envelope(BaseModel, Generic[T]):
    """Every response uses the same shape: {"data": ..., "error": ...}."""

    data: T | None = None
    error: Any | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Patient schemas
# ---------------------------------------------------------------------------

class PatientBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    first_name: Annotated[str, Field(max_length=50)]
    last_name: Annotated[str, Field(max_length=50)]
    date_of_birth: str
    sex: str
    phone_number: str
    address_line_1: Annotated[str, Field(min_length=1, max_length=200)]
    city: Annotated[str, Field(min_length=1, max_length=100)]
    state: str
    zip_code: str

    email: EmailStr | None = None
    address_line_2: Annotated[str, Field(max_length=200)] | None = None
    insurance_provider: Annotated[str, Field(max_length=120)] | None = None
    insurance_member_id: Annotated[str, Field(max_length=60)] | None = None
    preferred_language: Annotated[str, Field(max_length=50)] = "English"
    emergency_contact_name: Annotated[str, Field(max_length=120)] | None = None
    emergency_contact_phone: str | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def _names(cls, v: str) -> str:
        return normalize_name(v)

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, v: str) -> str:
        return normalize_dob(v)

    @field_validator("sex")
    @classmethod
    def _sex(cls, v: str) -> str:
        return normalize_sex(v)

    @field_validator("phone_number", "emergency_contact_phone")
    @classmethod
    def _phones(cls, v: str | None) -> str | None:
        if v is None or str(v).strip() == "":
            return None
        return normalize_phone(v)

    @field_validator("state")
    @classmethod
    def _state(cls, v: str) -> str:
        return normalize_state(v)

    @field_validator("zip_code")
    @classmethod
    def _zip(cls, v: str) -> str:
        return normalize_zip(v)

    @field_validator(
        "email", "address_line_2", "insurance_provider", "insurance_member_id",
        "emergency_contact_name", mode="before",
    )
    @classmethod
    def _blank_to_none(cls, v: Any) -> Any:
        """The LLM likes to send "" or "none" for fields the caller skipped."""
        if isinstance(v, str) and v.strip().lower() in ("", "none", "n/a", "null", "skip"):
            return None
        return v


class PatientCreate(PatientBase):
    """Body for POST /patients. phone_number is required here."""

    @field_validator("phone_number")
    @classmethod
    def _phone_required(cls, v: str | None) -> str:
        if not v:
            raise ValueError("A phone number is required.")
        return v


class PatientUpdate(BaseModel):
    """Body for PUT /patients/:id. Every field optional — partial updates."""

    model_config = ConfigDict(str_strip_whitespace=True)

    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: str | None = None
    sex: str | None = None
    phone_number: str | None = None
    email: EmailStr | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def _names(cls, v: str | None) -> str | None:
        return normalize_name(v) if v else None

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, v: str | None) -> str | None:
        return normalize_dob(v) if v else None

    @field_validator("sex")
    @classmethod
    def _sex(cls, v: str | None) -> str | None:
        return normalize_sex(v) if v else None

    @field_validator("phone_number", "emergency_contact_phone")
    @classmethod
    def _phones(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else None

    @field_validator("state")
    @classmethod
    def _state(cls, v: str | None) -> str | None:
        return normalize_state(v) if v else None

    @field_validator("zip_code")
    @classmethod
    def _zip(cls, v: str | None) -> str | None:
        return normalize_zip(v) if v else None


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: str
    first_name: str
    last_name: str
    date_of_birth: str
    sex: str
    phone_number: str
    email: str | None
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None
    insurance_member_id: str | None
    preferred_language: str
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    source: str


class TranscriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    call_id: str | None
    caller_number: str | None
    patient_id: str | None
    patient_name: str | None = None
    customer_name: str | None = None
    summary: str | None
    transcript: str | None
    ended_reason: str | None
    duration_seconds: int | None
    direction: str = "inbound"
    status: str = "ended"
    created_at: datetime


class LoginRequest(BaseModel):
    username: str
    password: str


class OutboundCallCreate(BaseModel):
    phone_number: str
    customer_name: str | None = None

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)

    @field_validator("customer_name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None or str(v).strip() == "":
            return None
        return str(v).strip()[:120]
