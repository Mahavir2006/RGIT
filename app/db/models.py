"""SQLAlchemy 2.0 mapped models.

Idempotency is enforced here, in the database, not by a read-before-write check in application
code. A read-then-insert race lets two concurrent deliveries of the same event create two rows;
a unique constraint cannot.

Constraints
-----------
* ``uq_events_idempotency_key`` on ``idempotency_key`` — the primary duplicate guard.
* ``uq_events_source_event_id`` on ``(source_id, source_event_id)`` — provider-scoped identity.
* ``uq_events_fingerprint`` on ``fingerprint`` — the fallback content fingerprint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

__all__ = [
    "EventModel",
    "IngestionRunModel",
    "SourceHealthModel",
    "DuplicateReceiptModel",
    "QuarantineModel",
    "JSONVariant",
]

# Use JSONB on PostgreSQL for efficient filtering; plain JSON elsewhere.
JSONVariant = JSON().with_variant(JSONB(), "postgresql")

# SQLite only auto-increments plain INTEGER primary keys, so the bigint key is downgraded there.
PKType = BigInteger().with_variant(Integer, "sqlite")


class EventModel(Base):
    """A canonical event. Immutable as a record of what was observed."""

    __tablename__ = "events"

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_events_idempotency_key"),
        UniqueConstraint(
            "source_id", "source_event_id", name="uq_events_source_event_id"
        ),
        UniqueConstraint("fingerprint", name="uq_events_fingerprint"),
        Index("ix_events_event_time", "event_time"),
        Index("ix_events_source_time", "source_id", "event_time"),
        Index("ix_events_type_time", "event_type", "event_time"),
        Index("ix_events_source_kind", "source_kind"),
        Index("ix_events_quality_status", "quality_status"),
    )

    id: Mapped[int] = mapped_column(PKType, primary_key=True, autoincrement=True)

    # --- identity
    event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    # --- classification
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)

    # --- timing: always stored separately and timezone-aware (UTC)
    # Indexed via the explicit ix_events_event_time entry in __table_args__, not index=True,
    # so the index is not declared twice.
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingest_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # --- location
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_precision: Mapped[str | None] = mapped_column(String(24), nullable=True)
    place_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    area_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    geometry_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    radius_m: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- content
    measurements: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, default=list)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- quality / provenance
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False, default="valid")
    quality_flags: Mapped[list[str]] = mapped_column(JSONVariant, default=list)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")

    is_late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_duplicate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Always false on canonical rows; retained for querying convenience.",
    )

    # --- lineage
    first_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    duplicate_receipts: Mapped[list["DuplicateReceiptModel"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", lazy="selectin"
    )


class IngestionRunModel(Base):
    """One execution of one source adapter."""

    __tablename__ = "ingestion_runs"

    __table_args__ = (
        Index("ix_runs_source_started", "source_id", "started_at"),
        Index("ix_runs_status", "status"),
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trigger: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    records_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_quarantined: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_duplicate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    latest_event_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)

    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSONVariant, default=list)
    outcome_counts: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict)
    notes: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict)


class SourceHealthModel(Base):
    """Current health state for one source. One row per source (upserted)."""

    __tablename__ = "source_health"

    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    mode: Mapped[str] = mapped_column(String(24), nullable=False, default="disabled")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_event_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_event_time_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    records_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_quarantined: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_duplicate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list[str]] = mapped_column(JSONVariant, default=list)

    freshness_sla_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    last_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    missing_settings: Mapped[list[str]] = mapped_column(JSONVariant, default=list)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DuplicateReceiptModel(Base):
    """Record of a delivery that was identified as a duplicate.

    Kept for debugging and audit. Explicitly *not* a second canonical event, and never counted as
    independent corroboration.
    """

    __tablename__ = "duplicate_receipts"

    __table_args__ = (
        Index("ix_dupes_event", "event_id"),
        Index("ix_dupes_run", "run_id"),
    )

    id: Mapped[int] = mapped_column(PKType, primary_key=True, autoincrement=True)
    # A real foreign key: a receipt must point at an event that exists, which both satisfies the
    # ORM relationship and prevents orphan receipts.
    event_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    rule: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    event: Mapped[EventModel] = relationship(back_populates="duplicate_receipts")


class QuarantineModel(Base):
    """A record that failed validation and was set aside for inspection.

    Retaining the payload supports remediation and safe replay after a mapping fix. Nothing is
    silently discarded.
    """

    __tablename__ = "quarantine"

    __table_args__ = (
        Index("ix_quarantine_source_time", "source_id", "created_at"),
        Index("ix_quarantine_reason", "reason_code"),
    )

    id: Mapped[int] = mapped_column(PKType, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, default="unknown")
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, default=list)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict)
    # Retained so an operator can tell whether a quarantined record was ever replayed.
    remediation_status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Register the processing tables on the shared metadata (import at end to avoid a cycle).
from app.db import processing_models as _processing_models  # noqa: E402,F401
