from __future__ import annotations

from typing import Any, TypedDict

from urban_sentinel import SCHEMA_VERSION


class IntelligenceState(TypedDict, total=False):
    workflow_id: str
    input_payload: dict[str, Any]
    cache_key: str
    cascade_paths_raw: list[dict[str, Any]]
    trigger_event_ids: list[str]
    candidate_incident_ids: list[str]
    incident_id: str | None
    normalized_events: list[dict[str, Any]]
    anomaly_records: list[dict[str, Any]]
    correlation_results: list[dict[str, Any]]
    source_health: list[dict[str, Any]]
    incidents: list[dict[str, Any]]
    assets: list[dict[str, Any]]
    dependencies: list[dict[str, Any]]
    evidence_context: dict[str, Any]
    fusion_decision: dict[str, Any] | None
    fusion_decisions: list[dict[str, Any]]
    signal_analysis: dict[str, Any] | None
    hypotheses: list[dict[str, Any]]
    cascade_scenarios: list[dict[str, Any]]
    severity_assessment: dict[str, Any] | None
    candidate_actions: list[dict[str, Any]]
    evidence_gaps: list[str]
    agent_runs: list[dict[str, Any]]
    review_required: bool
    errors: list[str]
    status: str
    schema_version: str
    reanalysis_scope: list[str]
    skip_signal: bool
    skip_fusion: bool
    graph_degraded: bool
    llm_degraded: bool
    expected_incident_version: int | None
    material_change: bool
    cache_hit: bool
    operator_summary: str | None
    known_event_ids: list[str]
    known_incident_ids: list[str]
    known_asset_ids: list[str]
    known_action_ids: list[str]


def empty_state(workflow_id: str) -> IntelligenceState:
    return IntelligenceState(
        workflow_id=workflow_id,
        trigger_event_ids=[],
        candidate_incident_ids=[],
        incident_id=None,
        normalized_events=[],
        anomaly_records=[],
        correlation_results=[],
        source_health=[],
        incidents=[],
        assets=[],
        dependencies=[],
        evidence_context={},
        fusion_decision=None,
        fusion_decisions=[],
        signal_analysis=None,
        hypotheses=[],
        cascade_scenarios=[],
        severity_assessment=None,
        candidate_actions=[],
        evidence_gaps=[],
        agent_runs=[],
        review_required=False,
        errors=[],
        status="running",
        schema_version=SCHEMA_VERSION,
        reanalysis_scope=["ALL"],
        skip_signal=False,
        skip_fusion=False,
        graph_degraded=False,
        llm_degraded=False,
        expected_incident_version=None,
        material_change=True,
        cache_hit=False,
        operator_summary=None,
        known_event_ids=[],
        known_incident_ids=[],
        known_asset_ids=[],
        known_action_ids=[],
    )
