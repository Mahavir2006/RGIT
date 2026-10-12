# Urban Sentinel — Multi-Agent Intelligence Layer

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

Python 3.12+.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
```

LLM and Neo4j credentials are optional. With them unset, the layer runs fully offline.

```bash
pytest
python -m urban_sentinel.demo.monsoon
uvicorn urban_sentinel.api.main:app --reload
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
