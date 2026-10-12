# Urban Sentinel — Milestone 1: FastAPI + Multi-Source Event Ingestion

**UrbanIncident Fusion & Causal Intelligence**

An uncertainty-aware urban incident engine that fuses heterogeneous, time-stamped signals into
evolving incidents, keeps competing explanations visible, estimates cascade risk, and explains
evidence-backed interventions.

> **Status: Milestone 1 only.** This repository currently implements the *ingestion and
> canonicalisation* subsystem: the FastAPI application, the versioned canonical event contract,
> five source adapters (weather, air quality, traffic, water levels, citizen reports), a
> deterministic replay engine, idempotent PostgreSQL persistence, source-health tracking, and
> ingestion-run accounting.
>
> **Anomaly detection, incident clustering/fusion, causal inference, cascade-risk prediction,
> the Neo4j evidence graph, and LangGraph agents are NOT implemented.** See
> [Scope status](#12-scope-status--what-is-and-is-not-implemented). Nothing in this codebase
> reports those capabilities as working.

> **This repository contains two subsystems, each a separate FastAPI app:**
>
> | Package | Subsystem | Start | Tests |
> |---|---|---|---|
> | `app/` | Milestone 1 — multi-source event ingestion (this document, §1–14) | `uvicorn app.main:app --port 8000` | `tests/*.py` |
> | `urban_sentinel/` | Multi-agent intelligence layer (LangGraph) — see [Part 2](#part-2--multi-agent-intelligence-layer) | `uvicorn urban_sentinel.api.main:app --port 8001` | `tests/intelligence/` |
>
> **They are now wired into one pipeline served by `app.main`:**
> ingestion → deterministic processing (`app/processing/`) → intelligence layer (mounted
> in-process). See [Part 1b](#part-1b--deterministic-processing-and-wiring).
> `python -m pytest` runs every suite (269 tests).

---

## Table of contents

1. [What this milestone does](#1-what-this-milestone-does)
2. [Repository layout](#2-repository-layout)
3. [Technology stack](#3-technology-stack)
4. [Setup](#4-setup)
5. [Environment configuration](#5-environment-configuration)
6. [Database setup and migrations](#6-database-setup-and-migrations)
7. [Running the server](#7-running-the-server)
8. [API reference and examples](#8-api-reference-and-examples)
9. [Canonical event contract](#9-canonical-event-contract)
10. [Deterministic replay](#10-deterministic-replay)
11. [Running the tests](#11-running-the-tests)
12. [Scope status — what is and is not implemented](#12-scope-status--what-is-and-is-not-implemented)
13. [Design principles and known limitations](#13-design-principles-and-known-limitations)

---

## 1. What this milestone does

| Capability | Status |
|---|---|
| FastAPI app with lifespan, structured logging, request correlation IDs | Implemented |
| Versioned canonical event schema (Pydantic v2, `schema_version = 1.0`) | Implemented |
| Weather adapter (OpenWeather, async, live + replay) | Implemented — live path unverified (no key) |
| Air-quality adapter (OpenAQ v3, async, paginated) | Implemented — live path unverified (no key) |
| Traffic adapter (TomTom-shaped, free-flow ratio guarded) | Implemented — live path unverified (no key) |
| Water-level adapter (CSV/JSON dataset + documented mapping) | Implemented — replay/dataset path only |
| Citizen-report adapter + `POST /api/v1/reports` | Implemented |
| Deterministic replay engine, stable event identity | Implemented |
| Validation with machine-readable reason codes + quarantine | Implemented |
| Atomic idempotency (DB unique constraints, not read-before-write) | Implemented |
| Duplicate receipts (traceable, never counted as corroboration) | Implemented |
| Late/out-of-order event acceptance with preserved `event_time` | Implemented |
| Source-health state machine + freshness tracking | Implemented |
| Ingestion-run accounting (accepted/rejected/quarantined/duplicate) | Implemented |
| Per-source failure isolation | Implemented |
| API-key authorisation on mutating endpoints | Implemented |
| Secret redaction in logs and API responses | Implemented |
| Alembic migrations | Implemented |
| Automated test suite (no network, no credentials) | Implemented |

---

## 2. Repository layout

```
RGIT/
├── README.md
├── pyproject.toml
├── requirements.txt
├── alembic.ini
├── .env.example                 # placeholders only — never real values
├── .gitignore                   # excludes .env and local secrets
├── app/
│   ├── main.py                  # FastAPI app factory + lifespan
│   ├── core/
│   │   ├── config.py            # pydantic-settings configuration
│   │   ├── logging.py           # JSON structured logs + correlation + redaction
│   │   ├── errors.py            # error envelope + domain exceptions
│   │   ├── security.py          # API-key auth, scopes, secret redaction
│   │   └── timeutil.py          # UTC normalisation, timezone-aware parsing
│   ├── schemas/
│   │   ├── common.py            # envelopes, pagination, source enums
│   │   ├── event.py             # CANONICAL EVENT CONTRACT
│   │   ├── source.py            # source + source-health schemas
│   │   ├── ingestion.py         # ingestion run + result schemas
│   │   └── report.py            # citizen report schemas
│   ├── api/
│   │   ├── deps.py              # DB session, auth, pagination deps
│   │   ├── health.py            # GET /health
│   │   ├── events.py            # event submit + query + detail
│   │   ├── sources.py           # source list, health, trigger ingest, runs
│   │   └── reports.py           # citizen report submission
│   ├── ingestion/
│   │   ├── base.py              # SourceAdapter contract + AdapterResult
│   │   ├── registry.py          # source_id -> adapter resolution
│   │   ├── http.py              # shared httpx client: timeout, retry, backoff
│   │   ├── openweather.py       # weather
│   │   ├── openaq.py            # air quality
│   │   ├── traffic.py           # traffic
│   │   ├── water.py             # water levels (CSV/JSON dataset)
│   │   ├── citizen.py           # citizen reports
│   │   └── replay.py            # deterministic fixture replay
│   ├── services/
│   │   ├── event_service.py     # validate -> dedupe -> persist orchestration
│   │   ├── source_health.py     # health transitions
│   │   └── ingestion_runner.py  # run lifecycle, isolation, scheduling loop
│   ├── db/
│   │   ├── base.py
│   │   ├── session.py           # async engine/sessionmaker
│   │   ├── models.py            # SQLAlchemy 2.0 mapped classes
│   │   └── repositories/
│   │       ├── event_repository.py
│   │       ├── ingestion_run_repository.py
│   │       ├── source_repository.py
│   │       └── duplicate_repository.py
│   └── processing/
│       └── __init__.py          # deliberate seam for Milestone 2
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── data/samples/                # sanitised fixtures for all five categories
├── scripts/
│   ├── provision_db.ps1
│   └── provision_db.sh
└── tests/
```

---

## 3. Technology stack

- **Python 3.11** (see [Deviations](#13-design-principles-and-known-limitations) — Python 3.12 was requested but is not installed on this machine)
- **FastAPI** + **Uvicorn**
- **Pydantic v2** + **pydantic-settings**
- **SQLAlchemy 2.0** (async) with **asyncpg** (PostgreSQL) / **aiosqlite** (tests)
- **httpx** for async provider calls
- **Alembic** for migrations
- **pytest**, **pytest-asyncio**, **pytest-httpx**, **pytest-cov**

**PostGIS / GeoAlchemy2 is deliberately not used yet.** Milestone 1 stores latitude/longitude as
numeric columns plus an optional GeoJSON reference string; no spatial query is required until
candidate retrieval (Milestone 2), where a real spatial index becomes worthwhile. Adding it
later is additive.

---

## 4. Setup

```powershell
# from the repository root
cd C:\Users\mouse\OneDrive\Desktop\RGIT

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then create your local environment file:

```powershell
Copy-Item .env.example .env
```

`.env` is git-ignored. **Never commit it.** Fill in only the provider keys you actually have;
every connector degrades to a clearly-labelled replay mode when its key is absent.

---

## 5. Environment configuration

All variables are optional except where marked required. Names only — values are never logged,
printed, or returned by the API.

### Core

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `urban-sentinel` | Service name |
| `APP_ENV` | `development` | `development` / `test` / `production` |
| `DEBUG` | `false` | Verbose errors |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address |
| `LOG_LEVEL` | `INFO` | Log level |
| `LOG_FORMAT` | `json` | `json` or `console` |
| `TIMEZONE_DISPLAY` | `Asia/Kolkata` | Label timezone for rendering |
| `CORS_ORIGINS` | *(empty)* | Comma-separated allowed origins |
| `MAX_PAYLOAD_BYTES` | `262144` | Hard cap on submitted payload size |

### Database

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | *(none — required)* | Async SQLAlchemy URL, e.g. `postgresql+asyncpg://user:pass@127.0.0.1:5432/urban_sentinel` |
| `DB_POOL_SIZE` | `5` | Connection pool size |
| `DB_MAX_OVERFLOW` | `10` | Pool overflow |
| `DB_ECHO` | `false` | SQL echo (never enable with secrets) |

For tests, set `DATABASE_URL=sqlite+aiosqlite:///./test.db` — or simply let the test suite
override it in-process.

### Authentication

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_ENABLED` | `true` | Enforce API keys on mutating routes |
| `API_WRITE_KEY` | *(none)* | Required to ingest, submit events/reports |
| `API_READ_KEY` | *(none)* | Optional; public reads are allowed without it |

### Provider credentials

| Variable | Used by | If missing |
|---|---|---|
| `OPENWEATHER_API_KEY` | Weather | Weather adapter reports `missing_credential`; replay works |
| `OPENAQ_API_KEY` | Air quality | Air-quality adapter reports `missing_credential`; replay works |
| `TOMTOM_API_KEY` | Traffic | Traffic adapter reports `missing_credential`; replay works |
| `WATER_API_KEY` / `WATER_DATASET_PATH` | Water levels | Falls back to the bundled CSV dataset in replay |
| `WEATHER_LAT` / `WEATHER_LON` | Weather | Required for live weather |
| `AQ_LAT` / `AQ_LON` / `AQ_RADIUS_M` | Air quality | Required for live OpenAQ |
| `TRAFFIC_LAT` / `TRAFFIC_LON` | Traffic | Required for live traffic |
| `TRAFFIC_SEGMENT_IDS` | Traffic | Comma-separated road segment ids |
| `WATER_MAPPING_PATH` | Water | Column-mapping JSON for CSV datasets |

### HTTP client behaviour

| Variable | Default |
|---|---|
| `HTTP_TIMEOUT_SECONDS` | `20.0` |
| `HTTP_MAX_RETRIES` | `3` |
| `HTTP_BACKOFF_BASE_SECONDS` | `0.5` |
| `HTTP_BACKOFF_MAX_SECONDS` | `8.0` |
| `HTTP_USER_AGENT` | `urban-sentinel/0.1` |

### Replay and scheduling

| Variable | Default | Purpose |
|---|---|---|
| `REPLAY_FIXTURES_DIR` | `./data/samples` | Fixture directory |
| `REPLAY_SHUFFLE_SEED` | `1337` | Seed for deterministic out-of-order replay |
| `SCHEDULER_ENABLED` | `false` | Periodic polling — **off by default** |
| `SCHEDULER_SOURCES` | `replay` | Comma-separated sources to poll |
| `SCHEDULER_INTERVAL_SECONDS` | `300` | Poll interval |

> `SCHEDULER_ENABLED` defaults to `false` so a local run can never silently consume a paid API
> quota.

---

## 6. Database setup and migrations

### 6.1 Provision the database (one-time, needs the PostgreSQL superuser password)

Do **not** run this inside the application. It creates a dedicated role and database:

```powershell
# Windows
$env:PGPASSWORD = "<your-postgres-superuser-password>"
.\scripts\provision_db.ps1 -Database urban_sentinel -User urban_sentinel -Password "<choose-a-strong-password>"
```

```bash
# macOS / Linux
export PGPASSWORD="<your-postgres-superuser-password>"
./scripts/provision_db.sh urban_sentinel urban_sentinel "<choose-a-strong-password>"
```

The script issues `CREATE ROLE` and `CREATE DATABASE` only, and grants `CREATE` on the public
schema. It never prints the password.

### 6.2 Apply migrations

```powershell
$env:DATABASE_URL = "postgresql+asyncpg://urban_sentinel:<password>@127.0.0.1:5432/urban_sentinel"
.\.venv\Scripts\alembic.exe upgrade head
```

Verify:

```powershell
.\.venv\Scripts\alembic.exe current
```

Migrations are plain Alembic revisions and run cleanly from an empty database.
`tests/test_migrations.py` runs `upgrade → alembic check → downgrade → upgrade` on every test run,
so the migration can never silently drift from the ORM models. To reset:

```powershell
.\.venv\Scripts\alembic.exe downgrade base
.\.venv\Scripts\alembic.exe upgrade head
```

---

## 7. Running the server

```powershell
$env:DATABASE_URL = "postgresql+asyncpg://urban_sentinel:<password>@127.0.0.1:5432/urban_sentinel"
$env:API_WRITE_KEY = "dev-write-key"
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

Then open:

- **Interactive docs:** <http://127.0.0.1:8000/docs>
- **OpenAPI JSON:** <http://127.0.0.1:8000/openapi.json>
- **Health:** <http://127.0.0.1:8000/health>

---

## 8. API reference and examples

All responses share one envelope:

```json
{
  "data": { "...": "..." },
  "meta": { "request_id": "0f3c...", "generated_at": "2026-10-12T10:00:00Z" },
  "error": null
}
```

Errors use the same envelope with `error` populated:

```json
{
  "data": null,
  "meta": { "request_id": "0f3c..." },
  "error": {
    "code": "validation_failed",
    "message": "Request validation failed",
    "field_errors": [{ "field": "location.latitude", "message": "must be <= 90" }],
    "retryable": false
  }
}
```

### Endpoints

| Method | Route | Auth | Purpose |
|---|---|---|---|
| `GET` | `/health` | public | Liveness + dependency readiness |
| `GET` | `/api/v1/sources` | public | Configured sources and their modes |
| `GET` | `/api/v1/sources/health` | public | Health, freshness, counters, error state |
| `POST` | `/api/v1/ingest/{source}` | **write** | Trigger one ingestion run. `{source}` is a full id (`weather.live`, `airquality.live`, `traffic.live`, `water.dataset`, `citizen.manual`, `replay.all`) or an unambiguous alias (`weather`, `air_quality`, `traffic`, `water`, `citizen`, `replay`) |
| `POST` | `/api/v1/events` | **write** | Submit canonical or manual events |
| `POST` | `/api/v1/reports` | **write** | Submit a citizen report |
| `POST` | `/api/v1/verification/image` | public or read-keyed | Bounded image triage with the optional XproAI checkpoint and C2PA SDK |
| `GET` | `/api/v1/events` | public | Paginated/filtered event query |
| `GET` | `/api/v1/events/{event_id}` | public | Event detail and provenance |
| `GET` | `/api/v1/ingestion/runs` | public | Recent ingestion runs and outcomes |

### Examples

**Trigger replay ingestion**

```bash
curl -X POST http://127.0.0.1:8000/api/v1/ingest/replay \
  -H "X-API-Key: dev-write-key" \
  -H "Content-Type: application/json" \
  -d '{"fixture": "monsoon_waterlogging", "shuffle": false}'
```

**Submit a citizen report**

```bash
curl -X POST http://127.0.0.1:8000/api/v1/reports \
  -H "X-API-Key: dev-write-key" \
  -H "Content-Type: application/json" \
  -d '{
        "report_category": "waterlogging",
        "text": "Road near the metro station is under knee-deep water.",
        "reported_at": "2026-10-12T08:41:00+05:30",
        "location": { "latitude": 19.0760, "longitude": 72.8777, "accuracy_m": 25 },
        "area_reference": "Andheri East"
      }'
```

**Query events**

```bash
curl "http://127.0.0.1:8000/api/v1/events?source_category=water&page=1&page_size=20"
```

**Inspect a source**

```bash
curl http://127.0.0.1:8000/api/v1/sources/health
```

### Image verification

The console Verification page sends original image bytes to `POST /api/v1/verification/image`.
The app uses the bundled `app/xproai_best.pt` by default; set `XPROAI_CHECKPOINT` only to use
another XproAI v3 checkpoint. Install the optional
dependencies with `pip install -e ".[image-verification]"`. The endpoint caps uploads at 15 MB
and decoded images at 30 megapixels. C2PA verification uses the `c2pa-python` SDK; configure
`C2PA_SETTINGS_FILE` with the SDK's trust settings when your deployment needs an explicit trust
store. Claims are treated as cryptographically verified only when the SDK reports a valid state.

The supplied v3 CNN is marked retired by its source project and has poor reported real-world
performance. Its score is displayed only as a review indicator; all uploaded evidence remains
subject to human verification. No C2PA manifest is not evidence that an image is authentic.

---

## 9. Canonical event contract

One versioned envelope for every source. See `app/schemas/event.py` for the authoritative
definition.

```json
{
  "event_id": "evt_01JAX9QK7M3N",
  "source_id": "openweather.current",
  "source_event_id": "ow-1728708072",
  "event_type": "rainfall_observed",
  "event_time": "2026-10-12T08:41:12+05:30",
  "ingest_time": "2026-10-12T08:41:15Z",
  "location": {
    "latitude": 19.0760,
    "longitude": 72.8777,
    "accuracy_m": 12.0,
    "precision": "approximate",
    "area_reference": null
  },
  "measurements": [
    {
      "name": "rainfall_1h",
      "value": 28.4,
      "unit": "mm",
      "original_unit": "mm",
      "original_value": 28.4,
      "period_seconds": 3600,
      "aggregation": "accumulation",
      "converted": false
    }
  ],
  "source_kind": "live_api",
  "quality_status": "valid",
  "quality_flags": [],
  "raw_payload": { "...": "provider response, retained but redacted on read" },
  "schema_version": "1.0",
  "idempotency_key": "idk_9f2b...",
  "fingerprint": "fp_41ac..."
}
```

Guarantees enforced by the schema and the persistence layer:

- `event_time` and `ingest_time` are always stored separately and timezone-aware (UTC internally).
- Measurements keep `original_value`/`original_unit`; conversion is explicit and recorded.
- Rainfall accumulation is never presented as instantaneous intensity — `aggregation` and
  `period_seconds` are mandatory for accumulation-style measurements.
- `location` may be absent **only** for event types that permit it, and then
  `location.precision = "unknown"` with an `area_reference`.
- Missing values are never coerced to zero.
- `quality_flags` records every warning; `quality_status` records the verdict.

Event types are a closed vocabulary (`EventType`) so downstream scoring is stable.

---

## 10. Deterministic replay

Bundled sanitised fixtures live in `data/samples/`, covering all five source categories plus a
combined `monsoon_waterlogging` scenario.

```bash
# all categories, in-order
curl -X POST http://127.0.0.1:8000/api/v1/ingest/replay -H "X-API-Key: dev-write-key" -d '{"fixture": "all"}'

# out-of-order arrival, deterministic
curl -X POST http://127.0.0.1:8000/api/v1/ingest/replay -H "X-API-Key: dev-write-key" \
  -d '{"fixture": "all", "shuffle": true, "shuffle_seed": 1337}'
```

Properties:

- Every replayed event is stamped `source_kind = "synthetic"` (or `"manual"` for citizen
  fixtures) — it is **never** presented as live data.
- Event identity is derived deterministically from the fixture content, so the same fixture
  yields the same `event_id` and the same duplicate decisions on every run.
- Re-running a fixture produces duplicate receipts, not duplicate canonical events.
- The replay date is rebased onto the current clock by default so the demo always looks recent;
  pass `"rebase": false` to keep the literal fixture timestamps.

---

## 11. Running the tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

With coverage:

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing
```

Current result: **214 passed** (196 ingestion + 18 intelligence-layer) (Python 3.11.9). A full-suite run also prints a few
`PytestUnhandledThreadExceptionWarning: Event loop is closed` warnings from aiosqlite connection
teardown. They are test-harness noise only, appear only when the whole suite runs together, and do
not affect any assertion.

The suite **never** performs live network calls and **never** requires provider credentials.
HTTP is mocked at the `httpx` transport layer. Tests run against SQLite in-memory so they do not
depend on PostgreSQL either.

---

## 12. Scope status — what is and is not implemented

### Implemented and tested

- Canonical event contract + validation + quarantine with reason codes
- Five source adapters with a shared contract, bounded retries, timeouts, rate-limit handling
- Deterministic replay with stable identity
- Atomic idempotency via database unique constraints, with duplicate receipts
- Late/out-of-order event acceptance
- Source-health state machine, freshness, counters, error classification
- Ingestion-run lifecycle with per-source failure isolation
- API-key authorisation and secret redaction

### Not implemented (out of scope for this milestone)

| Capability | Status |
|---|---|
| Anomaly detection / baselines | **Not implemented.** The seam is `app/processing/`. |
| Incident candidate matching / clustering / merging | **Not implemented** |
| Causal inference / hypotheses | **Not implemented** |
| Cascade-risk simulation | **Not implemented** |
| Neo4j evidence graph | **Not implemented** (relational tables only; schema is designed to project into a graph later) |
| LangGraph / LLM agents | **Not implemented** (not required by this milestone) |
| Emergency dispatch or infrastructure control | **Out of scope by design — never** |

### Live connector verification status

No provider credentials were present in this environment. Consequently:

| Adapter | Live code path | Verified against the real provider? |
|---|---|---|
| Weather (OpenWeather) | Implemented | **No — untested, no key** |
| Air quality (OpenAQ v3) | Implemented | **No — untested, no key** |
| Traffic (TomTom-shaped) | Implemented | **No — untested, no key** |
| Water levels | Dataset/CSV only | **No live endpoint exists or is claimed** |
| Citizen reports | Implemented and tested | **Yes** |

Adapter parsing logic is unit-tested against mocked provider responses, which validates field
mapping and normalisation but **does not** prove the provider's real response shape matches.
Treat live integration as unverified until a real key is supplied.

---

## 13. Design principles and known limitations

### Principles held throughout

- **Deterministic first.** Validation, deduplication, identity, and persistence contain no
  randomness or model calls. Milestone 2 can build anomaly detection and candidate matching on a
  stable substrate.
- **Missing ≠ zero. Silent ≠ safe. Stale ≠ healthy. Synthetic ≠ live.**
- **Duplicates are recorded but never counted twice.**
- **Provider parsing is isolated from canonical normalisation.** Adapters emit canonical events;
  they never write to the database.
- **Failure isolation.** One connector failing cannot abort a run or affect other sources.

### Deviations and limitations

1. **Python 3.11, not 3.12.** Python 3.12 is not installed on this machine (only 3.11 and 3.14).
   3.11 was chosen over 3.14 because the async/PostGIS-adjacent dependency set is better
   supported. Nothing in the code requires >3.11.
2. **No PostgreSQL credentials were available.** The PostgreSQL 18 server is present and
   running on `127.0.0.1:5432`, but no role credentials for a new application database were
   supplied. `scripts/provision_db.*` performs the one-time provisioning. Until that is run with
   a superuser password, the app runs against SQLite.
3. **No PostGIS.** No spatial query is needed until Milestone 2 candidate retrieval. See §3.
4. **Auth is API-key based**, not OIDC/JWT. It satisfies the "enforce role permissions for write
   actions" requirement for this milestone; a real identity provider is a Milestone-2+ concern.
5. **No scheduler process.** `SCHEDULER_ENABLED` wires an in-process periodic poller, but it is
   off by default; for production, an external scheduler is preferable.
6. **Replay duplicates on the first run are expected.** `fixture: "all"` loads the per-category
   fixtures *and* the combined `monsoon_waterlogging` scenario, which re-delivers some of the same
   observations under different ids. The content-fingerprint rule collapses them (first run:
   30 fetched → 23 accepted, 7 duplicates; second run: 30 duplicates, 0 new).
7. **Raw payloads are retained** for lineage (a core requirement) but are **redacted** when
   served to read-only clients and scrubbed from logs. Retention durations remain TBD per the
   PRD.

---

## 14. Demo walkthrough (Milestone 1)

1. `GET /health` — confirm the app and database are ready.
2. `GET /api/v1/sources` — show the five categories and each one's configured mode.
3. `POST /api/v1/ingest/replay {"fixture": "monsoon_waterlogging"}` — ingest a labelled
   synthetic scenario.
4. `GET /api/v1/events` — inspect the canonical events, filtered by category.
5. `GET /api/v1/events/{event_id}` — show provenance, units, and original values.
6. Re-run the same ingest — show duplicate receipts and an unchanged event count.
7. `POST /api/v1/reports` — add a citizen report; observe it land as an unverified observation.
8. `GET /api/v1/sources/health` — show freshness and counters per source.
9. `GET /api/v1/ingestion/runs` — show the run history with accepted/rejected/duplicate counts.

---

*Urban Sentinel · Milestone 1 · Canonical event schema v1.0*


---

# Part 1b — Deterministic processing and wiring

```
POST /api/v1/ingest/{source}
  └─ EventService.persist_batch           (canonical events, atomic idempotency)  [Milestone 1]
      └─ ProcessingService.process_events (auto, PROCESSING_AUTO_ON_INGEST=true)
          A validate  ─ reason-coded VALID / VALID_WITH_WARNINGS / QUARANTINED / REJECTED
          B dedup     ─ versioned processing fingerprint + near-duplicate review flag
          C anomalies ─ threshold · robust z (median/MAD) · rate of change · sensor health
          D retrieve  ─ open incidents within a time window + bounding box (indexed)
          E score     ─ S = Σw·{T,G,K,A,Q}/Σw → MATCH_CANDIDATE / AMBIGUOUS / NEEDS_REVIEW / NO_MATCH
          └─ persisted: event_processing · anomalies(+history) · candidate_matches · incidents
POST /api/v1/incidents/{id}/analyze
  └─ intelligence_bridge.build_workflow_input → urban_sentinel ProcessedWorkflowInput
      └─ LangGraph workflow (signal → fusion → causal/cascade → impact), human approval required
```

All Stage A–E code in `app/processing/` is pure and deterministic (no LLM, no I/O). Same events +
same history + same `processing_version` (engine version + config hash) ⇒ same decisions. Events in
a batch are processed in event-time order, so late arrivals do not change rule outcomes.

### Endpoints added

| Method | Path | Auth |
|---|---|---|
| `POST` | `/api/v1/processing/events/{event_id}` — process one event (`{"force": false}`) | write |
| `POST` | `/api/v1/processing/batches` — `event_ids` / `ingestion_run_id` / `unprocessed_limit` | write |
| `GET` | `/api/v1/processing/runs`, `/api/v1/processing/runs/{run_id}` | public |
| `GET` | `/api/v1/processing/events/{event_id}` — validation, dedup, anomalies, candidates | public |
| `GET` | `/api/v1/anomalies` (`status`, `anomaly_type`, `kind`, `severity`, `source_id`, `subject`), `/api/v1/anomalies/{id}` (with history) | public |
| `GET` | `/api/v1/incidents`, `/api/v1/incidents/{id}` | public |
| `GET` | `/api/v1/incidents/candidates` (`event_id`, `incident_id`, `outcome`, `min_score`), `/api/v1/incidents/candidates/{id}` (score breakdown) | public |
| `GET` | `/api/v1/incidents/{id}/workflow-input` — exact payload handed to the agents | public |
| `POST` | `/api/v1/incidents/{id}/analyze` — run the intelligence workflow (`{"wait": true}` for demos) | write |
| `GET` | `/api/v1/intelligence/workflows/latest` — latest workflow and live specialist run/results for the Kitchen floor | public |
| — | mounted from `urban_sentinel/`: `/api/v1/intelligence/*`, `/api/v1/incidents/{id}/hypotheses·cascade·recommendations·review` | as upstream |

```bash
curl -X POST localhost:8000/api/v1/ingest/replay -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{"fixture":"monsoon_waterlogging"}'
curl "localhost:8000/api/v1/anomalies?status=ACTIVE&kind=environmental"
curl localhost:8000/api/v1/incidents
curl -X POST localhost:8000/api/v1/incidents/<incident_id>/analyze -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{"wait":true}'
curl localhost:8000/api/v1/incidents/<incident_id>/hypotheses
```

### Rules and defaults (illustrative — require domain calibration)

All values live in `app/processing/config.py` and can be overridden with `PROCESSING_CONFIG_PATH`.

| Rule | Default | Notes |
|---|---|---|
| `rainfall_1h_high` | 7.5 / 15 / 30 / 60 mm → LOW…CRITICAL | 1 h accumulations only; loosely after IMD categories |
| `water_level_high` | station threshold from dataset, else 0.75 / 1.0 / 1.5 m | per-gauge `water_level_threshold` wins |
| `traffic_speed_ratio_low` | ≤ 0.5 / 0.35 / 0.2 / 0.1 | current / free-flow |
| `pm25_1h_high` | 60 / 90 / 120 / 250 µg/m³ | NAQI-inspired, demo only; no AQI is derived |
| rate of change | water +0.3/0.6/1.2 m/h; speed −20/40/80 km/h per h; PM2.5 +30/60 µg/m³ per h | same unit and period only; implausible jumps → sensor health |
| robust baseline | 72 h window, ≥ 12 samples, \|z\| ≥ 3.5 / 6 | prior anomalous samples excluded; MAD = 0 or too few samples → no z |
| sensor health | flatline 6 readings ≥ 1 h; neighbour conflict ≥ 60 % within 1.5 km; stale > freshness SLA | never treated as an incident |
| candidates | weights T .30 · G .30 · K .20 · A .10 · Q .10; window 3 h; radius 2 km (hard reject > 6 km); match ≥ 0.65; review ≥ 0.45; ambiguity margin 0.08 | **heuristic, not a probability** |

Only incident-relevant signals are matched: citizen reports and events with an *environmental*
anomaly. Normal readings, weather context and exact duplicates are never forced into an incident.
An unmatched eligible event seeds a **provisional** cluster; incidents are never merged.

### Persistence (migration `7c1e2a9d0b44`)

`processing_runs`, `event_processing` (unique per event + `processing_version`; also the atomic
claim that makes retries and concurrent requests safe), `anomalies` (unique condition fingerprint)
+ `anomaly_observations` (history: created / updated / resolved / reopened / late), `incidents`
(unique seed event), `candidate_matches` (unique per event + incident + version, with component
scores and evidence for/against). The canonical `events` table is untouched.

### Known limitations

* SQLite (dev/test) processes batches sequentially; PostgreSQL uses bounded concurrency
  (`concurrency=4`). PostGIS is not used: distance is haversine with a bounding-box prefilter.
* Validation staleness is relative to processing time (recorded in each trace as `now`).
* The intelligence layer's own stores (hypotheses, workflows, audits) are still **in-memory**
  inside `urban_sentinel/` and reset on restart; operational truth for processing stays in the DB.
* No Neo4j graph is written by processing. Assets/dependency edges are not yet sourced, so cascade
  analysis runs on the in-memory graph with whatever the agents can infer from IDs.
* Thresholds and weights are demonstration values pending product-owner / domain sign-off.

---

# Part 2 — Multi-Agent Intelligence Layer

Bounded LangGraph workflow that sits **on top of** the deterministic urban-incident pipeline. It does not ingest sensors, detect numerical anomalies, or invent infrastructure graph edges. It investigates ambiguity, ranks competing hypotheses, inspects known dependency paths, and proposes **human-approved** actions.

## What this layer consumes

The processing pipeline is expected to supply a `ProcessedWorkflowInput`:

- normalized events (weather, air quality, traffic, water-level, citizen reports)
- anomaly and source-health records already computed
- spatial-temporal correlation scores and candidate incident IDs
- optional incident summary, assets, and dependency edges

If those services are not wired yet, the intelligence layer still runs against in-memory repositories and the seeded monsoon demo.

## Architecture

```
START
  → validate processed input
  → retrieve incident + Neo4j evidence (degraded if graph is down)
  → Signal Intelligence (unstructured text / quality / duplicates)
  → Incident Fusion (only when association is ambiguous)
  → persist proposed association (operational DB is authoritative)
  → Causal + Cascade analyst (hypotheses + bounded graph traversal)
  → Impact + Response analyst (catalogue ranking, no dispatch)
  → validate IDs / persist provenance / consolidate
END
```

Independent evidence fetches run in parallel. Agent outputs are schema-validated. Invalid IDs are rejected, retried within a bound, then replaced by deterministic fallbacks. LLM timeouts use the same fallbacks. Neo4j outages do not fabricate graph evidence.

Confidence is **not** collapsed into one number. Event validity, association match scores, hypothesis support, incident severity, and cascade scores stay separate. Match scores are deterministic features, not calibrated probabilities.

## Setup

Python 3.11+ (verified on 3.11.9; the original target was 3.12).

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

LLM and Neo4j credentials are optional. With them unset, the layer runs fully offline.

```bash
pytest
python -m urban_sentinel.demo.monsoon
uvicorn urban_sentinel.api.main:app --reload --port 8001
```

## HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/intelligence/analyze/{incident_id}` | Queue analysis; returns `workflow_id` |
| `GET` | `/api/v1/intelligence/workflows/{workflow_id}` | Status, errors, agent-run metadata |
| `GET` | `/api/v1/incidents/{incident_id}/hypotheses` | Ranked hypotheses |
| `GET` | `/api/v1/incidents/{incident_id}/cascade` | Cascade scenarios |
| `GET` | `/api/v1/incidents/{incident_id}/recommendations` | Catalogue actions |
| `POST` | `/api/v1/incidents/{incident_id}/review` | Authorized human review (`Bearer` token) |

Long-running analysis is queued. Pass `"wait": true` in the analyze body only for demos and tests.

Review decisions are audited. Hypothesis status transitions are constrained (`PROPOSED` → `UNDER_REVIEW` / `SUPPORTED` / `REJECTED` / `UNRESOLVED`, and the documented subset thereafter). Chain-of-thought is not stored.

## Neo4j contract

This package **does not** own the production graph schema. It calls repository methods equivalent to:

`get_incident_evidence`, `get_incident_hypotheses`, `link_event_to_incident`, `upsert_hypothesis`, `link_evidence_to_hypothesis`, `upsert_agent_run`, `upsert_scenario`, `get_cascade_paths`, `get_incident_graph`.

Writes are idempotent upserts keyed by stable IDs. Cascade traversal never invents assets or edges.

## Reproducible monsoon demo

Seeded events: rainfall rises, water level rises, traffic speed drops, a citizen reports waterlogging, a secondary sensor is offline, a traffic-incident hypothesis remains possible, cascade analysis follows drain → hospital-approach road → emergency access, and response ranking comes from the validated action catalogue with approval required.

```bash
python -m urban_sentinel.demo.monsoon
```

## Environment

See `.env.example`. Important flags:

- `URBAN_SENTINEL_LLM_PROVIDER` — `none` / `openai` / `anthropic`
- `URBAN_SENTINEL_REVIEW_TOKEN` — required for review POST
- `NEO4J_URI` / `NEO4J_PASSWORD` — optional; degraded mode if unreachable
- `URBAN_SENTINEL_MAX_GRAPH_DEPTH`, timeouts, and retry bounds
