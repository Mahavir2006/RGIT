from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx

from urban_sentinel.intelligence.models import DepartmentReport, DepartmentReportStatus
from urban_sentinel.intelligence.service import IntelligenceService


def configured_webhooks(service: IntelligenceService) -> dict[str, str]:
    try:
        configured = json.loads(service.settings.department_webhooks)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("URBAN_SENTINEL_DEPARTMENT_WEBHOOKS must be a JSON object") from exc
    if not isinstance(configured, dict):
        raise ValueError("URBAN_SENTINEL_DEPARTMENT_WEBHOOKS must be a JSON object")
    result: dict[str, str] = {}
    for department_id, endpoint in configured.items():
        parsed = urlparse(str(endpoint))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"Webhook for {department_id} must be an HTTPS URL without embedded credentials")
        result[str(department_id)] = str(endpoint)
    return result


def configured_tokens(raw: str) -> dict[str, str]:
    try:
        configured = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Department token configuration must be a JSON object") from exc
    if not isinstance(configured, dict):
        raise ValueError("Department token configuration must be a JSON object")
    return {str(key): str(value) for key, value in configured.items() if value}


async def deliver_report(
    service: IntelligenceService, report: DepartmentReport, *, actor: str = "system"
) -> DepartmentReport:
    endpoints = configured_webhooks(service)
    endpoint = endpoints.get(report.department_id or "")
    if not endpoint:
        updated = service.operational.update_department_report(
            report.incident_id, report.report_id, delivery_status="not_configured",
            delivery_error=None, actor=actor,
            notes=f"No HTTPS webhook configured for department {report.department_id}.",
        )
        return updated or report

    headers = {"Idempotency-Key": report.report_id, "Content-Type": "application/json"}
    webhook_tokens = configured_tokens(service.settings.department_webhook_tokens)
    webhook_token = webhook_tokens.get(report.department_id or "") or service.settings.department_webhook_token
    if webhook_token:
        headers["Authorization"] = f"Bearer {webhook_token}"
    callback_url = None
    if service.settings.public_api_base_url:
        callback_url = (
            f"{service.settings.public_api_base_url.rstrip('/')}/api/v1/department-reports/"
            f"{report.report_id}/status"
        )
    body = {
        "report": report.model_dump(mode="json"),
        "status_callback_url": callback_url,
    }
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=False) as client:
            response = await client.post(endpoint, json=body, headers=headers)
        if 200 <= response.status_code < 300:
            try:
                response_body = response.json()
            except ValueError:
                response_body = {}
            external_reference = response_body.get("external_reference") if isinstance(response_body, dict) else None
            updated = service.operational.update_department_report(
                report.incident_id, report.report_id,
                status=DepartmentReportStatus.DELIVERED,
                delivery_status="delivered", delivery_error=None,
                external_reference=external_reference, actor=actor,
                increment_delivery_attempts=True,
                notes=f"Department webhook accepted the report (HTTP {response.status_code}).",
            )
        else:
            updated = service.operational.update_department_report(
                report.incident_id, report.report_id,
                status=DepartmentReportStatus.DELIVERY_FAILED,
                delivery_status="failed", delivery_error=f"Department endpoint returned HTTP {response.status_code}.",
                actor=actor, increment_delivery_attempts=True,
                notes=f"Department webhook rejected the report (HTTP {response.status_code}).",
            )
    except httpx.HTTPError as exc:
        updated = service.operational.update_department_report(
            report.incident_id, report.report_id,
            status=DepartmentReportStatus.DELIVERY_FAILED,
            delivery_status="failed", delivery_error=type(exc).__name__, actor=actor,
            increment_delivery_attempts=True,
            notes=f"Department webhook delivery failed ({type(exc).__name__}).",
        )
    return updated or report
