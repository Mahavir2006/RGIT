"""Shared schema primitives: enums, envelopes, pagination."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.core.timeutil import utc_now

__all__ = [
    "SourceKind",
    "SourceCategory",
    "SourceMode",
    "SourceStatus",
    "QualityStatus",
    "QualityFlag",
    "MeasurementAggregation",
    "LocationPrecision",
    "ValidationOutcome",
    "RunStatus",
    "DuplicateDecision",
    "PaginationMeta",
    "PageParams",
    "ErrorBody",
    "ResponseMeta",
    "ErrorResponse",
    "Envelope",
    "utc_now",
]

T = TypeVar("T")


class SourceKind(str, Enum):
    """Provenance of the record. Required provenance shown to users."""

    LIVE_API = "live_api"
    HISTORICAL = "historical"
    SYNTHETIC = "synthetic"
    MANUAL = "manual"


class SourceCategory(str, Enum):
    """The five supported source categories."""

    WEATHER = "weather"
    AIR_QUALITY = "air_quality"
    TRAFFIC = "traffic"
    WATER = "water"
    CITIZEN = "citizen"
    REPLAY = "replay"  # meta-source: deterministic fixture playback
    SYSTEM = "system"  # internal/health events


class SourceMode(str, Enum):
    """How a connector is currently obtaining data."""

    LIVE = "live"
    HISTORICAL = "historical"
    REPLAY = "replay"
    SYNTHETIC = "synthetic"
    MANUAL = "manual"
    DISABLED = "disabled"


class SourceStatus(str, Enum):
    """Health state. Mode is tracked separately: a replay source can be perfectly healthy."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    OFFLINE = "offline"
    MISCONFIGURED = "misconfigured"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class QualityStatus(str, Enum):
    """Validation verdict for a canonical event."""

    VALID = "valid"
    SUSPECT = "suspect"
    INVALID = "invalid"
    STALE = "stale"
    IMPUTED = "imputed"


class QualityFlag(str, Enum):
    """Machine-readable warnings attached to an event."""

    NAIVE_TIMESTAMP_ASSUMED_UTC = "naive_timestamp_assumed_utc"
    LOCATION_MISSING = "location_missing"
    LOCATION_PRECISION_LOW = "location_precision_low"
    UNIT_CONVERTED = "unit_converted"
    ORIGINAL_UNITS_PRESERVED = "original_units_preserved"
    MEASUREMENT_OUT_OF_EXPECTED_RANGE = "measurement_out_of_expected_range"
    LATE_ARRIVAL = "late_arrival"
    PROVIDER_PARTIAL_PAYLOAD = "provider_partial_payload"
    STALE_SOURCE = "stale_source"
    CITIZEN_UNVERIFIED = "citizen_unverified"
    REDACTED_TEXT = "redacted_text"
    OPTIONAL_MEASUREMENT_ABSENT = "optional_measurement_absent"
    NORMALIZED_GEOMETRY = "normalized_geometry"
    SYNTHETIC_DATA = "synthetic_data"
    REPLAY_DATA = "replay_data"


class MeasurementAggregation(str, Enum):
    """How a measurement should be interpreted over time.

    This exists so that, for example, 30 mm of rain accumulated over an hour is never displayed
    or compared as an instantaneous intensity of 30 mm/h.
    """

    INSTANTANEOUS = "instantaneous"
    ACCUMULATION = "accumulation"
    AVERAGE = "average"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    COUNT = "count"


class LocationPrecision(str, Enum):
    """Precision of a location fix.

    When a source provides only an area, `AREA` is used and no precise pin is rendered.
    """

    PRECISE = "precise"
    APPROXIMATE = "approximate"
    AREA = "area"
    UNKNOWN = "unknown"


class ValidationOutcome(str, Enum):
    """Result of validating a single submitted or fetched record."""

    ACCEPTED = "accepted"
    ACCEPTED_WITH_WARNING = "accepted_with_warning"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class RunStatus(str, Enum):
    """Lifecycle of an ingestion run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class DuplicateDecision(str, Enum):
    """Which idempotency rule matched."""

    NONE = "none"
    SOURCE_EVENT_ID = "source_event_id"
    IDEMPOTENCY_KEY = "idempotency_key"
    FINGERPRINT = "fingerprint"


class PageParams(BaseModel):
    """Bounded pagination parameters. `page_size` is capped by the API layer."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1, description="1-indexed page number.")
    page_size: int = Field(default=50, ge=1, le=200, description="Items per page (max 200).")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PaginationMeta(BaseModel):
    """Pagination block returned in the envelope meta."""

    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_previous: bool


class ResponseMeta(BaseModel):
    """Standard envelope metadata."""

    request_id: str | None = None
    generated_at: datetime = Field(default_factory=utc_now)
    pagination: PaginationMeta | None = None


class ErrorBody(BaseModel):
    """Error block returned in the envelope."""

    code: str
    message: str
    field_errors: list[dict[str, Any]] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class ErrorResponse(BaseModel):
    data: None = None
    meta: ResponseMeta = Field(default_factory=ResponseMeta)
    error: ErrorBody


class Envelope(BaseModel, Generic[T]):
    """Single response envelope used by every endpoint."""

    data: T | None = None
    meta: ResponseMeta = Field(default_factory=ResponseMeta)
    error: ErrorBody | None = None

    @classmethod
    def ok(cls, data: T, meta: ResponseMeta | None = None) -> "Envelope[T]":
        return cls(data=data, meta=meta or ResponseMeta(), error=None)
