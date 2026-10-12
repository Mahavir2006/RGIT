from __future__ import annotations

from urban_sentinel.core.config import Settings
from urban_sentinel.domain.models import ProcessedWorkflowInput, SourceHealthStatus


def should_run_intelligence(payload: ProcessedWorkflowInput, settings: Settings) -> bool:
    if payload.material_change:
        return True
    if payload.anomaly_records:
        return True
    if any(item.status == SourceHealthStatus.OFFLINE for item in payload.source_health):
        return True
    if any(not item.valid for item in payload.normalized_events):
        return True
    if any(
        event.event_type.value == "citizen_report" and event.text
        for event in payload.normalized_events
    ):
        return True
    ambiguous = False
    for corr in payload.correlation_results:
        if corr.hard_rejected:
            continue
        if corr.score is None or corr.score < settings.association_ambiguity_threshold:
            ambiguous = True
    if ambiguous or len(payload.candidate_incident_ids) > 1:
        return True
    return False


def association_is_ambiguous(payload: ProcessedWorkflowInput, settings: Settings) -> bool:
    if len(payload.candidate_incident_ids) > 1:
        return True
    live = [c for c in payload.correlation_results if not c.hard_rejected]
    if not live:
        return True
    if any(c.score is None or c.score < settings.association_ambiguity_threshold for c in live):
        return True
    incident_ids = {c.incident_id for c in live if c.incident_id}
    return len(incident_ids) > 1


def needs_signal_agent(payload: ProcessedWorkflowInput) -> bool:
    if any(event.text for event in payload.normalized_events):
        return True
    if any(item.status.value in {"offline", "degraded"} for item in payload.source_health):
        return True
    if payload.anomaly_records:
        return True
    types = {event.event_type.value for event in payload.normalized_events}
    return "citizen_report" in types
