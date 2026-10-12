from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    WEATHER = "weather"
    AIR_QUALITY = "air_quality"
    TRAFFIC = "traffic"
    WATER_LEVEL = "water_level"
    CITIZEN_REPORT = "citizen_report"
    SENSOR_HEALTH = "sensor_health"


class SourceHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class AssociationDecision(StrEnum):
    ATTACH_TO_INCIDENT = "ATTACH_TO_INCIDENT"
    CREATE_INCIDENT = "CREATE_INCIDENT"
    AMBIGUOUS_REVIEW = "AMBIGUOUS_REVIEW"
    REJECT_ASSOCIATION = "REJECT_ASSOCIATION"


class HypothesisStatus(StrEnum):
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUPPORTED = "SUPPORTED"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"


ALLOWED_HYPOTHESIS_TRANSITIONS: dict[HypothesisStatus, frozenset[HypothesisStatus]] = {
    HypothesisStatus.PROPOSED: frozenset(
        {
            HypothesisStatus.UNDER_REVIEW,
            HypothesisStatus.SUPPORTED,
            HypothesisStatus.REJECTED,
            HypothesisStatus.UNRESOLVED,
        }
    ),
    HypothesisStatus.UNDER_REVIEW: frozenset(
        {
            HypothesisStatus.SUPPORTED,
            HypothesisStatus.REJECTED,
            HypothesisStatus.UNRESOLVED,
            HypothesisStatus.PROPOSED,
        }
    ),
    HypothesisStatus.SUPPORTED: frozenset(
        {HypothesisStatus.UNDER_REVIEW, HypothesisStatus.REJECTED}
    ),
    HypothesisStatus.REJECTED: frozenset({HypothesisStatus.UNDER_REVIEW}),
    HypothesisStatus.UNRESOLVED: frozenset(
        {
            HypothesisStatus.UNDER_REVIEW,
            HypothesisStatus.SUPPORTED,
            HypothesisStatus.REJECTED,
            HypothesisStatus.PROPOSED,
        }
    ),
}


class ScoreType(StrEnum):
    DETERMINISTIC_MATCH = "deterministic_match"
    HEURISTIC_SUPPORT = "heuristic_support"
    RULE_SEVERITY = "rule_severity"
    GRAPH_PATH_HEURISTIC = "graph_path_heuristic"
    SIMULATED_CASCADE = "simulated_cascade"
    CATALOGUE_RANK = "catalogue_rank"
    INSUFFICIENT = "insufficient"


class GeoPoint(BaseModel):
    lat: float
    lon: float
    area_id: str | None = None


class NormalizedEvent(BaseModel):
    event_id: str
    source_id: str
    event_type: EventType
    observed_at: datetime
    ingested_at: datetime | None = None
    location: GeoPoint | None = None
    numeric_value: float | None = None
    unit: str | None = None
    text: str | None = None
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    valid: bool = True
    duplicate_of: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)


class AnomalyRecord(BaseModel):
    anomaly_id: str
    event_id: str
    detector: str
    severity: float | None = None
    description: str
    score_type: ScoreType = ScoreType.RULE_SEVERITY


class SourceHealthRecord(BaseModel):
    source_id: str
    status: SourceHealthStatus
    last_seen_at: datetime | None = None
    notes: str | None = None


class CorrelationResult(BaseModel):
    event_id: str
    incident_id: str | None = None
    score: float | None = None
    score_type: ScoreType = ScoreType.DETERMINISTIC_MATCH
    spatial_distance_m: float | None = None
    temporal_delta_seconds: float | None = None
    hard_rejected: bool = False
    rejection_reason: str | None = None
    existing_association: bool = False


class IncidentSummary(BaseModel):
    incident_id: str
    title: str
    status: str = "open"
    version: int = 1
    severity_score: float | None = None
    severity_score_type: ScoreType = ScoreType.RULE_SEVERITY
    location: GeoPoint | None = None
    associated_event_ids: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    summary: str | None = None
    evidence_version: str = "0"


class Asset(BaseModel):
    asset_id: str
    name: str
    asset_type: str
    critical: bool = False


class DependencyEdge(BaseModel):
    from_asset_id: str
    to_asset_id: str
    relationship: str = "DEPENDS_ON"


class ReviewDecision(StrEnum):
    APPROVE_ASSOCIATION = "APPROVE_ASSOCIATION"
    REJECT_ASSOCIATION = "REJECT_ASSOCIATION"
    SUPPORT_HYPOTHESIS = "SUPPORT_HYPOTHESIS"
    REJECT_HYPOTHESIS = "REJECT_HYPOTHESIS"
    APPROVE_ACTION = "APPROVE_ACTION"
    REQUEST_MORE_EVIDENCE = "REQUEST_MORE_EVIDENCE"
    SUBMIT_DEPARTMENT_REPORT = "SUBMIT_DEPARTMENT_REPORT"
    ROUTE_DEPARTMENT_REPORT = "ROUTE_DEPARTMENT_REPORT"
    UPDATE_DEPARTMENT_REPORT = "UPDATE_DEPARTMENT_REPORT"


class AuditRecord(BaseModel):
    audit_id: str
    incident_id: str
    actor: str
    decision: ReviewDecision
    target_id: str | None = None
    notes: str | None = None
    created_at: datetime


class ProcessedWorkflowInput(BaseModel):
    """Contract consumed from the deterministic processing pipeline."""

    trigger_event_ids: list[str]
    candidate_incident_ids: list[str] = Field(default_factory=list)
    incident_id: str | None = None
    normalized_events: list[NormalizedEvent]
    anomaly_records: list[AnomalyRecord] = Field(default_factory=list)
    correlation_results: list[CorrelationResult] = Field(default_factory=list)
    source_health: list[SourceHealthRecord] = Field(default_factory=list)
    incident: IncidentSummary | None = None
    incidents: list[IncidentSummary] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    dependencies: list[DependencyEdge] = Field(default_factory=list)
    material_change: bool = True
    reanalysis_scope: list[str] = Field(default_factory=lambda: ["ALL"])
    expected_incident_version: int | None = None
