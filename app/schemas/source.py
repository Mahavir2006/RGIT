"""Source catalogue and source-health schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import SourceCategory, SourceMode, SourceStatus

__all__ = [
    "SourceDescriptor",
    "SourceListItem",
    "SourceHealthState",
    "SourceHealthResponse",
    "CredentialState",
    "MissingCredential",
]


class CredentialState(BaseModel):
    """Whether a credential is configured.

    Reports state only. The value is never present on this model, so it cannot be leaked by a
    careless serialiser.
    """

    model_config = ConfigDict(extra="forbid")

    variable: str = Field(description="Name of the environment variable, never its value.")
    configured: bool
    placeholder: bool = Field(
        default=False, description="True when the value is an unfilled template placeholder."
    )


class SourceDescriptor(BaseModel):
    """Static description of a connector, returned by ``GET /api/v1/sources``."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    display_name: str
    category: SourceCategory
    provider: str
    mode: SourceMode
    enabled: bool
    description: str = ""
    supports_live: bool = False
    supports_replay: bool = True
    credentials: list[CredentialState] = Field(default_factory=list)
    required_settings: list[str] = Field(default_factory=list)
    missing_settings: list[str] = Field(default_factory=list)
    unit_notes: str = ""
    documentation_url: str | None = None
    caveats: list[str] = Field(default_factory=list)


class SourceListItem(SourceDescriptor):
    """Descriptor plus the current runtime mode and health, for compact listings."""

    status: SourceStatus = SourceStatus.UNKNOWN


class SourceHealthState(BaseModel):
    """Per-source health snapshot.

    A source is not healthy merely because the API process is running: health reflects the last
    real attempt to obtain data.
    """

    model_config = ConfigDict(extra="forbid")

    source_id: str
    display_name: str
    category: SourceCategory
    provider: str
    mode: SourceMode
    status: SourceStatus
    enabled: bool
    runnable: bool = Field(
        description="True when the source has everything it needs to run right now."
    )

    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    latest_event_time: datetime | None = Field(
        default=None, description="Watermark of the newest observation obtained."
    )
    last_event_time_at: datetime | None = Field(
        default=None, description="When that watermark last advanced."
    )

    ingest_lag_seconds: float | None = Field(
        default=None, description="Seconds between newest event time and now."
    )
    since_last_success_seconds: float | None = None

    records_fetched: int = 0
    records_accepted: int = 0
    records_rejected: int = 0
    records_quarantined: int = 0
    records_duplicate: int = 0

    freshness_sla_seconds: int
    is_fresh: bool = False
    consecutive_failures: int = 0

    error_category: str | None = None
    error_summary: str | None = Field(
        default=None, description="Redacted, safe-to-display error description."
    )
    warnings: list[str] = Field(default_factory=list)

    missing_settings: list[str] = Field(default_factory=list)
    last_run_id: str | None = None
    updated_at: datetime | None = None

    @property
    def age_of_last_observation_seconds(self) -> float | None:
        if self.latest_event_time is None:
            return None
        from app.core.timeutil import ensure_aware, utc_now

        # Re-tag naive values (SQLite) as UTC before subtracting.
        return max(0.0, (utc_now() - ensure_aware(self.latest_event_time)).total_seconds())


class SourceHealthResponse(BaseModel):
    """Aggregate health view returned by ``GET /api/v1/sources/health``."""

    total: int
    healthy: int
    degraded: int
    offline: int
    stale: int
    misconfigured: int
    disabled: int
    unknown: int
    all_fresh: bool
    data_mode_note: str = Field(
        default="A missing or stale feed is an observability gap, not evidence that a location is safe."
    )
    sources: list[SourceHealthState]
    warnings: list[str] = Field(default_factory=list)
