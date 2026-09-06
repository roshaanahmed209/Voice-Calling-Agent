# Voice AI patient registration

A caller dials a phone number, talks to an intake agent named Robin, and gets
registered as a new patient. The record persists to a database and is available
immediately over a REST API and a web dashboard.

## Live endpoints

| What | Where |
| --- | --- |
| Phone number | `+1 (___) ___-____` — fill in after provisioning |
| API base URL | `https://your-app.up.railway.app` |
| Dashboard | `https://your-app.up.railway.app/` |
| API docs (auto-generated) | `https://your-app.up.railway.app/docs` |
| Health check | `https://your-app.up.railway.app/health` |

No credentials are needed to browse the dashboard or read the API. The only
protected route is the Vapi webhook, which requires a shared secret header.

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
- **Transport** is two thin adapters over that service layer:
  `app/routers/patients.py` for REST and `app/routers/vapi_webhook.py` for the
  agent.

The important consequence: the voice agent has no privileged path to the
database. `create_patient` over the phone runs through exactly the same
`PatientCreate` validation and the same `crud.create_patient` as
`POST /patients`. A hallucinated date or a mangled phone number is rejected in
one place, not two.

### Project layout

```
app/
  config.py              env-driven settings
  database.py            engine, session, table creation
  models.py              SQLAlchemy models + DB-level constraints
  schemas.py             validation and speech-to-text normalization
  crud.py                service layer shared by REST and voice
  logging_config.py      stdout + file logging
  main.py                app wiring, error handlers, /health, /stats, /calls
  routers/
    patients.py          the five REST endpoints
    vapi_webhook.py      tool-call handlers and end-of-call reports
  static/dashboard.html  the dashboard (single file, no build step)
prompts/system_prompt.md the agent's prompt, with design rationale
vapi/assistant.json      assistant + tool definitions, version-controlled
scripts/
  provision_vapi.py      push the assistant config to Vapi
  seed.py                two demo records
tests/test_api.py        21 tests covering REST, validation and the webhook
```

---

## Running it

### Local

```bash
git clone <this repo> && cd voice-patient-registration
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then edit — see the table below
python scripts/seed.py        # optional demo records
uvicorn app.main:app --reload
```

Open <http://localhost:8000> for the dashboard, `/docs` for the API.

To let Vapi reach a local server, expose it and set `PUBLIC_BASE_URL` to the
tunnel URL:

```bash
ngrok http 8000
```

### Environment variables

| Variable | Required | What it is |
| --- | --- | --- |
| `DATABASE_URL` | no | Defaults to `sqlite:///./data/patients.db`. Set a Postgres URL for production; Railway injects one automatically when you attach the Postgres plugin. |
| `PUBLIC_BASE_URL` | yes | The public `https://` URL of this service. Vapi calls it, so it cannot be `localhost`. No trailing slash. |
| `VAPI_SECRET` | yes | Any long random string. The same value goes in the Vapi assistant's Server URL Secret field. Requests without it get a 401. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. |
| `VAPI_API_KEY` | no | Only for `scripts/provision_vapi.py`. Vapi → Settings → API Keys (private key). |
| `VAPI_PHONE_NUMBER_ID` | no | Only for `provision_vapi.py --attach`. |
| `LOG_LEVEL` | no | Defaults to `INFO`. |
| `ENVIRONMENT` | no | Cosmetic; appears in the startup log. |

Nothing is hardcoded. If `VAPI_SECRET` is empty the webhook logs a warning and
accepts unauthenticated requests, which is convenient locally and wrong
anywhere else.

### Deploying to Railway

1. Push to GitHub, then **New Project → Deploy from GitHub repo**.
2. **New → Database → Postgres**. Railway sets `DATABASE_URL` for you.
3. Add `PUBLIC_BASE_URL` and `VAPI_SECRET` under Variables.
4. Settings → Networking → **Generate Domain**, and put that domain into
   `PUBLIC_BASE_URL`.
5. Confirm `https://<domain>/health` returns `{"data":{"status":"ok",...}}`.

