"""Bridge: persisted deterministic-processing results -> multi-agent intelligence layer.

Builds the ``urban_sentinel.domain.models.ProcessedWorkflowInput`` contract from the authoritative
operational database (events, anomalies, candidate matches, incidents, source health), so the
LangGraph workflow consumes structured evidence instead of reverse-engineering logs.

The intelligence layer is optional: if ``urban_sentinel`` cannot be imported, ingestion and
processing keep working and the analyse endpoint reports the layer as unavailable.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.db.models import EventModel, SourceHealthModel
from app.db.processing_models import (
    AnomalyModel,
    AnomalyObservationModel,
    CandidateMatchModel,
    EventProcessingModel,
    IncidentModel,
)
from app.processing.correlation import primary_measurement
from app.schemas.anomaly import SEVERITY_ORDINAL
from app.schemas.event import CanonicalEvent, EventType
from app.services.event_service import EventService

__all__ = ["build_workflow_input", "set_intelligence_service", "get_intelligence_service",
           "trigger_analysis", "to_intelligence_type"]

logger = get_logger(__name__)

_service: Any = None


def set_intelligence_service(service: Any) -> None:
    global _service
    _service = service


def get_intelligence_service() -> Any:
    return _service


_TYPE_MAP: dict[str, str] = {
    "rainfall_observed": "weather", "temperature_observed": "weather",
    "weather_condition_observed": "weather", "humidity_observed": "weather",
    "wind_observed": "weather",
    "air_quality_observed": "air_quality",
    "traffic_speed_observed": "traffic", "traffic_congestion_observed": "traffic",
    "traffic_travel_time_observed": "traffic", "road_blocked_observed": "traffic",
    "water_level_observed": "water_level", "water_level_rising": "water_level",
    "sensor_offline": "sensor_health", "sensor_stale": "sensor_health",
    "source_unavailable": "sensor_health",
}


def to_intelligence_type(event_type: EventType | str) -> str:
    value = event_type.value if isinstance(event_type, EventType) else str(event_type)
    return _TYPE_MAP.get(value, "citizen_report" if value.endswith(("_reported", "_complaint",
                                                                     "_report")) else "weather")


_HEALTH_MAP = {"healthy": "healthy", "degraded": "degraded", "stale": "degraded",
               "offline": "offline"}


def _normalized(event: CanonicalEvent, proc: EventProcessingModel | None) -> dict[str, Any]:
    pm = primary_measurement(event)
    loc = event.location
    geo = None
    if loc is not None and loc.has_coordinates:
        geo = {"lat": loc.latitude, "lon": loc.longitude,
               "area_id": loc.area_reference or loc.place_id}
    valid = proc is None or proc.validation_verdict in ("VALID", "VALID_WITH_WARNINGS")
    return {
        "event_id": event.event_id,
        "source_id": event.source_id,
        "event_type": to_intelligence_type(event.event_type),
        "observed_at": event.event_time,
        "ingested_at": event.ingest_time,
        "location": geo,
        "numeric_value": pm[1] if pm else None,
        "unit": pm[2] if pm else None,
        "text": event.text,
        "quality_score": proc.quality_score if proc else None,
        "valid": valid,
        "duplicate_of": proc.duplicate_of if proc and not proc.counts_as_corroboration else None,
        "provenance": {
            "source_kind": event.source_kind.value,
            "canonical_event_type": event.event_type.value,
            "schema_version": event.schema_version,
            "processing_version": proc.processing_version if proc else None,
            "validation_verdict": proc.validation_verdict if proc else None,
            "dedup_decision": proc.dedup_decision if proc else None,
        },
        "attributes": {
            "measurements": [m.model_dump(mode="json") for m in event.measurements],
            "place_id": loc.place_id if loc else None,
            "area_reference": loc.area_reference if loc else None,
            "quality_flags": [f.value for f in event.quality_flags],
        },
    }


async def build_workflow_input(session: AsyncSession, incident_id: str,
                               processing_version: str) -> Any:
    from urban_sentinel.domain.models import ProcessedWorkflowInput

    inc = await session.get(IncidentModel, incident_id)
    if inc is None:
        raise NotFoundError(f"Unknown incident '{incident_id}'.",
                            details={"incident_id": incident_id})

    matches = (await session.execute(select(CandidateMatchModel).where(
        CandidateMatchModel.incident_id == incident_id))).scalars().all()
    member_ids = sorted({m.event_id for m in matches if m.attached or m.seed})
    related_ids = sorted({m.event_id for m in matches})
    # All candidate rows of related events, so competing incidents stay visible.
    all_matches = (await session.execute(select(CandidateMatchModel).where(
        CandidateMatchModel.event_id.in_(related_ids)))).scalars().all() if related_ids else []

    rows = (await session.execute(select(EventModel).where(
        EventModel.event_id.in_(related_ids)).order_by(EventModel.event_time))).scalars().all()
    events = [EventService.to_canonical(r) for r in rows]
    procs = {p.event_id: p for p in (await session.execute(select(EventProcessingModel).where(
        EventProcessingModel.event_id.in_(related_ids),
        EventProcessingModel.processing_version == processing_version))).scalars().all()}

    obs = (await session.execute(
        select(AnomalyObservationModel, AnomalyModel)
        .join(AnomalyModel, AnomalyModel.anomaly_id == AnomalyObservationModel.anomaly_id)
        .where(AnomalyObservationModel.event_id.in_(related_ids),
               AnomalyObservationModel.action.in_(["created", "updated", "reopened", "late"]))
    )).all() if related_ids else []
    anomaly_records = []
    seen: set[tuple[str, str]] = set()
    for o, a in obs:
        if (a.anomaly_id, o.event_id) in seen:
            continue
        seen.add((a.anomaly_id, o.event_id))
        explanation = (o.finding or {}).get("explanation") or a.latest_explanation
        anomaly_records.append({
            "anomaly_id": a.anomaly_id, "event_id": o.event_id,
            "detector": f"{a.rule_id}@{a.rule_version} ({a.kind})",
            "severity": SEVERITY_ORDINAL.get(o.severity or a.severity),
            "description": f"[{o.severity or a.severity}] {explanation}",
            "score_type": "rule_severity",
        })

    correlations = [{
        "event_id": m.event_id, "incident_id": m.incident_id, "score": m.score,
        "score_type": "deterministic_match", "spatial_distance_m": m.distance_m,
        "temporal_delta_seconds": m.time_delta_seconds, "hard_rejected": m.hard_rejected,
        "rejection_reason": m.rejection_reason, "existing_association": m.attached or m.seed,
    } for m in all_matches]
    candidate_ids = sorted({m.incident_id for m in all_matches if not m.hard_rejected})

    source_ids = sorted({e.source_id for e in events})
    health_rows = (await session.execute(select(SourceHealthModel).where(or_(
        SourceHealthModel.source_id.in_(source_ids),
        SourceHealthModel.status.in_(["offline", "stale", "degraded"]))))).scalars().all()
    source_health = [{
        "source_id": h.source_id, "status": _HEALTH_MAP.get(h.status, "unknown"),
        "last_seen_at": h.latest_event_time, "notes": h.error_summary or h.status,
    } for h in health_rows]

    peak = inc.peak_severity
    incident = {
        "incident_id": inc.incident_id, "title": inc.title, "status": inc.status,
        "version": inc.version,
        "severity_score": SEVERITY_ORDINAL.get(peak) if peak else None,
        "severity_score_type": "rule_severity",
        "location": ({"lat": inc.latitude, "lon": inc.longitude,
                      "area_id": inc.areas[0] if inc.areas else None}
                     if inc.latitude is not None else None),
        "associated_event_ids": member_ids,
        "asset_ids": [s.split(":", 1)[1] for s in inc.subjects],
        "summary": f"{inc.event_count} independent event(s); families {inc.families}; "
                   f"deterministic processing {processing_version}",
        "evidence_version": f"{processing_version}:v{inc.version}",
    }
    return ProcessedWorkflowInput.model_validate({
        "trigger_event_ids": member_ids,
        "candidate_incident_ids": candidate_ids or [incident_id],
        "incident_id": incident_id,
        "normalized_events": [_normalized(e, procs.get(e.event_id)) for e in events],
        "anomaly_records": anomaly_records,
        "correlation_results": correlations,
        "source_health": source_health,
        "incident": incident,
        "material_change": True,
    })


async def trigger_analysis(session: AsyncSession, incident_id: str, processing_version: str,
                           *, wait: bool) -> dict[str, Any]:
    service = get_intelligence_service()
    if service is None:
        from app.core.errors import AppError

        raise AppError("The intelligence layer is not enabled or failed to load.",
                       code="intelligence_unavailable", status_code=503)
    payload = await build_workflow_input(session, incident_id, processing_version)
    if wait:
        result = await service.run(payload)
        return {"workflow_id": str(result.get("workflow_id")),
                "status": str(result.get("status", "completed")),
                "errors": list(result.get("errors") or []),
                "review_required": result.get("review_required")}
    workflow_id = service.enqueue(payload)
    state = service.get_workflow(workflow_id) or {}
    return {"workflow_id": workflow_id, "status": str(state.get("status", "queued")),
            "errors": list(state.get("errors") or [])}
