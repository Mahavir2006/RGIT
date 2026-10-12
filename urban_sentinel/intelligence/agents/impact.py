from __future__ import annotations

from urban_sentinel.core.config import Settings
from urban_sentinel.domain.actions import DEFAULT_ACTIONS, ActionCatalogueItem
from urban_sentinel.domain.models import EventType, ProcessedWorkflowInput, ScoreType
from urban_sentinel.intelligence.models import (
    CausalAnalysis,
    ImpactAnalysis,
    ResponseRecommendation,
    SignalAnalysis,
    SeverityAssessment,
)


def _severity(payload: ProcessedWorkflowInput) -> SeverityAssessment:
    drivers: list[str] = []
    score = payload.incident.severity_score if payload.incident else None
    if score is None:
        score = 0.0
        for event in payload.normalized_events:
            if event.event_type == EventType.WATER_LEVEL and event.numeric_value is not None:
                bump = min(0.6, event.numeric_value / 2.0)
                score = max(score, bump)
                drivers.append(f"water-level observation {event.event_id}")
            if event.event_type == EventType.TRAFFIC and event.numeric_value is not None:
                bump = min(0.5, max(0.0, (40.0 - event.numeric_value) / 40.0))
                score = max(score, bump)
                drivers.append(f"traffic speed drop {event.event_id}")
            if event.event_type == EventType.CITIZEN_REPORT:
                score = max(score, 0.45)
                drivers.append(f"citizen report {event.event_id}")
            if event.event_type == EventType.WEATHER and event.numeric_value is not None:
                bump = min(0.4, event.numeric_value / 50.0)
                score = max(score, bump)
                drivers.append(f"rainfall intensity {event.event_id}")
        for anomaly in payload.anomaly_records:
            if anomaly.severity is not None:
                score = max(score, min(1.0, anomaly.severity))
                drivers.append(f"pipeline anomaly {anomaly.anomaly_id}")
    else:
        drivers.append("deterministic incident severity feature")
    incident_id = payload.incident_id or (payload.incident.incident_id if payload.incident else "unknown")
    return SeverityAssessment(
        incident_id=incident_id,
        severity_score=round(score, 3),
        score_type=ScoreType.RULE_SEVERITY,
        explanation="Severity is computed from deterministic features (levels, speed, report volume, anomalies), not from hypothesis rank.",
        drivers=drivers or ["insufficient numeric features"],
    )


def _applicable(item: ActionCatalogueItem, payload: ProcessedWorkflowInput, causal: CausalAnalysis) -> bool:
    types = {event.event_type.value for event in payload.normalized_events}
    if item.observation_first and (
        causal.insufficient_evidence
        or any(h.status.value == "UNRESOLVED" for h in causal.hypotheses)
        or any("water-level" in gap for gap in causal.suggested_additional_evidence)
    ):
        return True
    if not item.applicable_event_types:
        return True
    return bool(types.intersection(item.applicable_event_types))


def deterministic_impact(
    payload: ProcessedWorkflowInput,
    settings: Settings,
    causal: CausalAnalysis,
    signal: SignalAnalysis | None,
) -> ImpactAnalysis:
    severity = _severity(payload)
    incident_id = severity.incident_id
    event_ids = [event.event_id for event in payload.normalized_events]
    notes = list(causal.suggested_additional_evidence)
    if signal:
        notes.extend(item.description for item in signal.ambiguities)
    cascade_assets = {
        asset_id
        for scenario in causal.cascade_scenarios
        for asset_id in scenario.affected_asset_ids
    }

    ranked: list[tuple[float, ActionCatalogueItem, list[str]]] = []
    for item in DEFAULT_ACTIONS:
        if not _applicable(item, payload, causal):
            continue
        benefit = item.expected_risk_reduction
        assumptions = [
            "Rank uses the validated action catalogue, not an LLM-calculated safety score.",
            "No real-world dispatch, road closure, or infrastructure control is executed.",
        ]
        if item.action_id == "protect_emergency_access" and not cascade_assets:
            continue
        if item.action_id == "request_additional_observations" and causal.insufficient_evidence:
            benefit += 0.15
            assumptions.append("Additional observations are more useful than immediate escalation.")
        if item.action_id == "deploy_pumps" and severity.severity_score and severity.severity_score < 0.35:
            continue
        ranked.append((benefit, item, assumptions))

    ranked.sort(key=lambda row: row[0], reverse=True)
    actions: list[ResponseRecommendation] = []
    for index, (benefit, item, assumptions) in enumerate(ranked, start=1):
        actions.append(
            ResponseRecommendation(
                action_id=item.action_id,
                incident_id=incident_id,
                action_description=item.description,
                rank=index,
                expected_risk_reduction=min(1.0, benefit),
                cost=item.cost,
                time_to_effect=item.time_to_effect,
                feasibility=item.feasibility,
                evidence_event_ids=event_ids,
                assumptions=assumptions,
                approval_required=True,
                score_type=ScoreType.CATALOGUE_RANK,
            )
        )

    if severity.severity_score and severity.severity_score >= settings.high_impact_severity:
        notes.append("High-impact severity: human approval is required before any operational action.")

    summary = (
        f"Incident {incident_id}: rule severity {severity.severity_score} "
        f"({severity.score_type.value}). Cause confidence is tracked separately "
        f"across {len(causal.hypotheses)} hypotheses. "
        f"{len(actions)} catalogue actions proposed; all require human approval."
    )
    return ImpactAnalysis(
        severity=severity,
        candidate_actions=actions,
        operator_summary=summary,
        uncertainty_notes=notes,
        used_fallback=True,
    )