`railway.json`, `Procfile` and `Dockerfile` are all included — use whichever
your host prefers. Render and Fly.io work from the Dockerfile unchanged.

### Setting up the voice agent

Either run the script:

```bash
python scripts/provision_vapi.py --attach
```

or do it by hand in the Vapi dashboard:

1. Buy a US number under **Phone Numbers**.
2. Create an assistant. Paste `prompts/system_prompt.md` (everything below the
   `## Prompt` heading) as the system message.
3. Add the three tools from `vapi/assistant.json`, each with its server URL set
   to `https://<your-domain>/vapi/webhook` and the secret set to `VAPI_SECRET`.
4. Set the assistant's Server URL to the same webhook and enable the
   `tool-calls` and `end-of-call-report` server messages.
5. Attach the assistant to the number, then call it.

---

## API

Every response uses the same envelope, successes and failures alike:

```json
{ "data": { "...": "..." }, "error": null }
{ "data": null, "error": { "code": "validation_error", "message": "...", "fields": { "date_of_birth": "Date of birth cannot be in the future." } } }
```

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/patients` | Filters: `?last_name=`, `?date_of_birth=`, `?phone_number=`, plus `?limit=`, `?offset=`, `?include_deleted=`. Filters are normalized, so `?phone_number=(415) 555-0199` matches. |
| `GET` | `/patients/{id}` | 404 if unknown or soft-deleted. |
| `POST` | `/patients` | 201 with the created record. 422 on validation failure. |
| `PUT` | `/patients/{id}` | Partial updates; send only changed fields. |
| `DELETE` | `/patients/{id}` | Soft delete — sets `deleted_at`, never removes the row. |
| `GET` | `/calls` | Stored call transcripts and summaries. |
| `GET` | `/stats` | Counts used by the dashboard. |
| `GET` | `/health` | Includes a live database check. |

Status codes in use: 200, 201, 400 (a filter value that cannot be parsed, such
as `?phone_number=abc`), 401 (webhook secret), 404, 422 (body validation, and
query parameters of the wrong type such as `?limit=abc`), 500.

```bash
curl -X POST https://your-app.up.railway.app/patients \
  -H 'content-type: application/json' \
  -d '{"first_name":"Jane","last_name":"Doe","date_of_birth":"05/21/1990",
       "sex":"Female","phone_number":"(415) 555-0199",
       "address_line_1":"12 Elm Street","city":"Berkeley",
       "state":"California","zip_code":"94704"}'
```

That request stores `4155550199`, `CA`, and `1990-05-21` — input normalization
is described below.

---

## Data model

Stored in the `patients` table, matching the required minimum demographic set.
`patient_id` is a UUID, `created_at` / `updated_at` are UTC timestamps managed
by the ORM, and `deleted_at` implements soft deletion. One extra column,
`source`, records whether a row arrived by phone, by API, or from the seed
script — it makes the dashboard honest about provenance and made testing the
integration much easier.

Dates are stored as ISO `YYYY-MM-DD` strings rather than a native date type.
That keeps SQLite and Postgres behaving identically and keeps the JSON contract
stable; the cost is that date range queries would need a cast. Given that the
only date filter in the spec is exact match, that trade seemed right.

Constraints exist at two levels: Pydantic validators on the way in, plus
`CHECK` constraints and column lengths in the table itself, so a direct SQL
insert still cannot store a 7-digit phone number.

### Speech-to-text normalization

The agent is instructed to send canonical formats, but LLMs drift and
transcription is noisy, so the server repairs what it safely can and rejects
the rest. All of it lives in `app/schemas.py`:

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

The full prompt and the reasoning behind each rule are in
`prompts/system_prompt.md`. The short version:

- One question at a time, with a brief acknowledgement, so mishearings surface
  immediately instead of compounding.
- Names are always spelled back. Speech-to-text is worst on proper nouns.
- The caller's inbound number is known from Vapi, so the agent confirms it
  rather than asking anyone to recite ten digits aloud.
- Optional fields are offered once as a single opt-in, not asked one by one.
- Everything is read back in a natural sentence before saving. Corrections
  amend one field and re-confirm only that field.
- The agent is told explicitly never to claim a registration succeeded unless
  the tool confirmed it, and the tool responses reinforce that in their wording.

Tool results are written as short instructions to the model rather than as raw
JSON, because the model reads them and acts on them. A rejected write returns
`"...not saved because some fields need correcting: date_of_birth: Date of
birth cannot be in the future. Ask the caller only about those specific
fields..."` — which produces a targeted re-prompt rather than a restart.

