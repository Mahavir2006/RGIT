"""Anomaly listing and detail (with history)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import DbSession, RequestId
from app.api.envelope import paginated, success
from app.api.processing import _iso, anomaly_to_dict
from app.core.errors import NotFoundError
from app.db.processing_models import AnomalyModel, AnomalyObservationModel
from app.schemas.common import Envelope

__all__ = ["router"]

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


@router.get("", response_model=Envelope, summary="List anomalies")
async def list_anomalies(
    session: DbSession, request_id: RequestId,
    status: str | None = Query(default=None, description="ACTIVE | RESOLVED"),
    anomaly_type: str | None = Query(default=None),
    kind: str | None = Query(default=None, description="environmental | sensor_health"),
    severity: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
) -> Envelope:
    stmt = select(AnomalyModel)
    for col, val in ((AnomalyModel.status, status), (AnomalyModel.anomaly_type, anomaly_type),
                     (AnomalyModel.kind, kind), (AnomalyModel.severity, severity),
                     (AnomalyModel.source_id, source_id), (AnomalyModel.subject, subject)):
        if val:
            stmt = stmt.where(col == val)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await session.execute(
        stmt.order_by(AnomalyModel.last_seen_at.desc(), AnomalyModel.anomaly_id)
        .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return paginated([anomaly_to_dict(a) for a in rows], total, page, page_size, request_id)


@router.get("/{anomaly_id}", response_model=Envelope, summary="Anomaly detail and history")
async def get_anomaly(anomaly_id: str, session: DbSession, request_id: RequestId) -> Envelope:
    row = await session.get(AnomalyModel, anomaly_id)
    if row is None:
        raise NotFoundError(f"Unknown anomaly '{anomaly_id}'.")
    history = (await session.execute(select(AnomalyObservationModel).where(
        AnomalyObservationModel.anomaly_id == anomaly_id)
        .order_by(AnomalyObservationModel.id))).scalars().all()
    return success({**anomaly_to_dict(row), "history": [
        {"event_id": h.event_id, "action": h.action, "severity": h.severity,
         "observed_value": h.observed_value, "event_time": _iso(h.event_time),
         "run_id": h.run_id, "recorded_at": _iso(h.recorded_at),
         "explanation": (h.finding or {}).get("explanation")} for h in history]}, request_id)
