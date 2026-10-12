from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from urban_sentinel.api.deps import get_service, require_reviewer
from urban_sentinel.api.schemas import ReviewRequest
from urban_sentinel.intelligence.service import IntelligenceService

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.get("/{incident_id}/hypotheses")
async def get_hypotheses(
    incident_id: str, service: IntelligenceService = Depends(get_service)
) -> dict:
    items = service.operational.get_hypotheses(incident_id)
    return {"incident_id": incident_id, "hypotheses": [item.model_dump(mode="json") for item in items]}


@router.get("/{incident_id}/cascade")
async def get_cascade(
    incident_id: str, service: IntelligenceService = Depends(get_service)
) -> dict:
    items = service.operational.get_scenarios(incident_id)
    return {"incident_id": incident_id, "scenarios": [item.model_dump(mode="json") for item in items]}


@router.get("/{incident_id}/recommendations")
async def get_recommendations(
    incident_id: str, service: IntelligenceService = Depends(get_service)
) -> dict:
    items = service.operational.get_recommendations(incident_id)
    return {
        "incident_id": incident_id,
        "recommendations": [item.model_dump(mode="json") for item in items],
    }


@router.post("/{incident_id}/review")
async def review_incident(
    incident_id: str,
    body: ReviewRequest,
    service: IntelligenceService = Depends(get_service),
    actor: str = Depends(require_reviewer),
) -> dict:
    if service.operational.get_incident(incident_id) is None and not service.operational.get_hypotheses(
        incident_id
    ):
        raise HTTPException(status_code=404, detail="Unknown incident")
    record = service.record_review(
        incident_id=incident_id,
        actor=actor,
        decision=body.decision,
        target_id=body.target_id,
        notes=body.notes,
    )
    return {"audit": record.model_dump(mode="json")}
