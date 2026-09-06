"""Integration tests for the REST layer.

Runs against a throwaway SQLite file so it never touches the real database.
"""

import os
import tempfile

import pytest

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["VAPI_SECRET"] = "test-secret"
os.environ["DASHBOARD_USERNAME"] = "admin"
os.environ["DASHBOARD_PASSWORD"] = "test-password"
os.environ["DASHBOARD_SESSION_SECRET"] = "test-session-secret"
os.environ["VAPI_API_KEY"] = "test-vapi-key"
os.environ["VAPI_PHONE_NUMBER_ID"] = "test-phone-id"
os.environ["VAPI_ASSISTANT_ID"] = "test-assistant-id"

from fastapi.testclient import TestClient  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app)
assert client.post("/auth/login", json={"username": "admin", "password": "test-password"}).status_code == 200


def valid_patient(**overrides) -> dict:
    body = {
        "first_name": "Jane",
        "last_name": "Doe",
        "date_of_birth": "05/21/1990",
        "sex": "Female",
        "phone_number": "(415) 555-0199",
        "address_line_1": "12 Elm Street",
        "city": "Berkeley",
        "state": "California",
        "zip_code": "94704",
    }
    body.update(overrides)
    return body


# --- Creation --------------------------------------------------------------

def test_create_returns_201_and_normalizes_input():
    res = client.post("/patients", json=valid_patient())
    assert res.status_code == 201
    data = res.json()["data"]
    assert res.json()["error"] is None
    assert data["phone_number"] == "4155550199"   # punctuation stripped
    assert data["state"] == "CA"                   # full name abbreviated
    assert data["date_of_birth"] == "1990-05-21"   # stored as ISO
    assert data["preferred_language"] == "English"
    assert data["patient_id"]


def test_future_date_of_birth_is_rejected():
    res = client.post("/patients", json=valid_patient(date_of_birth="01/01/2999"))
    assert res.status_code == 422
    assert "future" in res.json()["error"]["fields"]["date_of_birth"].lower()


def test_short_phone_number_is_rejected():
    res = client.post("/patients", json=valid_patient(phone_number="415"))
    assert res.status_code == 422
    assert "date_of_birth" not in res.json()["error"]["fields"]


def test_invalid_state_is_rejected():
    res = client.post("/patients", json=valid_patient(state="Atlantis"))
    assert res.status_code == 422


def test_missing_required_field_is_rejected():
    body = valid_patient()
    del body["city"]
    assert client.post("/patients", json=body).status_code == 422


def test_spelled_out_name_is_joined():
    res = client.post("/patients", json=valid_patient(
        last_name="D-A-V-I-S", phone_number="4155550143"))
    assert res.json()["data"]["last_name"] == "Davis"


def test_blank_optional_fields_become_null():
    res = client.post("/patients", json=valid_patient(
        phone_number="4155550144", insurance_provider="none", address_line_2=""))
    data = res.json()["data"]
    assert data["insurance_provider"] is None
    assert data["address_line_2"] is None


# --- Retrieval -------------------------------------------------------------

