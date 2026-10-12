"""Ingestion run, per-record outcome, and adapter result schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DuplicateDecision, RunStatus, ValidationOutcome

__all__ = [
    "RecordOutcome",
    "DuplicateInfo",
    "RunError",
    "IngestionRunCreate",
    "IngestionRun",
    "IngestionRunSummary",
    "AdapterResult",
    "IngestRequest",
    "RunListResponse",
]


class DuplicateInfo(BaseModel):
    """How and why a record was identified as a duplicate.

    Recorded for debugging and audit. A duplicate is never treated as additional corroboration.
    """

    model_config = ConfigDict(extra="forbid")

    decision: DuplicateDecision
    matched_event_id: str | None = None
    rule: str = Field(description="Human-readable description of the rule that matched.")
    idempotency_key: str | None = None
    fingerprint: str | None = None


class RecordOutcome(BaseModel):
    """Per-record processing result inside an ingestion run."""

    model_config = ConfigDict(extra="forbid")

    outcome: ValidationOutcome
    event_id: str | None = None
    source_event_id: str | None = None
    reason_code: str | None = None
    message: str | None = None
    field_errors: list[dict[str, Any]] = Field(default_factory=list)
    duplicate: DuplicateInfo | None = None


class RunError(BaseModel):
    """A safe-to-display error encountered during a run.

    ``message`` must already be redacted and must never contain a credential.
    """

    model_config = ConfigDict(extra="forbid")

    category: str = Field(description="Machine-readable category, e.g. 'timeout'.")
    code: str | None = None
    message: str
    retryable: bool = False
    occurred_at: datetime | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class IngestionRunCreate(BaseModel):
    """Internal creation payload for an ingestion run."""

    run_id: str
    source_id: str
    trigger: str = Field(description="'api' | 'schedule' | 'replay' | 'manual'")
    correlation_id: str | None = None
    started_at: datetime


class IngestionRun(BaseModel):
    """Full ingestion-run record."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    source_id: str
    trigger: str
    status: RunStatus
    correlation_id: str | None = None

    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: float | None = None

    records_fetched: int = 0
    records_accepted: int = 0
    records_rejected: int = 0
    records_quarantined: int = 0
    records_duplicate: int = 0

    latest_event_time: datetime | None = None
    error_category: str | None = None
    errors: list[RunError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    outcome_counts: dict[str, int] = Field(default_factory=dict)
    notes: dict[str, Any] = Field(default_factory=dict)


class IngestionRunSummary(BaseModel):
    """Compact run view for list endpoints."""

    run_id: str
    source_id: str
    trigger: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: float | None = None
    records_fetched: int = 0
    records_accepted: int = 0
    records_rejected: int = 0
    records_quarantined: int = 0
    records_duplicate: int = 0
    error_category: str | None = None


class IngestRequest(BaseModel):
    """Body for ``POST /api/v1/ingest/{source}``."""

    model_config = ConfigDict(extra="forbid")

    force: bool = Field(
        default=False,
        description="Allow the run even when a run for this source is already in flight.",
    )
    dry_run: bool = Field(
        default=False,
        description="Fetch and validate but do not persist. Useful for verifying credentials.",
    )
    # Replay-specific options; ignored by live adapters.
    fixture: str | None = None
    shuffle: bool = False
    shuffle_seed: int | None = None
    rebase: bool | None = None


class RunListResponse(BaseModel):
    runs: list[IngestionRunSummary]


class AdapterResult(BaseModel):
    """What an adapter returns: canonical events plus actionable diagnostics.

    An adapter never raises for a *record-level* problem — malformed rows are reported as
    rejected/quarantined outcomes so that one bad record cannot abort a batch. It does raise (or
    return an error) for a *source-level* failure such as bad credentials or a timeout.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    source_id: str
    events: list[Any] = Field(default_factory=list, description="CanonicalEvent instances.")
    outcomes: list[RecordOutcome] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[RunError] = Field(default_factory=list)
    pages_fetched: int = 0
    truncated: bool = Field(
        default=False, description="True when a page limit or provider cap cut the result short."
    )
    provider_meta: dict[str, Any] = Field(default_factory=dict)
    fetch_started_at: datetime | None = None
    fetch_finished_at: datetime | None = None
