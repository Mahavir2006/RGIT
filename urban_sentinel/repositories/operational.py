from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from urban_sentinel.domain.models import (
    ALLOWED_HYPOTHESIS_TRANSITIONS,
    AuditRecord,
    HypothesisStatus,
    IncidentSummary,
    ReviewDecision,
)
from urban_sentinel.intelligence.exceptions import ConcurrentUpdateError
from urban_sentinel.intelligence.models import (
    CascadeScenario,
    DepartmentReport,
    DepartmentReportStatus,
    Hypothesis,
    ResponseRecommendation,
    WorkflowStatus,
)
from urban_sentinel.intelligence.state import IntelligenceState, empty_state


class OperationalRepository:
    """Authoritative incident, workflow, recommendation and audit store."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.incidents: dict[str, IncidentSummary] = {}
        self.workflows: dict[str, IntelligenceState] = {}
        self.hypotheses: dict[str, list[Hypothesis]] = {}
        self.scenarios: dict[str, list[CascadeScenario]] = {}
        self.recommendations: dict[str, list[ResponseRecommendation]] = {}
        self.department_reports: dict[str, list[DepartmentReport]] = {}
        self.audits: dict[str, list[AuditRecord]] = {}

    def get_incident(self, incident_id: str) -> IncidentSummary | None:
        return self.incidents.get(incident_id)

    def upsert_incident(self, incident: IncidentSummary, *, expected_version: int | None = None) -> IncidentSummary:
        with self._lock:
            current = self.incidents.get(incident.incident_id)
            if current is not None and expected_version is not None:
                if current.version != expected_version:
                    raise ConcurrentUpdateError(
                        f"incident {incident.incident_id} version {current.version} "
                        f"!= expected {expected_version}"
                    )
                incident.version = current.version + 1
            elif current is not None:
                incident.version = current.version + 1
            self.incidents[incident.incident_id] = incident
            return incident

    def attach_event(self, incident_id: str, event_id: str, *, expected_version: int | None) -> IncidentSummary:
        return self.attach_events(incident_id, [event_id], expected_version=expected_version)

    def attach_events(
        self, incident_id: str, event_ids: list[str], *, expected_version: int | None
    ) -> IncidentSummary:
        with self._lock:
            incident = self.incidents.get(incident_id)
            if incident is None:
                raise ConcurrentUpdateError(f"unknown incident {incident_id}")
            if expected_version is not None and incident.version != expected_version:
                raise ConcurrentUpdateError(
                    f"incident {incident_id} version {incident.version} != expected {expected_version}"
                )
            for event_id in event_ids:
                if event_id not in incident.associated_event_ids:
                    incident.associated_event_ids.append(event_id)
            incident.version += 1
            self.incidents[incident_id] = incident
            return incident

    def create_workflow(self, workflow_id: str) -> IntelligenceState:
        state = empty_state(workflow_id)
        state["status"] = WorkflowStatus.QUEUED.value
        self.workflows[workflow_id] = state
        return state

    def save_workflow(self, state: IntelligenceState) -> None:
        self.workflows[state["workflow_id"]] = state

    def get_workflow(self, workflow_id: str) -> IntelligenceState | None:
        return self.workflows.get(workflow_id)

    def get_latest_workflow(self) -> IntelligenceState | None:
        """Return the most recently created workflow for live operator views."""
        with self._lock:
            return next(reversed(self.workflows.values()), None)

    def replace_hypotheses(self, incident_id: str, items: list[Hypothesis]) -> None:
        by_id = {item.hypothesis_id: item for item in self.hypotheses.get(incident_id, [])}
        merged: dict[str, Hypothesis] = dict(by_id)
        for item in items:
            merged[item.hypothesis_id] = item
        self.hypotheses[incident_id] = list(merged.values())

    def get_hypotheses(self, incident_id: str) -> list[Hypothesis]:
        return list(self.hypotheses.get(incident_id, []))

    def replace_scenarios(self, incident_id: str, items: list[CascadeScenario]) -> None:
        by_id = {item.scenario_id: item for item in self.scenarios.get(incident_id, [])}
        for item in items:
            by_id[item.scenario_id] = item
        self.scenarios[incident_id] = list(by_id.values())

    def get_scenarios(self, incident_id: str) -> list[CascadeScenario]:
        return list(self.scenarios.get(incident_id, []))

    def replace_recommendations(
        self, incident_id: str, items: list[ResponseRecommendation]
    ) -> None:
        by_id = {item.action_id: item for item in self.recommendations.get(incident_id, [])}
        for item in items:
            by_id[item.action_id] = item
        self.recommendations[incident_id] = list(by_id.values())

    def get_recommendations(self, incident_id: str) -> list[ResponseRecommendation]:
        return list(self.recommendations.get(incident_id, []))

    def replace_department_reports(self, incident_id: str, items: list[DepartmentReport]) -> None:
        with self._lock:
            existing = {item.report_id: item for item in self.department_reports.get(incident_id, [])}
            for item in items:
                current = existing.get(item.report_id)
                # A workflow rerun must never reset an operator-submitted report to draft.
                if current and current.status == DepartmentReportStatus.QUEUED:
                    continue
                if current and current.routing_reason.startswith("Recipient selected by operator"):
                    item = item.model_copy(update={
                        "department_id": current.department_id,
                        "department_name": current.department_name,
                        "routing_reason": current.routing_reason,
                        "routing_confidence": current.routing_confidence,
                    })
                existing[item.report_id] = item
            self.department_reports[incident_id] = list(existing.values())

    def get_department_reports(self, incident_id: str) -> list[DepartmentReport]:
        with self._lock:
            return list(self.department_reports.get(incident_id, []))

    def submit_department_report(
        self, incident_id: str, report_id: str, *, actor: str
    ) -> DepartmentReport | None:
        with self._lock:
            items = self.department_reports.get(incident_id, [])
            for index, item in enumerate(items):
                if item.report_id != report_id:
                    continue
                if item.department_id is None or item.status == DepartmentReportStatus.NEEDS_ROUTING_REVIEW:
                    return None
                if item.status == DepartmentReportStatus.QUEUED:
                    return item
                updated = item.model_copy(update={
                    "status": DepartmentReportStatus.QUEUED,
                    "delivery_status": "not_configured",
                    "submitted_at": datetime.now(UTC),
                    "submitted_by": actor,
                })
                items[index] = updated
                self.audits.setdefault(incident_id, []).append(
                    AuditRecord(
                        audit_id=str(uuid4()),
                        incident_id=incident_id,
                        actor=actor,
                        decision=ReviewDecision.SUBMIT_DEPARTMENT_REPORT,
                        target_id=report_id,
                        notes="Department report queued internally; external delivery is not configured.",
                        created_at=datetime.now(UTC),
                    )
                )
                return updated
            return None

    def route_department_report(
        self, incident_id: str, report_id: str, *, department_id: str, department_name: str, actor: str
    ) -> DepartmentReport | None:
        with self._lock:
            items = self.department_reports.get(incident_id, [])
            for index, item in enumerate(items):
                if item.report_id != report_id or item.status == DepartmentReportStatus.QUEUED:
                    continue
                updated = item.model_copy(update={
                    "department_id": department_id,
                    "department_name": department_name,
                    "routing_reason": f"Recipient selected by operator {actor}.",
                    "routing_confidence": 1.0,
                    "status": DepartmentReportStatus.DRAFT,
                })
                items[index] = updated
                self.audits.setdefault(incident_id, []).append(
                    AuditRecord(
                        audit_id=str(uuid4()), incident_id=incident_id, actor=actor,
                        decision=ReviewDecision.ROUTE_DEPARTMENT_REPORT, target_id=report_id,
                        notes=f"Recipient set to {department_id}.", created_at=datetime.now(UTC),
                    )
                )
                return updated
            return None

    def record_review(
        self,
        *,
        incident_id: str,
        actor: str,
        decision: ReviewDecision,
        target_id: str | None,
        notes: str | None,
    ) -> AuditRecord:
        record = AuditRecord(
            audit_id=str(uuid4()),
            incident_id=incident_id,
            actor=actor,
            decision=decision,
            target_id=target_id,
            notes=notes,
            created_at=datetime.now(UTC),
        )
        self.audits.setdefault(incident_id, []).append(record)
        if decision in {ReviewDecision.SUPPORT_HYPOTHESIS, ReviewDecision.REJECT_HYPOTHESIS} and target_id:
            new_status = (
                HypothesisStatus.SUPPORTED
                if decision == ReviewDecision.SUPPORT_HYPOTHESIS
                else HypothesisStatus.REJECTED
            )
            updated: list[Hypothesis] = []
            for hyp in self.get_hypotheses(incident_id):
                if hyp.hypothesis_id == target_id:
                    allowed = ALLOWED_HYPOTHESIS_TRANSITIONS[hyp.status]
                    if new_status not in allowed and new_status != hyp.status:
                        hyp = hyp.model_copy(
                            update={"status": HypothesisStatus.UNDER_REVIEW}
                        )
                    else:
                        hyp = hyp.model_copy(update={"status": new_status})
                updated.append(hyp)
            self.hypotheses[incident_id] = updated
        return record

    def get_audits(self, incident_id: str) -> list[AuditRecord]:
        return list(self.audits.get(incident_id, []))
