"""Deterministic processing endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, APIRouter, Header, Query
from sqlalchemy import func, select

from app.api.deps import DbSession, RequestId
from app.api.envelope import paginated, success
from app.core.errors import NotFoundError, ValidationError
from app.core.security import require_write_key
from app.db.models import EventModel, IngestionRunModel
from app.db.processing_models import (
    AnomalyModel,
    AnomalyObservationModel,
    CandidateMatchModel,
    EventProcessingModel,
    ProcessingRunModel,
)
from app.schemas.common import Envelope
from app.schemas.processing import ProcessBatchRequest, ProcessEventRequest
from app.services.processing_service import get_processing_service

__all__ = ["router", "run_to_dict", "candidate_to_dict", "anomaly_to_dict"]

router = APIRouter(prefix="/processing", tags=["processing"])


def _iso(v: Any) -> Any:
    from app.core.timeutil import ensure_aware

    return ensure_aware(v).isoformat() if v is not None else None


def run_to_dict(r: ProcessingRunModel, *, full: bool = False) -> dict[str, Any]:
    d = {"run_id": r.run_id, "trigger": r.trigger, "status": r.status,
         "processing_version": r.processing_version, "started_at": _iso(r.started_at),
         "finished_at": _iso(r.finished_at), "duration_ms": r.duration_ms,
         "requested": r.requested, "counts": r.counts, "stage_counts": r.stage_counts,
         "errors": r.errors}
    if full:
        d["config_snapshot"] = r.config_snapshot
    return d


def processing_to_dict(p: EventProcessingModel) -> dict[str, Any]:
    return {"event_id": p.event_id, "processing_version": p.processing_version,
            "run_id": p.run_id, "status": p.status, "attempts": p.attempts,
            "validation": {"verdict": p.validation_verdict, "issues": p.validation_issues,
                           "quality_score": p.quality_score, "is_late": p.is_late},
            "deduplication": {"decision": p.dedup_decision, "method": p.dedup_method,
                              "duplicate_of": p.duplicate_of,
                              "fingerprint": p.processing_fingerprint,
                              "counts_as_corroboration": p.counts_as_corroboration},
            "anomaly_ids": p.anomaly_ids, "candidate_outcome": p.candidate_outcome,
            "selected_incident_id": p.selected_incident_id, "trace": p.trace,
            "error": p.error, "processed_at": _iso(p.processed_at)}


def anomaly_to_dict(a: AnomalyModel) -> dict[str, Any]:
    f = a.latest_finding or {}
    return {"anomaly_id": a.anomaly_id, "anomaly_type": a.anomaly_type, "kind": a.kind,
            "status": a.status, "severity": a.severity, "peak_severity": a.peak_severity,
            "rule_id": a.rule_id, "rule_version": a.rule_version, "source_id": a.source_id,
            "subject": a.subject, "measurement": a.measurement, "unit": a.unit,
            "event_id": a.latest_event_id, "observed_value": a.latest_value,
            "threshold": f.get("threshold"), "expected_range": f.get("expected_range"),
            "score": f.get("score"), "method": f.get("method"),
            "baseline_window_hours": f.get("baseline_window_hours"),
            "sample_count": f.get("sample_count"), "explanation": a.latest_explanation,
            "occurrence_count": a.occurrence_count, "reopen_count": a.reopen_count,
            "first_seen_at": _iso(a.first_seen_at), "detected_at": _iso(a.last_seen_at),
            "resolved_at": _iso(a.resolved_at), "resolved_by_event_id": a.resolved_by_event_id,
            "processing_run_id": a.processing_run_id,
            "processing_version": a.processing_version}


def candidate_to_dict(c: CandidateMatchModel) -> dict[str, Any]:
    return {"candidate_id": c.candidate_id, "event_id": c.event_id,
            "incident_id": c.incident_id, "outcome": c.outcome, "attached": c.attached,
            "seed": c.seed, "score": c.score,
            "score_type": "deterministic_match_heuristic (not a probability)",
            "rank": c.rank, "components": c.components, "weights": c.weights,
            "evidence_for": c.evidence_for, "evidence_against": c.evidence_against,
            "time_delta_seconds": c.time_delta_seconds, "distance_m": c.distance_m,
            "shared": c.shared, "hard_rejected": c.hard_rejected,
            "rejection_reason": c.rejection_reason, "explanation": c.explanation,
            "recommended_next_step": c.recommended_next_step,
            "config_version": c.config_version, "processing_version": c.processing_version,
            "run_id": c.run_id, "created_at": _iso(c.created_at)}


@router.post("/events/{event_id}", response_model=Envelope, summary="Process one canonical event",
             dependencies=[Depends(require_write_key)])
async def process_event(
    event_id: str,
    request_id: RequestId,
    body: ProcessEventRequest | None = None,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Envelope:
    require_write_key(x_api_key)
    result = await get_processing_service().process_events(
        [event_id], trigger="api", force=(body or ProcessEventRequest()).force,
        correlation_id=request_id)
    if result["counts"].get("NOT_FOUND"):
        raise NotFoundError(f"Unknown event '{event_id}'.", details={"event_id": event_id})
    return success(result, request_id)


@router.post("/batches", response_model=Envelope, summary="Process a bounded batch of events",
             dependencies=[Depends(require_write_key)])
async def process_batch(
    body: ProcessBatchRequest,
    session: DbSession,
    request_id: RequestId,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Envelope:
    require_write_key(x_api_key)
    service = get_processing_service()
    ids: list[str] = list(body.event_ids or [])
    if body.ingestion_run_id:
        run = await session.get(IngestionRunModel, body.ingestion_run_id)
        if run is None:
            raise NotFoundError(f"Unknown ingestion run '{body.ingestion_run_id}'.")
        ids += [r[0] for r in await session.execute(
            select(EventModel.event_id).where(EventModel.first_run_id == body.ingestion_run_id))]
    if body.unprocessed_limit:
        ids += await service.unprocessed_event_ids(body.unprocessed_limit)
    if not ids:
        if body.unprocessed_limit or body.ingestion_run_id:
            # A valid request that simply has nothing left to do.
            return success({"run_id": None, "status": "COMPLETED", "requested": 0,
                            "counts": {}, "message": "no matching events need processing"},
                           request_id)
        raise ValidationError("Provide event_ids, ingestion_run_id, or unprocessed_limit.")
    if len(set(ids)) > service.cfg.batch_max:
        raise ValidationError(f"Batch exceeds batch_max={service.cfg.batch_max}.")
    result = await service.process_events(ids, trigger="api_batch", force=body.force,
                                          correlation_id=request_id)
    return success(result, request_id)


@router.get("/runs", response_model=Envelope, summary="List processing runs")
async def list_runs(
    session: DbSession, request_id: RequestId,
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
) -> Envelope:
    stmt = select(ProcessingRunModel)
    if status:
        stmt = stmt.where(ProcessingRunModel.status == status)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await session.execute(stmt.order_by(ProcessingRunModel.started_at.desc())
                                  .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return paginated([run_to_dict(r) for r in rows], total, page, page_size, request_id)


@router.get("/runs/{run_id}", response_model=Envelope, summary="Processing run detail")
async def get_run(run_id: str, session: DbSession, request_id: RequestId) -> Envelope:
    row = await session.get(ProcessingRunModel, run_id)
    if row is None:
        raise NotFoundError(f"Unknown processing run '{run_id}'.")
    return success(run_to_dict(row, full=True), request_id)


@router.get("/events/{event_id}", response_model=Envelope,
            summary="Validation, dedup, anomaly and candidate results for one event")
async def get_event_results(event_id: str, session: DbSession, request_id: RequestId) -> Envelope:
    if (await session.execute(select(EventModel.id).where(EventModel.event_id == event_id))
            ).first() is None:
        raise NotFoundError(f"Unknown event '{event_id}'.")
    procs = (await session.execute(select(EventProcessingModel).where(
        EventProcessingModel.event_id == event_id)
        .order_by(EventProcessingModel.processed_at.desc()))).scalars().all()
    obs = (await session.execute(
        select(AnomalyObservationModel, AnomalyModel)
        .join(AnomalyModel, AnomalyModel.anomaly_id == AnomalyObservationModel.anomaly_id)
        .where(AnomalyObservationModel.event_id == event_id))).all()
    cands = (await session.execute(select(CandidateMatchModel).where(
        CandidateMatchModel.event_id == event_id).order_by(CandidateMatchModel.rank))
    ).scalars().all()
    return success({
        "event_id": event_id,
        "processing": [processing_to_dict(p) for p in procs],
        "anomalies": [{**anomaly_to_dict(a), "action": o.action,
                       "finding": o.finding} for o, a in obs],
        "candidates": [candidate_to_dict(c) for c in cands],
    }, request_id)
