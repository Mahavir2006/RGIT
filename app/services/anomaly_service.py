"""Anomaly persistence and lifecycle.

Lifecycle rules (per condition fingerprint = rule + source category + subject + measurement):

* **create** — first firing: a new ACTIVE record.
* **update** — fires again while ACTIVE: occurrence count, latest value, peak severity updated; a
  history row is appended. No second active record is created for a persisting condition.
* **resolve** — a *later* reading of the same subject was evaluated by the same rule and did not
  fire. A missing measurement never resolves anything (absence is not evidence of normality), and
  a late-arriving normal reading older than the latest firing does not resolve it either.
* **reopen** — fires again after RESOLVED with an event newer than the resolution.
* **late** — fires on an event older than the resolution: recorded in history, no reopening.

Every action is idempotent via ``uq_anomaly_observation``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import ensure_aware
from app.db.processing_models import AnomalyModel, AnomalyObservationModel
from app.schemas.anomaly import SEVERITY_ORDINAL, AnomalyFinding, AnomalyStatus

__all__ = ["AnomalyService", "condition_fingerprint"]


def condition_fingerprint(rule_id: str, source_id: str, subject: str, measurement: str | None) -> str:
    key = "|".join([rule_id, source_id.split(".")[0], subject, measurement or "-"])
    return hashlib.sha256(key.encode()).hexdigest()[:32]


class AnomalyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get(self, fingerprint: str) -> AnomalyModel | None:
        return (await self.session.execute(
            select(AnomalyModel).where(AnomalyModel.fingerprint == fingerprint)
        )).scalar_one_or_none()

    async def _observe(self, row: AnomalyModel, event_id: str, action: str,
                       finding: AnomalyFinding | None, event_time: datetime | None,
                       run_id: str) -> bool:
        """Append a history row; returns False if this exact observation already exists."""
        exists = (await self.session.execute(
            select(AnomalyObservationModel.id).where(
                AnomalyObservationModel.anomaly_id == row.anomaly_id,
                AnomalyObservationModel.event_id == event_id,
                AnomalyObservationModel.action.in_(
                    ["created", "updated", "reopened", "late"] if action != "resolved"
                    else ["resolved"]),
            )
        )).first()
        if exists:
            return False
        try:
            async with self.session.begin_nested():
                self.session.add(AnomalyObservationModel(
                    anomaly_id=row.anomaly_id, event_id=event_id, action=action,
                    severity=finding.severity.value if finding else None,
                    observed_value=finding.observed_value if finding else None,
                    event_time=event_time,
                    finding=finding.model_dump(mode="json") if finding else {},
                    run_id=run_id,
                ))
        except IntegrityError:
            return False
        return True

    async def apply(
        self,
        findings: list[AnomalyFinding],
        *,
        event_id: str,
        event_time: datetime,
        run_id: str,
        processing_version: str,
        evaluated: list[tuple[str, str, str, str | None]] = (),  # type: ignore[assignment]
    ) -> list[str]:
        """Persist findings for one event; resolve evaluated-but-silent conditions.

        ``evaluated`` holds ``(rule_id, source_id, subject, measurement)`` for rules whose
        measurement was present and unit-compatible.
        """
        touched: list[str] = []
        fired: set[str] = set()
        for f in findings:
            fp = condition_fingerprint(f.rule_id, f.source_id, f.subject, f.measurement)
            fired.add(fp)
            row = await self._get(fp)
            if row is None:
                row = AnomalyModel(
                    anomaly_id=f"anm_{fp[:24]}", fingerprint=fp,
                    anomaly_type=f.anomaly_type.value, kind=f.kind.value,
                    status=AnomalyStatus.ACTIVE.value, severity=f.severity.value,
                    peak_severity=f.severity.value, rule_id=f.rule_id, rule_version=f.rule_version,
                    source_id=f.source_id, subject=f.subject, measurement=f.measurement,
                    unit=f.unit, latest_event_id=event_id, latest_value=f.observed_value,
                    latest_explanation=f.explanation, latest_finding=f.model_dump(mode="json"),
                    occurrence_count=1, first_seen_at=event_time, last_seen_at=event_time,
                    processing_run_id=run_id, processing_version=processing_version,
                )
                try:
                    async with self.session.begin_nested():
                        self.session.add(row)
                except IntegrityError:  # concurrent creator won; fall through to update
                    row = await self._get(fp)
                else:
                    await self._observe(row, event_id, "created", f, event_time, run_id)
                    touched.append(row.anomaly_id)
                    continue
            assert row is not None
            touched.append(row.anomaly_id)
            if row.status == AnomalyStatus.RESOLVED.value:
                if row.resolved_at is not None and event_time <= ensure_aware(row.resolved_at):
                    await self._observe(row, event_id, "late", f, event_time, run_id)
                    continue
                if await self._observe(row, event_id, "reopened", f, event_time, run_id):
                    row.status = AnomalyStatus.ACTIVE.value
                    row.reopen_count += 1
                    row.resolved_at = None
                    row.resolved_by_event_id = None
                    self._absorb(row, f, event_id, event_time, run_id)
                continue
            if await self._observe(row, event_id, "updated", f, event_time, run_id):
                self._absorb(row, f, event_id, event_time, run_id)

        for rule_id, source_id, subject, measurement in evaluated:
            fp = condition_fingerprint(rule_id, source_id, subject, measurement)
            if fp in fired:
                continue
            row = await self._get(fp)
            if row is None or row.status != AnomalyStatus.ACTIVE.value:
                continue
            if event_time <= ensure_aware(row.last_seen_at):
                continue  # late normal reading: does not clear a newer anomaly
            if await self._observe(row, event_id, "resolved", None, event_time, run_id):
                row.status = AnomalyStatus.RESOLVED.value
                row.resolved_at = event_time
                row.resolved_by_event_id = event_id
                touched.append(row.anomaly_id)
        await self.session.flush()
        return sorted(set(touched))

    @staticmethod
    def _absorb(row: AnomalyModel, f: AnomalyFinding, event_id: str, event_time: datetime,
                run_id: str) -> None:
        row.occurrence_count += 1
        if SEVERITY_ORDINAL[f.severity.value] > SEVERITY_ORDINAL[row.peak_severity]:
            row.peak_severity = f.severity.value
        # Current severity/value always describe the *latest observation in event time*, so a
        # late-arriving older reading never overwrites the present state.
        if event_time >= ensure_aware(row.last_seen_at):
            row.severity = f.severity.value
            row.last_seen_at = event_time
            row.latest_event_id = event_id
            row.latest_value = f.observed_value
            row.latest_explanation = f.explanation
            row.latest_finding = f.model_dump(mode="json")
        row.processing_run_id = run_id
