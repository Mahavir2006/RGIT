from __future__ import annotations

from datetime import UTC, datetime
import os
import json
import sqlite3
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

    def __init__(self, report_store_path: str | None = None) -> None:
        self._lock = Lock()
        self.incidents: dict[str, IncidentSummary] = {}
        self.workflows: dict[str, IntelligenceState] = {}
        self.hypotheses: dict[str, list[Hypothesis]] = {}
        self.scenarios: dict[str, list[CascadeScenario]] = {}
        self.recommendations: dict[str, list[ResponseRecommendation]] = {}
        self.department_reports: dict[str, list[DepartmentReport]] = {}
        self.audits: dict[str, list[AuditRecord]] = {}
        self._report_store_path = report_store_path or ":memory:"
        if self._report_store_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self._report_store_path)), exist_ok=True)
        self._report_connection = sqlite3.connect(
            self._report_store_path, timeout=15, check_same_thread=False
        )
        self._report_connection.row_factory = sqlite3.Row
        with self._report_db() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS department_reports "
                "(report_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, payload TEXT NOT NULL, "
                "status_token_hash TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_department_reports_incident "
                "ON department_reports(incident_id, created_at)"
            )
            rows = connection.execute(
                "SELECT report_id, incident_id, payload FROM department_reports"
            ).fetchall()
        for row in rows:
            report = self._parse_persisted_report(row["payload"])
            if report is not None:
                self.department_reports.setdefault(row["incident_id"], []).append(report)

    def _report_db(self) -> sqlite3.Connection:
        return self._report_connection

    @staticmethod
    def _parse_persisted_report(payload_json: str) -> DepartmentReport | None:
        try:
            payload = json.loads(payload_json)
            if payload.get("status") == "queued":
                payload["status"] = DepartmentReportStatus.DELIVERY_PENDING.value
            return DepartmentReport.model_validate(payload)
        except (ValueError, TypeError):
            return None

    def _refresh_department_reports(self, incident_id: str) -> list[DepartmentReport]:
        rows = self._report_db().execute(
            "SELECT payload FROM department_reports WHERE incident_id = ? ORDER BY created_at",
            (incident_id,),
        ).fetchall()
        reports = [report for row in rows if (report := self._parse_persisted_report(row["payload"]))]
        self.department_reports[incident_id] = reports
        return reports

    def _persist_report(self, report: DepartmentReport, *, status_token_hash: str | None = None) -> None:
        with self._report_db() as connection:
            connection.execute(
                "INSERT INTO department_reports(report_id, incident_id, payload, status_token_hash, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(report_id) DO UPDATE SET "
                "incident_id=excluded.incident_id, payload=excluded.payload, "
                "status_token_hash=COALESCE(excluded.status_token_hash, department_reports.status_token_hash), "
                "updated_at=excluded.updated_at",
                (report.report_id, report.incident_id, report.model_dump_json(), status_token_hash,
                 report.created_at.isoformat(), datetime.now(UTC).isoformat()),
            )

    def find_report_by_status_token(self, token_hash: str) -> DepartmentReport | None:
        with self._report_db() as connection:
            row = connection.execute(
                "SELECT payload FROM department_reports WHERE status_token_hash = ?", (token_hash,)
            ).fetchone()
        return self._parse_persisted_report(row["payload"]) if row else None

    def get_department_report(self, report_id: str) -> DepartmentReport | None:
        with self._report_db() as connection:
            row = connection.execute(
                "SELECT payload FROM department_reports WHERE report_id = ?", (report_id,)
            ).fetchone()
        return self._parse_persisted_report(row["payload"]) if row else None

    def set_report_status_token(self, report_id: str, token_hash: str) -> None:
        with self._report_db() as connection:
            connection.execute(
                "UPDATE department_reports SET status_token_hash = ? WHERE report_id = ?",
                (token_hash, report_id),
            )

    def update_department_report(
        self, incident_id: str, report_id: str, *, status: DepartmentReportStatus | None = None,
        delivery_status: str | None = None, delivery_error: str | None = None,
        external_reference: str | None = None, actor: str = "system", notes: str | None = None,
        increment_delivery_attempts: bool = False,
    ) -> DepartmentReport | None:
        with self._lock:
            reports = self._refresh_department_reports(incident_id)
            for index, report in enumerate(reports):
                if report.report_id != report_id:
                    continue
                now = datetime.now(UTC)
                changes: dict = {"updated_at": now}
                if status is not None:
                    # A webhook callback may acknowledge a report before its HTTP response
                    # returns. Never let the delivery response move that report backwards.
                    current_status = report.status
                    if status == DepartmentReportStatus.DELIVERED and current_status != DepartmentReportStatus.DELIVERY_PENDING:
                        status = current_status
                    if status == DepartmentReportStatus.DELIVERY_FAILED and current_status in {
                        DepartmentReportStatus.ACKNOWLEDGED, DepartmentReportStatus.IN_PROGRESS,
                        DepartmentReportStatus.RESOLVED,
                    }:
                        status = current_status
                    changes["status"] = status
                    if status == DepartmentReportStatus.ACKNOWLEDGED:
                        changes["acknowledged_at"] = report.acknowledged_at or now
                    if status == DepartmentReportStatus.RESOLVED:
                        changes["resolved_at"] = report.resolved_at or now
                if delivery_status is not None:
                    changes["delivery_status"] = delivery_status
                if delivery_error is not None or delivery_status == "delivered":
                    changes["last_delivery_error"] = delivery_error
                if external_reference is not None:
                    changes["external_reference"] = external_reference
                if increment_delivery_attempts:
                    changes["delivery_attempts"] = report.delivery_attempts + 1
                updated = report.model_copy(update=changes)
                if status is not None or delivery_status is not None:
                    updated.status_history = report.status_history + [{
                        "status": updated.status.value,
                        "delivery_status": updated.delivery_status,
                        "at": now.isoformat(),
                        "actor": actor,
                        "note": notes,
                    }]
                reports[index] = updated
                self._persist_report(updated)
                self.audits.setdefault(incident_id, []).append(AuditRecord(
                    audit_id=str(uuid4()), incident_id=incident_id, actor=actor,
                    decision=ReviewDecision.UPDATE_DEPARTMENT_REPORT, target_id=report_id,
                    notes=notes or f"Report status updated to {updated.status.value}.", created_at=now,
                ))
                return updated
        return None

    def retry_department_report(self, incident_id: str, report_id: str, *, actor: str) -> DepartmentReport | None:
        with self._lock:
            items = self._refresh_department_reports(incident_id)
            for index, item in enumerate(items):
                retryable = item.status == DepartmentReportStatus.DELIVERY_FAILED or (
                    item.status == DepartmentReportStatus.DELIVERY_PENDING
                    and item.delivery_status == "not_configured"
                )
                if item.report_id != report_id or not retryable:
                    continue
                updated = item.model_copy(update={
                    "status": DepartmentReportStatus.DELIVERY_PENDING,
                    "delivery_status": "pending",
                    "last_delivery_error": None,
                })
                items[index] = updated
                self._persist_report(updated)
                self.audits.setdefault(incident_id, []).append(AuditRecord(
                    audit_id=str(uuid4()), incident_id=incident_id, actor=actor,
                    decision=ReviewDecision.SUBMIT_DEPARTMENT_REPORT, target_id=report_id,
                    notes="Operator requested a department webhook delivery retry.", created_at=datetime.now(UTC),
                ))
                return updated
        return None

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
            existing = {item.report_id: item for item in self._refresh_department_reports(incident_id)}
            for item in items:
                current = existing.get(item.report_id)
                # A workflow rerun must never reset an operator-submitted report to draft.
                if current and current.status not in {
                    DepartmentReportStatus.DRAFT, DepartmentReportStatus.NEEDS_ROUTING_REVIEW,
                }:
                    continue
                if current and current.routing_reason.startswith("Recipient selected by operator"):
                    item = item.model_copy(update={
                        "department_id": current.department_id,
                        "department_name": current.department_name,
                        "routing_reason": current.routing_reason,
                        "routing_confidence": current.routing_confidence,
                    })
                existing[item.report_id] = item
                self._persist_report(item)
            self.department_reports[incident_id] = list(existing.values())

    def get_department_reports(self, incident_id: str) -> list[DepartmentReport]:
        with self._lock:
            return list(self._refresh_department_reports(incident_id))

    def submit_department_report(
        self, incident_id: str, report_id: str, *, actor: str
    ) -> DepartmentReport | None:
        with self._lock:
            # Reserve the SQLite write lock before checking state so concurrent workers cannot
            # both dispatch the same draft. The outbound Idempotency-Key is a second guard.
            self._report_db().execute("BEGIN IMMEDIATE")
            items = self._refresh_department_reports(incident_id)
            for index, item in enumerate(items):
                if item.report_id != report_id:
                    continue
                if item.department_id is None or item.status == DepartmentReportStatus.NEEDS_ROUTING_REVIEW:
                    self._report_db().rollback()
                    return None
                if item.status not in {DepartmentReportStatus.DRAFT, DepartmentReportStatus.NEEDS_ROUTING_REVIEW}:
                    self._report_db().rollback()
                    return None
                updated = item.model_copy(update={
                    "status": DepartmentReportStatus.DELIVERY_PENDING,
                    "delivery_status": "pending",
                    "submitted_at": datetime.now(UTC),
                    "submitted_by": actor,
                    "updated_at": datetime.now(UTC),
                    "status_history": item.status_history + [{
                        "status": DepartmentReportStatus.DELIVERY_PENDING.value,
                        "delivery_status": "pending", "at": datetime.now(UTC).isoformat(),
                        "actor": actor, "note": "Submitted by operator.",
                    }],
                })
                items[index] = updated
                self._persist_report(updated)
                self.audits.setdefault(incident_id, []).append(
                    AuditRecord(
                        audit_id=str(uuid4()),
                        incident_id=incident_id,
                        actor=actor,
                        decision=ReviewDecision.SUBMIT_DEPARTMENT_REPORT,
                        target_id=report_id,
                        notes="Department report accepted for delivery.",
                        created_at=datetime.now(UTC),
                    )
                )
                return updated
            self._report_db().rollback()
            return None

    def route_department_report(
        self, incident_id: str, report_id: str, *, department_id: str, department_name: str, actor: str
    ) -> DepartmentReport | None:
        with self._lock:
            items = self._refresh_department_reports(incident_id)
            for index, item in enumerate(items):
                if item.report_id != report_id or item.status not in {
                    DepartmentReportStatus.DRAFT, DepartmentReportStatus.NEEDS_ROUTING_REVIEW,
                }:
                    continue
                updated = item.model_copy(update={
                    "department_id": department_id,
                    "department_name": department_name,
                    "routing_reason": f"Recipient selected by operator {actor}.",
                    "routing_confidence": 1.0,
                    "status": DepartmentReportStatus.DRAFT,
                })
                items[index] = updated
                self._persist_report(updated)
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
