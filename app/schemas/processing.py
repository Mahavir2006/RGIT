"""Processing-stage result schemas (validation, deduplication, run summaries)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

__all__ = [
    "ValidationVerdict",
    "ReasonCode",
    "ValidationIssue",
    "ValidationResult",
    "DedupDecision",
    "DedupResult",
    "ProcessingRunStatus",
    "EventProcessingStatus",
    "ProcessBatchRequest",
    "ProcessEventRequest",
]


class ValidationVerdict(str, Enum):
    VALID = "VALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


class ReasonCode(str, Enum):
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_FIELD = "INVALID_FIELD"
    INVALID_COORDINATES = "INVALID_COORDINATES"
    NAIVE_TIMESTAMP = "NAIVE_TIMESTAMP"
    MALFORMED_TIMESTAMP = "MALFORMED_TIMESTAMP"
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    EXCESSIVELY_OLD = "EXCESSIVELY_OLD"
    LATE_ARRIVAL = "LATE_ARRIVAL"
    UNKNOWN_UNIT = "UNKNOWN_UNIT"
    INCOMPATIBLE_UNIT = "INCOMPATIBLE_UNIT"
    NON_FINITE_VALUE = "NON_FINITE_VALUE"
    MISSING_PERIOD = "MISSING_PERIOD"
    MISSING_MEASUREMENT = "MISSING_MEASUREMENT"
    LOCATION_MISSING = "LOCATION_MISSING"
    LOCATION_APPROXIMATE = "LOCATION_APPROXIMATE"
    UNSUPPORTED_SCHEMA_VERSION = "UNSUPPORTED_SCHEMA_VERSION"
    UNKNOWN_EVENT_TYPE = "UNKNOWN_EVENT_TYPE"
    INCONSISTENT_IDENTIFIER = "INCONSISTENT_IDENTIFIER"
    UPSTREAM_INVALID = "UPSTREAM_INVALID"
    UPSTREAM_SUSPECT = "UPSTREAM_SUSPECT"
    SYNTHETIC_DATA = "SYNTHETIC_DATA"


class ValidationIssue(BaseModel):
    code: ReasonCode
    severity: str = Field(description="warning | quarantine | reject")
    field: str | None = None
    message: str


class ValidationResult(BaseModel):
    verdict: ValidationVerdict
    issues: list[ValidationIssue] = Field(default_factory=list)
    quality_score: float = Field(ge=0.0, le=1.0)
    is_late: bool = False

    @property
    def processable(self) -> bool:
        return self.verdict in (ValidationVerdict.VALID, ValidationVerdict.VALID_WITH_WARNINGS)


class DedupDecision(str, Enum):
    UNIQUE = "UNIQUE"
    #: Identical observation already exists under another canonical event id.
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    #: Similar but not provably identical. Kept, flagged, excluded from corroboration.
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"


class DedupResult(BaseModel):
    decision: DedupDecision
    method: str = Field(description="source_event_id | idempotency_key | fingerprint | near_match | none")
    fingerprint: str
    fingerprint_version: str
    duplicate_of: str | None = None
    explanation: str
    counts_as_corroboration: bool = True


class ProcessingRunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    PARTIALLY_FAILED = "PARTIALLY_FAILED"
    FAILED = "FAILED"


class EventProcessingStatus(str, Enum):
    PROCESSED = "PROCESSED"
    REUSED = "REUSED"  # already processed with this processing_version; no new effects
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    NOT_FOUND = "NOT_FOUND"


class ProcessEventRequest(BaseModel):
    #: Recompute even when a result exists for this processing_version. Effects stay idempotent.
    force: bool = False


class ProcessBatchRequest(BaseModel):
    event_ids: list[str] | None = Field(default=None, max_length=5000)
    #: Process every event persisted by this ingestion run.
    ingestion_run_id: str | None = None
    #: Process the N most recent events that have no result for the current version.
    unprocessed_limit: int | None = Field(default=None, ge=1, le=5000)
    force: bool = False
