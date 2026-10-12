from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from urban_sentinel.domain.models import AssociationDecision, HypothesisStatus, ScoreType


class WorkflowStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    REVIEW_REQUIRED = "review_required"


class ExtractedFact(BaseModel):
    event_id: str
    statement: str
    kind: Literal["observation", "interpretation"] = "observation"
    confidence_note: str | None = None


class AmbiguityNote(BaseModel):
    event_id: str | None = None
    description: str
    missing_fields: list[str] = Field(default_factory=list)


class QualityConcern(BaseModel):
    event_id: str | None = None
    source_id: str | None = None
    description: str
    reliability: Literal["low", "medium", "unknown"] = "unknown"


class DuplicateReference(BaseModel):
    event_id: str
    possible_duplicate_of: str
    reason: str


class SignalAnalysis(BaseModel):
    extracted_facts: list[ExtractedFact] = Field(default_factory=list)
    relevant_event_ids: list[str] = Field(default_factory=list)
    ambiguities: list[AmbiguityNote] = Field(default_factory=list)
    possible_duplicates: list[DuplicateReference] = Field(default_factory=list)
    quality_concerns: list[QualityConcern] = Field(default_factory=list)
    evidence_summary: str = ""
    used_fallback: bool = False


class FusionDecision(BaseModel):
    event_id: str
    decision: AssociationDecision
    candidate_incident_ids: list[str] = Field(default_factory=list)
    selected_incident_id: str | None = None
    association_score: float | None = None
    score_type: ScoreType = ScoreType.DETERMINISTIC_MATCH
    evidence_event_ids: list[str] = Field(default_factory=list)
    reason: str
    review_required: bool = False
    uncertainty_notes: list[str] = Field(default_factory=list)
    used_fallback: bool = False


class Hypothesis(BaseModel):
    hypothesis_id: str
    incident_id: str
    claim: str
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    score: float | None = None
    score_type: ScoreType = ScoreType.HEURISTIC_SUPPORT
    supporting_event_ids: list[str] = Field(default_factory=list)
    contradicting_event_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    model_version: str = "deterministic-v1"
    alternatives: list[str] = Field(default_factory=list)


class DependencyPath(BaseModel):
    asset_ids: list[str]
    relationships: list[str] = Field(default_factory=list)


class CascadeScenario(BaseModel):
    scenario_id: str
    incident_id: str
    starting_asset_ids: list[str] = Field(default_factory=list)
    affected_asset_ids: list[str] = Field(default_factory=list)
    dependency_paths: list[DependencyPath] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risk_score: float | None = None
    score_type: ScoreType = ScoreType.GRAPH_PATH_HEURISTIC
    simulation_version: str = "graph-bfs-v1"
    simulated: bool = True
    limitations: list[str] = Field(default_factory=list)


class CausalAnalysis(BaseModel):
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    cascade_scenarios: list[CascadeScenario] = Field(default_factory=list)
    suggested_additional_evidence: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False
    used_fallback: bool = False


class SeverityAssessment(BaseModel):
    incident_id: str
    severity_score: float | None = None
    score_type: ScoreType = ScoreType.RULE_SEVERITY
    explanation: str
    drivers: list[str] = Field(default_factory=list)
    distinct_from_cause_confidence: str = (
        "Severity describes observed impact intensity, not confidence that a cause is true."
    )


class ResponseRecommendation(BaseModel):
    action_id: str
    incident_id: str
    action_description: str
    rank: int
    expected_risk_reduction: float | None = None
    cost: str | None = None
    time_to_effect: str | None = None
    feasibility: str | None = None
    evidence_event_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    approval_required: bool = True
    score_type: ScoreType = ScoreType.CATALOGUE_RANK


class ImpactAnalysis(BaseModel):
    severity: SeverityAssessment
    candidate_actions: list[ResponseRecommendation] = Field(default_factory=list)
    operator_summary: str
    uncertainty_notes: list[str] = Field(default_factory=list)
    used_fallback: bool = False


class AgentRun(BaseModel):
    run_id: str
    agent_name: str
    status: str
    model_version: str
    prompt_version: str
    started_at: datetime
    finished_at: datetime | None = None
    latency_ms: float | None = None
    retries: int = 0
    token_usage: dict[str, int] | None = None
    error: str | None = None
    fallback_used: bool = False


class EvidenceContext(BaseModel):
    graph_available: bool = True
    degraded_reason: str | None = None
    linked_event_ids: list[str] = Field(default_factory=list)
    existing_hypotheses: list[Hypothesis] = Field(default_factory=list)
    existing_scenarios: list[CascadeScenario] = Field(default_factory=list)
    cascade_paths: list[DependencyPath] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ConsolidatedResult(BaseModel):
    workflow_id: str
    incident_id: str | None
    status: WorkflowStatus
    review_required: bool
    fusion_decisions: list[FusionDecision] = Field(default_factory=list)
    signal_analysis: SignalAnalysis | None = None
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    cascade_scenarios: list[CascadeScenario] = Field(default_factory=list)
    severity_assessment: SeverityAssessment | None = None
    candidate_actions: list[ResponseRecommendation] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    agent_runs: list[AgentRun] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    schema_version: str
    extras: dict[str, Any] = Field(default_factory=dict)
