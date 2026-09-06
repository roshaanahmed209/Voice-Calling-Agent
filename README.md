# Voice AI patient registration

A caller dials a phone number, talks to an intake agent named Robin, and gets
registered as a new patient. The record persists to a database and is available
immediately over a REST API and a web dashboard.

## Reviewer notes

| What | Where |
| --- | --- |
| Phone number | `+1 (516) 583-1185` |
| Dashboard (local) | http://localhost:8000 |
| Dashboard login | username `admin` / password `CareCloud2026!` |
| API docs | http://localhost:8000/docs |
| Health check | `GET /health` — public, no login |

After you deploy to Railway, put that domain in `PUBLIC_BASE_URL`, re-run
`python scripts/provision_vapi.py --attach`, and replace the local URLs above
with `https://<your-railway-domain>`.

The dashboard, patient API, call log, and stats require a session cookie.
`/health` and `POST /vapi/webhook` stay public (the webhook uses `VAPI_SECRET`).

```bash
curl -c cookies.txt -X POST http://localhost:8000/auth/login \
  -H "content-type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"CareCloud2026!\"}"

curl -b cookies.txt http://localhost:8000/patients
curl -b cookies.txt http://localhost:8000/stats
```

---

## Architecture

```
   Caller
     │  PSTN
     ▼
┌─────────────────┐   tool call (HTTPS + shared secret)   ┌──────────────────┐
│  Vapi           │ ────────────────────────────────────► │  FastAPI service │
│  number + STT   │                                        │                  │
│  + GPT-4o + TTS │ ◄──────────────────────────────────── │  /vapi/webhook   │
└─────────────────┘   plain-language result for the LLM    │       │          │
                                                           │       ▼          │
                                              ┌────────────┤  service layer   │
                                              │            │   (app/crud.py)  │
                                              │            │       │          │
                                              ▼            │       ▼          │
                                     ┌─────────────────┐   │   SQLAlchemy     │
                                     │ /patients REST  │───┤       │          │
                                     │ /calls, /stats  │   └───────┼──────────┘
                                     └────────┬────────┘           ▼
                                              │            ┌──────────────────┐
                                              ▼            │ Postgres/SQLite  │
                                     ┌─────────────────┐   └──────────────────┘
                                     │ Dashboard (SPA) │
                                     └─────────────────┘
```

Four layers, each with one job:

- **Telephony and speech** are entirely Vapi's. The service never touches audio.
- **Conversation logic** is the system prompt plus three tool definitions
  (`prompts/system_prompt.md`, `vapi/assistant.json`).
- **Domain logic and validation** live in `app/schemas.py` and `app/crud.py`.
- **Transport** is thin adapters over that service layer:
  `app/routers/patients.py` for REST, `app/routers/vapi_webhook.py` for the
  agent, and `app/routers/calls.py` for the call log / outbound dialer.

The important consequence: the voice agent has no privileged path to the
database. `create_patient` over the phone runs through exactly the same
`PatientCreate` validation and the same `crud.create_patient` as
`POST /patients`.

### Project layout

```
app/
  auth.py                cookie sessions for the dashboard
  config.py              env-driven settings
  database.py            engine, session, lightweight column adds
  models.py              SQLAlchemy models + DB-level constraints
  schemas.py             validation and speech-to-text normalization
  crud.py                service layer shared by REST and voice
  logging_config.py      stdout + file logging
  main.py                app wiring, error handlers, /health, /stats
  routers/
    auth.py              login / logout / me
    patients.py          the five REST endpoints
    calls.py             call log, outbound phone, browser-call config
    vapi_webhook.py      tool-call handlers and end-of-call reports
  static/dashboard.html  login + tabbed dashboard (no build step)
prompts/system_prompt.md the agent's prompt, with design rationale
vapi/assistant.json      assistant + tool definitions, version-controlled
scripts/
  provision_vapi.py      push the assistant config to Vapi
  seed.py                two demo records
tests/test_api.py        REST, validation, webhook, auth, outbound errors
```

---

## Running it

### Local

```bash
cd voice-patient-registration
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # then edit — see the table below
python scripts/seed.py        # optional demo records
uvicorn app.main:app --reload
```

Open http://localhost:8000 and sign in. `/docs` is the API explorer.

To let Vapi reach a local server, expose it and set `PUBLIC_BASE_URL` to the
tunnel URL, then re-provision:

```bash
ngrok http 8000
# or: .\data\cloudflared.exe tunnel --url http://127.0.0.1:8000
python scripts/provision_vapi.py --attach
```

### Environment variables

