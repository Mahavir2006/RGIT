from __future__ import annotations

from datetime import UTC, datetime
import json
from uuid import NAMESPACE_URL, uuid5

from urban_sentinel.domain.departments import departments_by_id
from urban_sentinel.domain.models import EventType, ProcessedWorkflowInput
from urban_sentinel.intelligence.models import DepartmentReport, DepartmentReportStatus, Hypothesis


_ROUTE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("drainage", ("drain", "stormwater", "culvert", "sewer", "catch basin", "flood channel")),
    ("water_resources", ("water supply", "reservoir", "water main", "water-level", "water level", "gauge")),
    ("roads_traffic", ("road", "traffic", "underpass", "highway", "bridge", "congestion")),
    ("environment", ("air quality", "pollution", "smog", "environment")),
)
_TYPE_ROUTE = {
    EventType.WATER_LEVEL: "water_resources",
    EventType.TRAFFIC: "roads_traffic",
    EventType.AIR_QUALITY: "environment",
}


def _route(text: str) -> str | None:
    normalized = text.casefold().replace("_", " ")
    return next(
        (department_id for department_id, terms in _ROUTE_RULES
         if any(term in normalized for term in terms)),
        None,
    )


def build_department_reports(
    payload: ProcessedWorkflowInput,
    *,
    hypotheses: list[Hypothesis],
    evidence_gaps: list[str],
) -> list[DepartmentReport]:
    incident = payload.incident
    incident_id = payload.incident_id or (incident.incident_id if incident else "unknown")
    if incident_id == "unknown":
        return []
    directory = departments_by_id()
    routes: dict[str, dict] = {}

    for hypothesis in hypotheses:
        if hypothesis.status.value == "REJECTED":
            continue
        department_id = _route(hypothesis.claim)
        if not department_id:
            continue
        current = routes.get(department_id)
        if current is None or (hypothesis.score or 0) > ((current["hypothesis"].score or 0) if current["hypothesis"] else -1):
            routes[department_id] = {
                "hypothesis": hypothesis,
                "alternatives": [current["hypothesis"].claim] if current and current["hypothesis"] else [],
                "assets": current["assets"] if current else [],
                "events": current["events"] if current else [],
                "reason": f"Cause hypothesis maps to {directory[department_id].name} under the department routing registry.",
                "confidence": 0.82 if hypothesis.status.value == "SUPPORTED" else 0.68,
            }
        elif current["hypothesis"]:
            current["alternatives"].append(hypothesis.claim)

    incident_asset_ids = set(incident.asset_ids if incident else [])
    for asset in payload.assets:
        if incident_asset_ids and asset.asset_id not in incident_asset_ids:
            continue
        department_id = _route(f"{asset.name} {asset.asset_type} {asset.asset_id}")
        if not department_id:
            continue
        entry = routes.setdefault(department_id, {
            "hypothesis": None, "alternatives": [], "assets": [], "events": [],
            "reason": f"Incident references an asset maintained by {directory[department_id].name}.",
            "confidence": 0.9,
        })
        entry["assets"].append(asset.asset_id)
        entry["confidence"] = max(entry["confidence"], 0.9)

    incident_text = " ".join(filter(None, [incident.title, incident.summary])) if incident else ""
    incident_department = _route(incident_text)
    if incident_department:
        routes.setdefault(incident_department, {
            "hypothesis": None, "alternatives": [], "assets": [], "events": [],
            "reason": f"Incident description maps to {directory[incident_department].name}; routing remains subject to review.",
            "confidence": 0.62,
        })

    for event in payload.normalized_events:
        event_text = " ".join(filter(None, [event.text, json.dumps(event.attributes, sort_keys=True)]))
        department_id = _route(event_text)
        if not department_id:
            continue
        entry = routes.setdefault(department_id, {
            "hypothesis": None, "alternatives": [], "assets": [], "events": [],
            "reason": f"Event details map to {directory[department_id].name}; routing remains subject to review.",
            "confidence": 0.7,
        })
        entry["events"].append(event.event_id)

    if not routes:
        for event in payload.normalized_events:
            department_id = _TYPE_ROUTE.get(event.event_type)
            if department_id:
                entry = routes.setdefault(department_id, {
                    "hypothesis": None, "alternatives": [], "assets": [], "events": [],
                    "reason": f"Incident evidence includes {event.event_type.value.replace('_', ' ')} signals; assignment is provisional.",
                    "confidence": 0.58,
                })
                entry["events"].append(event.event_id)
    if not routes:
        routes[""] = {
            "hypothesis": None, "alternatives": [], "assets": [], "events": [],
            "reason": "Available evidence does not support a specific department assignment.",
            "confidence": 0.0,
        }

    location = incident.location.model_dump(mode="json") if incident and incident.location else None
    if location is None:
        location = next(
            (event.location.model_dump(mode="json") for event in payload.normalized_events if event.location),
            None,
        )
    event_ids = {event.event_id for event in payload.normalized_events}
    reports: list[DepartmentReport] = []
    for department_id, route in sorted(routes.items()):
        hypothesis: Hypothesis | None = route["hypothesis"]
        cited_events = []
        if hypothesis:
            cited_events = [
                item for item in [*hypothesis.supporting_event_ids, *hypothesis.contradicting_event_ids]
                if item in event_ids
            ]
        cited_events.extend(item for item in route["events"] if item in event_ids)
        if not cited_events and not hypothesis:
            cited_events = [item for item in payload.trigger_event_ids if item in event_ids]
        department = directory.get(department_id)
        unresolved = department is None
        uncertainty = list(hypothesis.limitations if hypothesis else [])
        uncertainty.extend(evidence_gaps)
        uncertainty.extend(route["alternatives"])
        if hypothesis and hypothesis.status.value != "SUPPORTED":
            uncertainty.append(f"Cause remains {hypothesis.status.value.lower()}; it is not asserted as confirmed.")
        summary = (
            f"Incident {incident_id}: observed signals relate to {department.name.lower()}."
            if department else f"Incident {incident_id}: evidence is available, but the responsible department is undetermined."
        )
        if hypothesis:
            summary += f" Current hypothesis: {hypothesis.claim}."
        key = f"{incident_id}/{department_id or 'unassigned'}/{hypothesis.hypothesis_id if hypothesis else 'signals'}"
        reports.append(DepartmentReport(
            report_id=str(uuid5(NAMESPACE_URL, key)),
            incident_id=incident_id,
            department_id=department_id or None,
            department_name=department.name if department else "Needs department routing",
            routing_reason=route["reason"],
            routing_confidence=route["confidence"],
            location=location,
            subject=f"Incident {incident_id}: {incident.title if incident else 'Department follow-up'}",
            summary=summary,
            cause_hypothesis_id=hypothesis.hypothesis_id if hypothesis else None,
            cause_claim=hypothesis.claim if hypothesis else None,
            cause_status=hypothesis.status.value if hypothesis else None,
            cause_score=hypothesis.score if hypothesis else None,
            evidence_event_ids=sorted(set(cited_events)),
            asset_ids=sorted(set(route["assets"])),
            requested_follow_up=(
                f"Please assess the reported {department.name.lower()} issue and update incident {incident_id}."
                if department else "Please review the evidence and assign the responsible department."
            ),
            uncertainties=sorted(set(uncertainty)),
            status=DepartmentReportStatus.NEEDS_ROUTING_REVIEW if unresolved else DepartmentReportStatus.DRAFT,
            created_at=datetime.now(UTC),
        ))
    return reports
