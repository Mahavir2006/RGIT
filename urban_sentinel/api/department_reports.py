from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException

from urban_sentinel.api.deps import get_service, require_reviewer
from urban_sentinel.api.schemas import DepartmentReportStatusRequest
from urban_sentinel.intelligence.models import DepartmentReportStatus
from urban_sentinel.intelligence.department_delivery import configured_tokens
from urban_sentinel.intelligence.service import IntelligenceService

router = APIRouter(tags=["department reports"])
DEPARTMENT_STATUS_UPDATES = {
    DepartmentReportStatus.ACKNOWLEDGED,
    DepartmentReportStatus.IN_PROGRESS,
    DepartmentReportStatus.RESOLVED,
}


@router.get("/api/v1/report-status")
async def resident_report_status(
    authorization: str | None = Header(default=None),
    service: IntelligenceService = Depends(get_service),
) -> dict:
    """Privacy-safe tracking view. The high-entropy bearer token is issued at submission."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="A report tracking token is required")
    token_hash = hashlib.sha256(authorization[7:].strip().encode()).hexdigest()
    report = service.operational.find_report_by_status_token(token_hash)
    if report is None:
        raise HTTPException(status_code=404, detail="Report tracking token is unknown")
    return {
        "report_id": report.report_id,
        "incident_id": report.incident_id,
        "department_name": report.department_name,
        "status": report.status.value,
        "delivery_status": report.delivery_status,
        "submitted_at": report.submitted_at,
        "acknowledged_at": report.acknowledged_at,
        "resolved_at": report.resolved_at,
        "external_reference": report.external_reference,
        "status_history": [
            {key: value for key, value in entry.items() if key != "actor"}
            for entry in report.status_history
        ],
    }


@router.post("/api/v1/department-reports/{report_id}/status")
async def update_department_report_status(
    report_id: str,
    body: DepartmentReportStatusRequest,
    authorization: str | None = Header(default=None),
    service: IntelligenceService = Depends(get_service),
) -> dict:
    supplied = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
    if body.status not in DEPARTMENT_STATUS_UPDATES:
        raise HTTPException(status_code=422, detail="Departments may acknowledge, start, or resolve a report")
    current = service.operational.get_department_report(report_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Unknown report")
    try:
        update_tokens = configured_tokens(service.settings.department_update_tokens)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Department status callback configuration is invalid") from exc
    expected_token = update_tokens.get(current.department_id or "") or service.settings.department_update_token
    if not expected_token:
        raise HTTPException(status_code=503, detail="Department status callbacks are not configured")
    if not hmac.compare_digest(supplied, expected_token):
        raise HTTPException(status_code=401, detail="Invalid department integration token")
    allowed = {
        DepartmentReportStatus.ACKNOWLEDGED: {
            DepartmentReportStatus.DELIVERY_PENDING, DepartmentReportStatus.DELIVERED,
            DepartmentReportStatus.ACKNOWLEDGED,
        },
        DepartmentReportStatus.IN_PROGRESS: {
            DepartmentReportStatus.DELIVERED, DepartmentReportStatus.ACKNOWLEDGED,
            DepartmentReportStatus.IN_PROGRESS,
        },
        DepartmentReportStatus.RESOLVED: {
            DepartmentReportStatus.DELIVERED, DepartmentReportStatus.ACKNOWLEDGED,
            DepartmentReportStatus.IN_PROGRESS, DepartmentReportStatus.RESOLVED,
        },
    }
    if current.status not in allowed[body.status]:
        raise HTTPException(status_code=409, detail=f"Cannot move report from {current.status.value} to {body.status.value}")
    updated = service.operational.update_department_report(
        current.incident_id, report_id, status=body.status,
        delivery_status=("delivered" if current.delivery_status in {"pending", "not_configured"} else None),
        external_reference=body.external_reference, actor=f"department:{current.department_id}",
        notes=f"Department reported status {body.status.value}.",
    )
    return {"report_id": report_id, "status": updated.status.value if updated else body.status.value}


@router.post("/api/v1/incidents/{incident_id}/department-reports/{report_id}/retry")
async def retry_department_report(
    incident_id: str,
    report_id: str,
    service: IntelligenceService = Depends(get_service),
    actor: str = Depends(require_reviewer),
) -> dict:
    report = service.operational.retry_department_report(incident_id, report_id, actor=actor)
    if report is None:
        raise HTTPException(status_code=409, detail="Only failed or unconfigured deliveries can be retried")
    from urban_sentinel.intelligence.department_delivery import deliver_report

    try:
        report = await deliver_report(service, report, actor=actor)
    except ValueError as exc:
        report = service.operational.update_department_report(
            incident_id, report_id, status=DepartmentReportStatus.DELIVERY_FAILED,
            delivery_status="failed", delivery_error=str(exc), actor=actor,
        ) or report
    return {"report": report.model_dump(mode="json")}