| Variable | Required | What it is |
| --- | --- | --- |
| `DATABASE_URL` | no | Defaults to `sqlite:///./data/patients.db`. Set a Postgres URL for production; Railway injects one when you attach Postgres. |
| `PUBLIC_BASE_URL` | yes | Public `https://` URL of this service. Vapi calls it, so it cannot be `localhost`. No trailing slash. |
| `VAPI_SECRET` | yes | Shared secret for `POST /vapi/webhook`. Same value in the Vapi assistant Server URL Secret. |
| `VAPI_API_KEY` | yes for outbound / provision | Vapi private key. |
| `VAPI_PUBLIC_KEY` | yes for browser calls | Vapi public key. |
| `VAPI_PHONE_NUMBER_ID` | yes for outbound | Vapi phone number id. |
| `VAPI_ASSISTANT_ID` | yes for outbound / browser | Assistant id. |
| `DASHBOARD_USERNAME` | yes | Dashboard / API login. |
| `DASHBOARD_PASSWORD` | yes | Dashboard / API password. |
| `DASHBOARD_SESSION_SECRET` | yes | Signs the session cookie. |
| `LOG_LEVEL` | no | Defaults to `INFO`. |
| `ENVIRONMENT` | no | Cosmetic; appears in the startup log. |

Nothing is hardcoded. If `VAPI_SECRET` is empty the webhook logs a warning and
accepts unauthenticated requests, which is convenient locally and wrong
anywhere else.

### Deploying to Railway

1. Push to GitHub, then **New Project → Deploy from GitHub repo**.
2. **New → Database → Postgres**. Railway sets `DATABASE_URL` for you.
3. Add `PUBLIC_BASE_URL`, `VAPI_SECRET`, `VAPI_API_KEY`, `VAPI_PUBLIC_KEY`,
   `VAPI_PHONE_NUMBER_ID`, `VAPI_ASSISTANT_ID`, and the `DASHBOARD_*` variables.
4. Settings → Networking → **Generate Domain**, and put that domain into
   `PUBLIC_BASE_URL`.
5. Confirm `https://<domain>/health` returns `{"data":{"status":"ok",...}}`.
6. Run `python scripts/provision_vapi.py --attach` so the assistant webhook
   points at the Railway URL.

`railway.json`, `Procfile` and `Dockerfile` are included.

### Setting up the voice agent

```bash
python scripts/provision_vapi.py --attach
```

Or in the Vapi dashboard: paste `prompts/system_prompt.md` (below `## Prompt`),
point tools and the server URL at `https://<your-domain>/vapi/webhook`, set the
secret to `VAPI_SECRET`, enable `tool-calls` and `end-of-call-report`, attach
the assistant to `+15165831185`.

---

## API

Every response uses the same envelope, successes and failures alike:

```json
{ "data": { "...": "..." }, "error": null }
{ "data": null, "error": { "code": "validation_error", "message": "...", "fields": { "date_of_birth": "Date of birth cannot be in the future." } } }
```

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `POST` | `/auth/login` | no | Sets the `cc_session` cookie. |
| `POST` | `/auth/logout` | no | Clears the cookie. |
| `GET` | `/auth/me` | cookie | Current user. |
| `GET` | `/patients` | cookie | Filters: `?last_name=`, `?date_of_birth=`, `?phone_number=`, plus `?limit=`, `?offset=`, `?include_deleted=`. |
| `GET` | `/patients/{id}` | cookie | 404 if unknown or soft-deleted. |
| `POST` | `/patients` | cookie | 201 with the created record. 422 on validation failure. |
| `PUT` | `/patients/{id}` | cookie | Partial updates; send only changed fields. |
| `DELETE` | `/patients/{id}` | cookie | Soft delete — sets `deleted_at`. |
| `GET` | `/calls` | cookie | Transcripts, duration, inbound/outbound. `?direction=outbound`. |
| `POST` | `/calls/outbound` | cookie | Place an outbound phone call via Vapi. |
| `GET` | `/stats` | cookie | Counts used by the dashboard. |
| `GET` | `/health` | no | Includes a live database check. |
| `POST` | `/vapi/webhook` | `x-vapi-secret` | Voice tool calls and end-of-call reports. |

Status codes in use: 200, 201, 400, 401, 404, 422, 429 (Vapi outbound daily
limit), 500, 502.

```bash
curl -b cookies.txt -X POST http://localhost:8000/patients \
  -H "content-type: application/json" \
  -d "{\"first_name\":\"Jane\",\"last_name\":\"Doe\",\"date_of_birth\":\"05/21/1990\",
       \"sex\":\"Female\",\"phone_number\":\"(415) 555-0199\",
       \"address_line_1\":\"12 Elm Street\",\"city\":\"Berkeley\",
       \"state\":\"California\",\"zip_code\":\"94704\"}"
```

That request stores `4155550199`, `CA`, and `1990-05-21`.

---

## Data model

