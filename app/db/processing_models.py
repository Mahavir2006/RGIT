"""Deterministic-processing tables (Milestone 2).

The canonical ``events`` table stays the single source of truth for observations. Everything
here references it by ``event_id`` and records the ``processing_version`` that produced it, so a
result can always be explained and reproduced. Unique constraints make every effect idempotent
under retries and concurrent requests:

* ``uq_event_processing``     one result per (event, processing_version) — also the atomic claim
* ``uq_anomaly_episode``      one anomaly record per condition fingerprint
* ``uq_anomaly_observation``  one history entry per (anomaly, event, action)
* ``uq_candidate_match``      one candidate row per (event, incident, processing_version)
* ``uq_incident_seed``        one provisional incident per seeding event
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models import JSONVariant, PKType

__all__ = [
    "ProcessingRunModel",
    "EventProcessingModel",
    "AnomalyModel",
    "AnomalyObservationModel",
    "IncidentModel",
    "CandidateMatchModel",
]


class ProcessingRunModel(Base):
    __tablename__ = "processing_runs"
    __table_args__ = (Index("ix_proc_runs_started", "started_at"),)

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    processing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    requested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    stage_counts: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    errors: Mapped[list[Any]] = mapped_column(JSONVariant, nullable=False, default=list)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)


class EventProcessingModel(Base):
    """Validation + dedup verdicts and stage trace for one event under one processing version."""

    __tablename__ = "event_processing"
    __table_args__ = (
        UniqueConstraint("event_id", "processing_version", name="uq_event_processing"),
        Index("ix_event_processing_status", "status"),
        Index("ix_event_processing_run", "run_id"),
    )

    id: Mapped[int] = mapped_column(PKType, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False
    )
    processing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    validation_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    validation_issues: Mapped[list[Any]] = mapped_column(JSONVariant, nullable=False, default=list)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dedup_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dedup_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duplicate_of: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processing_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    counts_as_corroboration: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    anomaly_ids: Mapped[list[Any]] = mapped_column(JSONVariant, nullable=False, default=list)
    candidate_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    selected_incident_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AnomalyModel(Base):
    """One anomaly *condition* on one subject. Repeated firings update it; history is kept."""

    __tablename__ = "anomalies"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_anomaly_episode"),
        Index("ix_anomalies_status_type", "status", "anomaly_type"),
        Index("ix_anomalies_source", "source_id", "last_seen_at"),
    )

    anomaly_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    anomaly_type: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    peak_severity: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    subject: Mapped[str] = mapped_column(String(160), nullable=False)
    measurement: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    latest_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latest_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    latest_finding: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reopen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processing_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_version: Mapped[str] = mapped_column(String(64), nullable=False)


class AnomalyObservationModel(Base):
    """History: every firing / resolution / reopening of an anomaly."""

    __tablename__ = "anomaly_observations"
    __table_args__ = (
        UniqueConstraint("anomaly_id", "event_id", "action", name="uq_anomaly_observation"),
        Index("ix_anomaly_obs_event", "event_id"),
    )

    id: Mapped[int] = mapped_column(PKType, primary_key=True, autoincrement=True)
    anomaly_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("anomalies.anomaly_id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    #: created | updated | reopened | resolved
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finding: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IncidentModel(Base):
    """An incident or provisional candidate cluster built from matched events.

    Deterministic processing only *proposes* clusters; it never merges two incidents.
    """

    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("seed_event_id", name="uq_incident_seed"),
        Index("ix_incidents_status_time", "status", "last_event_time"),
    )

    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="provisional")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    seed_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    families: Mapped[list[Any]] = mapped_column(JSONVariant, nullable=False, default=list)
    subjects: Mapped[list[Any]] = mapped_column(JSONVariant, nullable=False, default=list)
    areas: Mapped[list[Any]] = mapped_column(JSONVariant, nullable=False, default=list)
    first_event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    located_event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    radius_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Independent (non-duplicate) events only. Duplicates never inflate corroboration.
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    peak_severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processing_version: Mapped[str] = mapped_column(String(64), nullable=False)


class CandidateMatchModel(Base):
    """One scored (event, incident) pair, with components and evidence for/against."""

    __tablename__ = "candidate_matches"
    __table_args__ = (
        UniqueConstraint("event_id", "incident_id", "processing_version",
                         name="uq_candidate_match"),
        Index("ix_candidates_incident", "incident_id", "outcome"),
        Index("ix_candidates_event", "event_id"),
        Index("ix_candidates_outcome", "outcome", "score"),
    )

    candidate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False
    )
    incident_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    #: True when the event was attached to the incident as supporting evidence.
    attached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    components: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    weights: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    evidence_for: Mapped[list[Any]] = mapped_column(JSONVariant, nullable=False, default=list)
    evidence_against: Mapped[list[Any]] = mapped_column(JSONVariant, nullable=False, default=list)
    time_delta_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    shared: Mapped[list[Any]] = mapped_column(JSONVariant, nullable=False, default=list)
    hard_rejected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommended_next_step: Mapped[str] = mapped_column(Text, nullable=False, default="")
    config_version: Mapped[str] = mapped_column(String(32), nullable=False)
    processing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
