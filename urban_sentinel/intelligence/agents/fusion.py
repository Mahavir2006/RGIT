from __future__ import annotations

from urban_sentinel.core.config import Settings
from urban_sentinel.domain.models import AssociationDecision, ProcessedWorkflowInput, ScoreType
from urban_sentinel.intelligence.models import FusionDecision
from urban_sentinel.intelligence.triggers import association_is_ambiguous


def deterministic_fusion(
    payload: ProcessedWorkflowInput,
    settings: Settings,
    event_id: str,
) -> FusionDecision:
    correlations = [c for c in payload.correlation_results if c.event_id == event_id]
    hard = [c for c in correlations if c.hard_rejected]
    if hard and not [c for c in correlations if not c.hard_rejected]:
        return FusionDecision(
            event_id=event_id,
            decision=AssociationDecision.REJECT_ASSOCIATION,
            candidate_incident_ids=payload.candidate_incident_ids,
            selected_incident_id=None,
            association_score=hard[0].score,
            score_type=ScoreType.DETERMINISTIC_MATCH,
            evidence_event_ids=[event_id],
            reason=hard[0].rejection_reason or "Deterministic hard-rejection rule matched.",
            review_required=False,
            used_fallback=True,
        )

    live = [c for c in correlations if not c.hard_rejected]
    existing = [c for c in live if c.existing_association and c.incident_id]
    if existing:
        chosen = existing[0]
        return FusionDecision(
            event_id=event_id,
            decision=AssociationDecision.ATTACH_TO_INCIDENT,
            candidate_incident_ids=payload.candidate_incident_ids,
            selected_incident_id=chosen.incident_id,
            association_score=chosen.score,
            score_type=ScoreType.DETERMINISTIC_MATCH,
            evidence_event_ids=[event_id],
            reason="Existing auditable association retained; fusion will not overwrite it silently.",
            review_required=False,
            used_fallback=True,
        )

    if association_is_ambiguous(payload, settings):
        incident_id = payload.incident_id or (
            payload.candidate_incident_ids[0] if payload.candidate_incident_ids else None
        )
        high_impact = False
        if payload.incident and payload.incident.severity_score is not None:
            high_impact = payload.incident.severity_score >= settings.high_impact_severity
        return FusionDecision(
            event_id=event_id,
            decision=AssociationDecision.AMBIGUOUS_REVIEW,
            candidate_incident_ids=payload.candidate_incident_ids,
            selected_incident_id=incident_id,
            association_score=min((c.score or 0.0) for c in live) if live else None,
            score_type=ScoreType.DETERMINISTIC_MATCH,
            evidence_event_ids=[event_id],
            reason="Multiple candidates or below-threshold deterministic match scores require review. Match scores are not calibrated probabilities.",
            review_required=True,
            uncertainty_notes=["Association is ambiguous.", "Do not merge incidents solely because event types match."],
            used_fallback=True,
        )

    if live and live[0].incident_id:
        chosen = max(live, key=lambda c: c.score or 0.0)
        return FusionDecision(
            event_id=event_id,
            decision=AssociationDecision.ATTACH_TO_INCIDENT,
            candidate_incident_ids=payload.candidate_incident_ids,
            selected_incident_id=chosen.incident_id,
            association_score=chosen.score,
            score_type=ScoreType.DETERMINISTIC_MATCH,
            evidence_event_ids=[event_id],
            reason="Single above-threshold deterministic spatial-temporal match.",
            review_required=high_impact_review(payload, settings),
            used_fallback=True,
        )

    if payload.incident_id:
        return FusionDecision(
            event_id=event_id,
            decision=AssociationDecision.ATTACH_TO_INCIDENT,
            candidate_incident_ids=payload.candidate_incident_ids or [payload.incident_id],
            selected_incident_id=payload.incident_id,
            association_score=None,
            score_type=ScoreType.DETERMINISTIC_MATCH,
            evidence_event_ids=[event_id],
            reason="Workflow was requested for an existing incident; attaching trigger event.",
            review_required=False,
            used_fallback=True,
        )

    return FusionDecision(
        event_id=event_id,
        decision=AssociationDecision.CREATE_INCIDENT,
        candidate_incident_ids=[],
        selected_incident_id=None,
        association_score=None,
        score_type=ScoreType.DETERMINISTIC_MATCH,
        evidence_event_ids=[event_id],
        reason="No viable existing incident candidate remained after hard-rejection filters.",
        review_required=True,
        used_fallback=True,
    )


def high_impact_review(payload: ProcessedWorkflowInput, settings: Settings) -> bool:
    if payload.incident and payload.incident.severity_score is not None:
        return payload.incident.severity_score >= settings.high_impact_severity
    return False