def test_get_by_id_and_404_for_unknown():
    created = client.post("/patients", json=valid_patient(
        phone_number="4155550145")).json()["data"]

    found = client.get(f"/patients/{created['patient_id']}")
    assert found.status_code == 200
    assert found.json()["data"]["patient_id"] == created["patient_id"]

    missing = client.get("/patients/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["data"] is None


def test_filters():
    client.post("/patients", json=valid_patient(
        last_name="Nakamura", phone_number="6505550111", date_of_birth="07/04/1978"))

    by_name = client.get("/patients?last_name=nakamura").json()["data"]
    assert len(by_name) == 1

    by_phone = client.get("/patients?phone_number=(650) 555-0111").json()["data"]
    assert by_phone[0]["last_name"] == "Nakamura"

    by_dob = client.get("/patients?date_of_birth=07/04/1978").json()["data"]
    assert by_dob[0]["last_name"] == "Nakamura"


# --- Update ----------------------------------------------------------------

def test_partial_update():
    created = client.post("/patients", json=valid_patient(
        phone_number="4155550146")).json()["data"]

    res = client.put(f"/patients/{created['patient_id']}",
                     json={"city": "Emeryville", "insurance_provider": "Aetna",
                           "next_appointment": "Tuesday at 10:00 AM"})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["city"] == "Emeryville"
    assert data["insurance_provider"] == "Aetna"
    assert data["next_appointment"] == "Tuesday at 10:00 AM"
    assert data["last_name"] == "Doe"  # untouched fields survive


def test_update_rejects_bad_value():
    created = client.post("/patients", json=valid_patient(
        phone_number="4155550147")).json()["data"]
    res = client.put(f"/patients/{created['patient_id']}", json={"state": "ZZ"})
    assert res.status_code == 422


# --- Soft delete -----------------------------------------------------------

def test_delete_is_soft():
    created = client.post("/patients", json=valid_patient(
        phone_number="4155550148")).json()["data"]
    pid = created["patient_id"]

    assert client.delete(f"/patients/{pid}").status_code == 200
    assert client.get(f"/patients/{pid}").status_code == 404

    # The row is still there, just hidden.
    hidden = client.get("/patients?include_deleted=true").json()["data"]
    assert any(p["patient_id"] == pid and p["deleted_at"] for p in hidden)


# --- Voice webhook ---------------------------------------------------------

def tool_call(name: str, arguments: dict, caller: str = "+14155550777") -> dict:
    return {
        "message": {
            "type": "tool-calls",
            "call": {"id": "call-test-1", "customer": {"number": caller}},
            "toolCallList": [{"id": "tc-1", "name": name, "arguments": arguments}],
        }
    }


def test_webhook_requires_the_secret():
    res = client.post("/vapi/webhook", json=tool_call("lookup_patient", {}))
    assert res.status_code == 401


def test_webhook_creates_a_patient():
    res = client.post(
        "/vapi/webhook",
        headers={"x-vapi-secret": "test-secret"},
        json=tool_call("create_patient", valid_patient(phone_number="4155550150")),
    )
    assert res.status_code == 200
    result = res.json()["results"][0]["result"]
    assert "Saved successfully" in result

    stored = client.get("/patients?phone_number=4155550150").json()["data"]
    assert stored[0]["source"] == "voice"


def test_webhook_returns_field_guidance_instead_of_crashing():
    res = client.post(
        "/vapi/webhook",
        headers={"x-vapi-secret": "test-secret"},
        json=tool_call("create_patient", valid_patient(
            date_of_birth="01/01/2999", phone_number="4155550151")),
    )
    assert res.status_code == 200
    result = res.json()["results"][0]["result"]
    assert "not saved" in result
    assert "date_of_birth" in result


def test_webhook_lookup_finds_returning_caller():
    client.post("/patients", json=valid_patient(
        first_name="Rosa", last_name="Pereira", phone_number="3105550123"))

    res = client.post(
        "/vapi/webhook",
        headers={"x-vapi-secret": "test-secret"},
        json=tool_call("lookup_patient", {}, caller="+13105550123"),
    )
    result = res.json()["results"][0]["result"]
    assert "existing record was found" in result
    assert "Rosa Pereira" in result


def test_webhook_uses_caller_id_when_phone_omitted():
    body = valid_patient(first_name="Ada", phone_number="4155550777")
    del body["phone_number"]
    res = client.post(
        "/vapi/webhook",
        headers={"x-vapi-secret": "test-secret"},
        json=tool_call("create_patient", body, caller="+14155550777"),
    )
    assert "Saved successfully" in res.json()["results"][0]["result"]


# --- Auth ------------------------------------------------------------------

def test_patients_require_login():
    bare = TestClient(app)
    assert bare.get("/patients").status_code == 401
    assert bare.get("/calls").status_code == 401
    assert bare.get("/stats").status_code == 401


def test_login_rejects_bad_password():
    bare = TestClient(app)
    res = bare.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert res.status_code == 401


def test_health_stays_public():
    bare = TestClient(app)
    assert bare.get("/health").status_code == 200


# --- Outbound calls --------------------------------------------------------

@patch("app.routers.calls.httpx.Client")
def test_outbound_call_is_logged(mock_client_cls):
    vapi = MagicMock()
    vapi.post.return_value.status_code = 201
    vapi.post.return_value.json.return_value = {"id": "call-out-1", "status": "queued"}
    mock_client_cls.return_value.__enter__.return_value = vapi

    res = client.post("/calls/outbound", json={"phone_number": "5165550199", "customer_name": "Lee Chen"})
    assert res.status_code == 201
    data = res.json()["data"]
    assert data["direction"] == "outbound"
    assert data["caller_number"] == "5165550199"
    assert data["customer_name"] == "Lee Chen"
    assert data["status"] == "queued"

    log = client.get("/calls?direction=outbound").json()["data"]
    assert any(c["call_id"] == "call-out-1" for c in log)


@patch("app.routers.calls.httpx.Client")
def test_outbound_limit_returns_vapi_message(mock_client_cls):
    vapi = MagicMock()
    vapi.post.return_value.status_code = 400
    vapi.post.return_value.json.return_value = {
        "statusCode": 400,
        "message": "Couldn't Start Call. Numbers Bought On Vapi Have A Daily Outbound Call Limit.",
        "error": "Bad Request",
    }
    vapi.post.return_value.text = (
        '{"message":"Could not start call. Numbers Bought On Vapi Have A Daily Outbound Call Limit."}'
    )
    mock_client_cls.return_value.__enter__.return_value = vapi

    res = client.post("/calls/outbound", json={"phone_number": "5165550188"})
    assert res.status_code == 429
    assert "daily outbound-call limit" in res.json()["error"]["message"].lower()


def test_end_of_call_report_stores_duration_and_direction():
    client.post(
        "/vapi/webhook",
        headers={"x-vapi-secret": "test-secret"},
        json={
            "message": {
                "type": "end-of-call-report",
                "endedReason": "assistant-ended-call",
                "durationSeconds": 142,
                "summary": "Registered Lee Chen.",
                "transcript": "Robin: Hi...",
                "call": {
                    "id": "call-in-9",
                    "type": "inboundPhoneCall",
                    "customer": {"number": "+15165550199"},
                },
            }
        },
    )
    calls = client.get("/calls").json()["data"]
    match = next(c for c in calls if c["call_id"] == "call-in-9")
    assert match["duration_seconds"] == 142
    assert match["direction"] == "inbound"
    assert match["status"] == "ended"


# --- Meta ------------------------------------------------------------------

def test_health_and_stats():
    assert client.get("/health").json()["data"]["status"] == "ok"
    stats = client.get("/stats").json()["data"]
    assert stats["patients"] > 0
    assert "outbound_calls" in stats
    assert "total_duration_seconds" in stats


@pytest.mark.parametrize("spoken,expected", [
    ("March 3, 1990", "1990-03-03"),
    ("1990-03-03", "1990-03-03"),
    ("03-03-1990", "1990-03-03"),
])
def test_date_formats_the_agent_might_send(spoken, expected):
    from app.schemas import normalize_dob
    assert normalize_dob(spoken) == expected
