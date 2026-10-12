"""Incident candidates, provisional clusters, and the hand-off to the intelligence layer.

The intelligence layer's own routes (``/api/v1/incidents/{id}/hypotheses``, ``/cascade``,
``/recommendations``, ``/review`` and ``/api/v1/intelligence/*``) are mounted alongside these by
``app.main``; the paths do not overlap.
"""

from __future__ import annotations

from fastapi import Depends, APIRouter, Header, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession, RequestId
from app.api.envelope import paginated, success
from app.api.processing import _iso, candidate_to_dict
from app.core.errors import NotFoundError
from app.core.security import require_write_key
from app.db.processing_models import CandidateMatchModel, IncidentModel
from app.integration.intelligence_bridge import build_workflow_input, trigger_analysis
from app.processing.config import get_processing_config
from app.schemas.common import Envelope

__all__ = ["router"]

router = APIRouter(prefix="/incidents", tags=["incidents"])


def incident_to_dict(i: IncidentModel) -> dict:
    return {"incident_id": i.incident_id, "status": i.status, "title": i.title,
            "seed_event_id": i.seed_event_id, "families": i.families, "subjects": i.subjects,
            "areas": i.areas, "first_event_time": _iso(i.first_event_time),
            "last_event_time": _iso(i.last_event_time),
            "location": ({"latitude": i.latitude, "longitude": i.longitude,
                          "radius_m": i.radius_m} if i.latitude is not None else None),
            "independent_event_count": i.event_count, "peak_severity": i.peak_severity,
            "version": i.version, "processing_version": i.processing_version,
            "note": "provisional cluster from deterministic matching; not a confirmed incident"
            if i.status == "provisional" else None}


class AnalyzeBody(BaseModel):
    wait: bool = False


@router.get("/candidates", response_model=Envelope, summary="List ranked candidate matches")
async def list_candidates(
    session: DbSession, request_id: RequestId,
    event_id: str | None = Query(default=None), incident_id: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0, le=1),
    include_rejected: bool = Query(default=False),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
) -> Envelope:
    stmt = select(CandidateMatchModel)
    if event_id:
        stmt = stmt.where(CandidateMatchModel.event_id == event_id)
    if incident_id:
        stmt = stmt.where(CandidateMatchModel.incident_id == incident_id)
    if outcome:
        stmt = stmt.where(CandidateMatchModel.outcome == outcome)
    if min_score is not None:
        stmt = stmt.where(CandidateMatchModel.score >= min_score)
    if not include_rejected:
        stmt = stmt.where(CandidateMatchModel.hard_rejected.is_(False))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await session.execute(
        stmt.order_by(CandidateMatchModel.score.desc(), CandidateMatchModel.candidate_id)
        .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return paginated([candidate_to_dict(c) for c in rows], total, page, page_size, request_id)


@router.get("/candidates/{candidate_id}", response_model=Envelope,
            summary="Candidate detail and score explanation")
async def get_candidate(candidate_id: str, session: DbSession, request_id: RequestId) -> Envelope:
    row = await session.get(CandidateMatchModel, candidate_id)
    if row is None:
        raise NotFoundError(f"Unknown candidate '{candidate_id}'.")
    d = candidate_to_dict(row)
    if row.components and row.weights:
        total_w = sum(row.weights.values())
        d["contributions"] = {k: round(row.weights[k] * row.components[k] / total_w, 4)
                              for k in row.weights}
        d["formula"] = "S = (wt*T + ws*G + wk*K + wa*A + wq*Q) / sum(w)  — heuristic, not a probability"
    return success(d, request_id)


@router.get("", response_model=Envelope, summary="List incidents / provisional clusters")
async def list_incidents(
    session: DbSession, request_id: RequestId, status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
) -> Envelope:
    stmt = select(IncidentModel)
    if status:
        stmt = stmt.where(IncidentModel.status == status)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await session.execute(stmt.order_by(IncidentModel.last_event_time.desc())
                                  .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return paginated([incident_to_dict(i) for i in rows], total, page, page_size, request_id)


@router.get("/{incident_id}", response_model=Envelope, summary="Incident detail with evidence")
async def get_incident(incident_id: str, session: DbSession, request_id: RequestId) -> Envelope:
    row = await session.get(IncidentModel, incident_id)
    if row is None:
        raise NotFoundError(f"Unknown incident '{incident_id}'.")
    cands = (await session.execute(select(CandidateMatchModel).where(
        CandidateMatchModel.incident_id == incident_id)
        .order_by(CandidateMatchModel.score.desc()))).scalars().all()
    return success({**incident_to_dict(row),
                    "member_event_ids": sorted({c.event_id for c in cands if c.attached}),
                    "candidates": [candidate_to_dict(c) for c in cands]}, request_id)


@router.get("/{incident_id}/workflow-input", response_model=Envelope,
            summary="The ProcessedWorkflowInput handed to the intelligence layer")
async def workflow_input(incident_id: str, session: DbSession, request_id: RequestId) -> Envelope:
    payload = await build_workflow_input(session, incident_id,
                                         get_processing_config().processing_version)
    return success(payload.model_dump(mode="json"), request_id)


@router.post("/{incident_id}/analyze", response_model=Envelope,
             summary="Run the multi-agent intelligence workflow on a processed incident",
             dependencies=[Depends(require_write_key)])
async def analyze(
    incident_id: str, session: DbSession, request_id: RequestId,
    body: AnalyzeBody | None = None,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Envelope:
    require_write_key(x_api_key)
    result = await trigger_analysis(session, incident_id,
                                    get_processing_config().processing_version,
                                    wait=(body or AnalyzeBody()).wait)
    result["links"] = {
        "workflow": f"/api/v1/intelligence/workflows/{result['workflow_id']}",
        "hypotheses": f"/api/v1/incidents/{incident_id}/hypotheses",
        "cascade": f"/api/v1/incidents/{incident_id}/cascade",
        "recommendations": f"/api/v1/incidents/{incident_id}/recommendations",
    }
    return success(result, request_id)