Stored in the `patients` table, matching the required minimum demographic set.
`patient_id` is a UUID, `created_at` / `updated_at` are UTC timestamps, and
`deleted_at` implements soft deletion. Extra columns: `source` (voice / api /
seed) and `next_appointment` (mock first-visit slot booked on the call).

Dates are stored as ISO `YYYY-MM-DD` strings rather than a native date type so
SQLite and Postgres behave the same. The only date filter in the spec is exact
match.

Constraints exist at two levels: Pydantic validators on the way in, plus
`CHECK` constraints and column lengths in the table itself.

### Speech-to-text normalization

| Caller says / agent sends | Stored |
| --- | --- |
| `(415) 555-0199`, `+1 415 555 0199` | `4155550199` |
| `March 3, 1990`, `03/03/1990` | `1990-03-03` |
| `California`, `calif.` | `CA` |
| `D-A-V-I-S`, `D A V I S` | `Davis` |
| `female`, `f` | `Female` |
| `904015512` | `90401-5512` |
| `""`, `"none"`, `"n/a"` for an optional field | `null` |

Rejected outright, with a per-field message the agent reads back: future dates,
numbers that aren't ten digits, area codes starting 0 or 1, invalid states,
malformed ZIPs.

---

## Conversation design

The full prompt is in `prompts/system_prompt.md`. The short version:

- One question at a time, with a brief acknowledgement.
- Names are always spelled back.
- Caller ID is confirmed instead of reciting ten digits.
- Optional fields are one opt-in, not a laundry list.
- Full natural read-back before save.
- Never claim success unless the tool confirmed it.
- Returning callers are looked up by phone and offered an update.
- After a successful save, Robin offers two mock first-visit slots
  (Tuesday 10:00 AM or Thursday 2:30 PM) and stores the choice.
- If the caller says "Hablo español", Robin switches to Spanish and sets
  `preferred_language`.

Tool results are written as short instructions to the model. A rejected write
returns a field-specific re-prompt rather than a restart.

---

## Edge cases

| Situation | Behaviour |
| --- | --- |
| Future or malformed date of birth | 422 with a field-specific message; agent re-asks for that field only. |
| Three-digit phone number | Rejected with the digit count; agent asks for the area code. |
| Caller corrects a spelling mid-call | Agent amends the one field and re-confirms just that field. |
| Caller answers a question that hasn't been asked | Prompt keeps it and skips that question later. |
| Database write fails | Agent apologises and says it was not saved. No false confirmation. |
| Call drops mid-registration | Nothing is written until confirmation. Transcript still stored. |
| Caller asks to start over | Discard and restart from the first name. |
| Returning caller | `lookup_patient` offers update instead of a duplicate. |
| Unauthenticated webhook | 401 before any handler runs. |
| Vapi-bought number hits daily outbound cap | 429 with a clear message. Inbound and browser calls still work. |

---

## Observability

Every tool call, accepted write, and rejection is logged to stdout and
`logs/app.log`:

```
INFO  vapi   voice.tool name=create_patient args={"first_name": "Maria", ...}
INFO  vapi   voice.create.ok id=310edfad-... payload={"first_name": "Maria", ...}
INFO  vapi   voice.create.rejected errors={'date_of_birth': 'Date of birth cannot be in the future.'}
```

Transcripts and end-of-call summaries are stored in `call_transcripts` and
served at `/calls`.

---

## Tests

```bash
pytest
```

Integration tests against a throwaway SQLite database: the five patient
endpoints, normalizers, soft-delete, webhook auth, duplicate detection, login,
and outbound error handling.

---

## Trade-offs and known limitations

- **`create_all()` plus a few `ALTER TABLE`s instead of Alembic.** Fine for a
  fresh deploy; a real service needs migrations from day one.
- **SQLite by default, Postgres in production.** SQLite on an ephemeral
  container disk does not survive redeploys — attach Postgres on Railway.
- **Dashboard login protects the REST API.** Reviewers need the cookie (or the
  dashboard). `/health` and the Vapi webhook stay public.
- **Not HIPAA-compliant.** Out of scope per the brief. Do not store real
  patient data.
- **Duplicate detection keys on phone number alone.** Household numbers collide.
- **Vapi-provisioned numbers have a daily outbound-call limit.** Inbound calling
  is the path the brief grades. Browser calls do not use that quota.
- **Dashboard polls every 15 seconds.**
- **Transcripts link to patients by phone**, so a call that ends before
  registration is stored unlinked.
- **Appointments are mock slots**, stored as a string on the patient record.

## Next steps

1. Alembic migrations and a native `date` column.
2. Per-IP rate limiting on the webhook.
3. Retry with backoff on transient database failures.
4. A second Spanish voice on Vapi when `preferred_language` is Spanish.
5. A confirmation SMS with the record ID.
6. Eval harness: replay transcripts against the prompt when it changes.