---

## Edge cases

| Situation | Behaviour |
| --- | --- |
| Future or malformed date of birth | 422 with a field-specific message; agent re-asks for that field only. |
| Three-digit phone number | Rejected with the digit count in the message; agent asks for the area code. |
| Caller corrects a spelling mid-call | Agent amends the one field and re-confirms just that field. |
| Caller answers a question that hasn't been asked | Prompt instructs the agent to keep it and skip that question later. |
| Database write fails | Handler catches it, logs the traceback, and returns a result telling the agent to apologise and say the data was not saved. The caller never gets silence, and never gets a false confirmation. |
| Call drops mid-registration | Nothing is written until confirmation, so no partial records. The `end-of-call-report` still stores a transcript with the `endedReason`. |
| Caller asks to start over | Prompt instructs the agent to discard and restart from the first name. |
| Returning caller | `lookup_patient` runs before collection; if the number matches, the agent offers to update instead of creating a duplicate. |
| Unauthenticated webhook request | 401 before any handler runs. |
| Unknown tool name | Logged and returned as an error string rather than a 500. |

---

## Observability

Every tool call, every accepted write, and every rejection is logged to stdout
and to `logs/app.log`:

```
INFO  vapi   voice.tool name=create_patient args={"first_name": "Maria", ...}
INFO  vapi   voice.create.ok id=310edfad-... payload={"first_name": "Maria", "last_name": "Davis", ...}
INFO  vapi   voice.create.rejected errors={'date_of_birth': 'Date of birth cannot be in the future.'}
```

`railway logs` shows the full collected payload for each call. Transcripts and
end-of-call summaries are stored in `call_transcripts` and served at `/calls`.

---

## Tests

```bash
pytest
```

21 tests against a throwaway SQLite database, covering all five endpoints,
every normalizer, soft-delete semantics, webhook authentication, duplicate
detection, and the agent-sends-garbage path.

---

## Trade-offs and known limitations

Deliberate choices, with what I'd do differently given more time:

- **`create_all()` instead of Alembic.** Fine for a fresh deploy, useless for
  schema evolution. A real service needs migrations from day one.
- **SQLite by default, Postgres in production.** The default gets someone
  running with zero setup. SQLite on an ephemeral container filesystem does not
  survive redeploys, which is why the deploy instructions attach Postgres.
- **No authentication on the REST API.** The brief asks for a callable demo, so
  every endpoint is open. Any real deployment needs auth on everything, and the
  patient data would be a compliance boundary rather than a table.
- **Data is not encrypted at rest and the service is not HIPAA-compliant.** Out
  of scope per the brief. Do not put real patient data in it.
- **Duplicate detection keys on phone number alone.** Shared household numbers
  would collide. Name plus date of birth would be the better key.
- **No rate limiting on the webhook.** The shared secret is the only control.
- **The dashboard polls every 15 seconds.** Server-sent events would be nicer;
  polling was three lines.
- **Transcripts link to patients by phone number**, so a call that ends before
  registration is stored unlinked.
- **Single-instance assumptions.** No background workers, no queue. A failed
  database write is surfaced to the caller rather than retried.

## Next steps

1. Alembic migrations and a proper `date` column type.
2. API-key auth plus per-IP rate limiting.
3. Retry with backoff on transient database failures, so a blip doesn't cost
   the caller their registration.
4. Spanish support — the prompt scaffolding is there, it needs a second voice
   and a language switch on `preferred_language`.
5. Appointment scheduling after registration.
6. A confirmation SMS with the record ID.
7. Eval harness: replay recorded call transcripts against the prompt to catch
   regressions when the prompt changes.
"# Voice-Calling-Agent" 
