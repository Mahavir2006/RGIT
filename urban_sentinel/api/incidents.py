from __future__ import annotations

import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException
from urban_sentinel.intelligence.models import DepartmentReportStatus

from urban_sentinel.api.deps import get_service, require_reviewer
from urban_sentinel.api.schemas import DepartmentReportRouteRequest, DepartmentReportSubmitRequest, ReviewRequest
from urban_sentinel.domain.departments import departments_by_id
from urban_sentinel.domain.models import ReviewDecision
from urban_sentinel.intelligence.service import IntelligenceService
from urban_sentinel.intelligence.department_delivery import deliver_report

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


@router.get("/{incident_id}/department-reports")
async def get_department_reports(
    incident_id: str, service: IntelligenceService = Depends(get_service)
) -> dict:
    items = service.operational.get_department_reports(incident_id)
    return {"incident_id": incident_id, "reports": [item.model_dump(mode="json") for item in items]}


@router.patch("/{incident_id}/department-reports/{report_id}/route")
async def route_department_report(
    incident_id: str,
    report_id: str,
    body: DepartmentReportRouteRequest,
    service: IntelligenceService = Depends(get_service),
    actor: str = Depends(require_reviewer),
) -> dict:
    department = departments_by_id().get(body.department_id)
    if department is None:
        raise HTTPException(status_code=422, detail="Unknown department")
    report = service.operational.route_department_report(
        incident_id, report_id, department_id=department.department_id,
        department_name=department.name, actor=actor,
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Unknown or already queued department report")
    return {"report": report.model_dump(mode="json")}


@router.post("/{incident_id}/department-reports/{report_id}/submit")
async def submit_department_report(
    incident_id: str,
    report_id: str,
    body: DepartmentReportSubmitRequest,
    service: IntelligenceService = Depends(get_service),
    actor: str = Depends(require_reviewer),
) -> dict:
    if not body.confirm:
        raise HTTPException(status_code=422, detail="Explicit confirmation is required")
    report = service.operational.submit_department_report(incident_id, report_id, actor=actor)
    if report is None:
        raise HTTPException(status_code=409, detail="Report needs a valid department recipient before submission")
    status_token = secrets.token_urlsafe(32)
    service.operational.set_report_status_token(report_id, hashlib.sha256(status_token.encode()).hexdigest())
    try:
        report = await deliver_report(service, report, actor=actor)
    except ValueError as exc:
        report = service.operational.update_department_report(
            incident_id, report_id, status=DepartmentReportStatus.DELIVERY_FAILED,
            delivery_status="failed", delivery_error=str(exc), actor=actor,
        ) or report
    return {
        "report": report.model_dump(mode="json"),
        "resident_status_token": status_token,
        "resident_status_url": (
            f"{service.settings.public_web_base_url.rstrip('/')}/track-report#{status_token}"
            if service.settings.public_web_base_url else None
        ),
        "message": (
            "Report delivered to the configured department webhook."
            if report.delivery_status == "delivered"
            else "Report is durably stored, but department delivery is not confirmed."
        ),
    }


@router.post("/{incident_id}/review")
async def review_incident(
    incident_id: str,
    body: ReviewRequest,
    service: IntelligenceService = Depends(get_service),
    actor: str = Depends(require_reviewer),
) -> dict:
    if body.decision in {
        ReviewDecision.SUBMIT_DEPARTMENT_REPORT,
        ReviewDecision.ROUTE_DEPARTMENT_REPORT,
    }:
        raise HTTPException(status_code=422, detail="Use the department report endpoints for report actions")
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
