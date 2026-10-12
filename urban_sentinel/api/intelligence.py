from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from urban_sentinel.api.deps import get_service
from urban_sentinel.api.schemas import AnalyzeRequest, AnalyzeResponse
from urban_sentinel.domain.models import IncidentSummary, ProcessedWorkflowInput
from urban_sentinel.intelligence.service import IntelligenceService

router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])


@router.post("/analyze/{incident_id}", response_model=AnalyzeResponse)
async def analyze_incident(
    incident_id: str,
    body: AnalyzeRequest | None = None,
    service: IntelligenceService = Depends(get_service),
) -> AnalyzeResponse:
    body = body or AnalyzeRequest()
    if body.payload is not None:
        payload = body.payload.model_copy(update={"incident_id": incident_id})
    else:
        incident = service.operational.get_incident(incident_id)
        if incident is None:
            incident = IncidentSummary(incident_id=incident_id, title=f"Incident {incident_id}")
            service.operational.upsert_incident(incident)
        payload = ProcessedWorkflowInput(
            trigger_event_ids=incident.associated_event_ids,
            candidate_incident_ids=[incident_id],
            incident_id=incident_id,
            normalized_events=[],
            incident=incident,
            material_change=body.material_change,
            reanalysis_scope=body.reanalysis_scope,
        )
    if body.wait:
        result = await service.run(payload)
        return AnalyzeResponse(
            workflow_id=str(result.get("workflow_id")),
            status=str(result.get("status", "completed")),
        )
    workflow_id = service.enqueue(payload)
    state = service.get_workflow(workflow_id) or {}
    return AnalyzeResponse(workflow_id=workflow_id, status=str(state.get("status", "queued")))


@router.get("/workflows/latest")
async def get_latest_workflow(
    service: IntelligenceService = Depends(get_service),
) -> dict:
    state = service.operational.get_latest_workflow()
    if state is None:
        return {"workflow_id": None, "status": "idle", "agent_runs": []}
    return _workflow_view(str(state.get("workflow_id")), state)


@router.get("/workflows/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    service: IntelligenceService = Depends(get_service),
) -> dict:
    state = service.get_workflow(workflow_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown workflow")
    return _workflow_view(workflow_id, state)


def _workflow_view(workflow_id: str, state: dict) -> dict:
    return {
        "workflow_id": workflow_id,
        "status": state.get("status"),
        "incident_id": state.get("incident_id"),
        "errors": state.get("errors") or [],
        "review_required": state.get("review_required"),
        "agent_runs": state.get("agent_runs") or [],
        "skip_signal": state.get("skip_signal", False),
        "skip_fusion": state.get("skip_fusion", False),
        "signal_analysis": state.get("signal_analysis"),
        "fusion_decisions": state.get("fusion_decisions") or [],
        "hypotheses": state.get("hypotheses") or [],
        "cascade_scenarios": state.get("cascade_scenarios") or [],
        "severity_assessment": state.get("severity_assessment"),
        "candidate_actions": state.get("candidate_actions") or [],
        "department_reports": state.get("department_reports") or [],
        "operator_summary": state.get("operator_summary"),
        "schema_version": state.get("schema_version"),
    }
