"""Processing orchestrator: loads bounded context, runs the pure pipeline, persists results.

Idempotency and retry safety
----------------------------
* Each (event, processing_version) is *claimed* by inserting its ``event_processing`` row under a
  unique constraint. A concurrent or repeated request hits the constraint and returns ``REUSED``
  with the stored result — no second set of anomaly or candidate effects is produced.
* ``force=True`` recomputes, but anomaly observations and candidate rows are themselves unique, so
  forcing never duplicates effects either; only ``attempts`` and the run history change.

Failure isolation
-----------------
Every event runs in its own session/transaction. A malformed event or a stage error is recorded
as ``FAILED``/``QUARANTINED``/``REJECTED`` for that event and the batch continues. The run status
distinguishes COMPLETED, COMPLETED_WITH_WARNINGS, PARTIALLY_FAILED and FAILED.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.core.timeutil import ensure_aware, utc_now
from app.db.models import EventModel, QuarantineModel, SourceHealthModel
from app.db.processing_models import (
    AnomalyObservationModel,
    EventProcessingModel,
    ProcessingRunModel,
)
from app.processing.anomaly import (
    AnomalyContext,
    Reading,
    detect_repeated_malformed,
    detect_stale_source,
)
from app.processing.config import ProcessingConfig
from app.processing.correlation import subject_of
from app.processing.pipeline import evaluate_event, match_event
from app.schemas.event import CanonicalEvent
from app.schemas.processing import (
    DedupDecision,
    EventProcessingStatus,
    ProcessingRunStatus,
    ValidationVerdict,
)
from app.services.anomaly_service import AnomalyService
from app.services.candidate_service import CandidateService
from app.services.event_service import EventService

__all__ = ["ProcessingService"]

logger = get_logger(__name__)

_HISTORY_LIMIT = 200
_NEIGHBOUR_LIMIT = 50


def new_processing_run_id() -> str:
    return f"prun_{utc_now().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"


class ProcessingService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], cfg: ProcessingConfig,
                 *, sqlite: bool = False) -> None:
        self.session_factory = session_factory
        self.cfg = cfg
        self.version = cfg.processing_version
        # SQLite serialises writers; running concurrently would only produce lock errors.
        self.concurrency = 1 if sqlite else cfg.concurrency

    # ------------------------------------------------------------------ public
    async def process_events(self, event_ids: list[str], *, trigger: str = "api",
                             force: bool = False, as_of: datetime | None = None,
                             correlation_id: str | None = None) -> dict[str, Any]:
        """Process a bounded batch. Never raises for per-event failures."""
        if len(event_ids) > self.cfg.batch_max:
            raise ValueError(f"batch of {len(event_ids)} exceeds batch_max {self.cfg.batch_max}")
        ids = await self._chronological(list(dict.fromkeys(event_ids)))
        run_id = new_processing_run_id()
        started = utc_now()
        t0 = time.perf_counter()
        async with self.session_factory() as s:
            s.add(ProcessingRunModel(
                run_id=run_id, trigger=trigger, status=ProcessingRunStatus.RUNNING.value,
                processing_version=self.version, correlation_id=correlation_id,
                started_at=started, requested=len(ids),
                config_snapshot=self.cfg.model_dump(mode="json"),
            ))
            await s.commit()

        sem = asyncio.Semaphore(self.concurrency)

        async def one(eid: str) -> dict[str, Any]:
            async with sem:
                return await self._process_one(eid, run_id=run_id, force=force,
                                               now=as_of or utc_now())

        # Ordered execution keeps history-dependent rules reproducible on SQLite (concurrency 1).
        if self.concurrency == 1:
            results = [await one(e) for e in ids]
        else:
            results = list(await asyncio.gather(*(one(e) for e in ids)))

        source_findings: list[str] = []
        try:
            source_findings = await self._scan_sources(run_id, now=as_of or utc_now())
        except Exception as exc:  # noqa: BLE001 - recorded on the run
            logger.exception("source health scan failed", extra={"run_id": run_id})
            results.append({"event_id": None, "status": EventProcessingStatus.FAILED.value,
                            "error": f"source scan: {type(exc).__name__}"})

        counts = {s.value: 0 for s in EventProcessingStatus}
        stage = {"validated": 0, "valid_with_warnings": 0, "exact_duplicates": 0,
                 "possible_duplicates": 0, "anomaly_findings": 0, "matched": 0,
                 "ambiguous": 0, "needs_review": 0, "seeded": 0, "late": 0,
                 "source_anomalies": len(source_findings)}
        errors: list[dict[str, Any]] = []
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            for k in stage:
                stage[k] += int(r.get("stage", {}).get(k, 0))
            if r.get("error"):
                errors.append({"event_id": r.get("event_id"), "error": r["error"]})

        failed = counts[EventProcessingStatus.FAILED.value] + counts[EventProcessingStatus.NOT_FOUND.value]
        warned = (counts[EventProcessingStatus.QUARANTINED.value]
                  + counts[EventProcessingStatus.REJECTED.value] + stage["valid_with_warnings"])
        ok = len(results) - failed
        if results and ok == 0:
            status = ProcessingRunStatus.FAILED
        elif failed:
            status = ProcessingRunStatus.PARTIALLY_FAILED
        elif warned:
            status = ProcessingRunStatus.COMPLETED_WITH_WARNINGS
        else:
            status = ProcessingRunStatus.COMPLETED
        duration = (time.perf_counter() - t0) * 1000
        async with self.session_factory() as s:
            run = await s.get(ProcessingRunModel, run_id)
            assert run is not None
            run.status = status.value
            run.finished_at = utc_now()
            run.duration_ms = duration
            run.counts = counts
            run.stage_counts = {**stage, "events_per_second":
                                round(len(ids) / (duration / 1000), 2) if duration else None}
            run.errors = errors
            await s.commit()
        logger.info("processing run complete", extra={"run_id": run_id, "status": status.value,
                                                       "duration_ms": round(duration, 1), **counts})
        touched = sorted({r["incident_id"] for r in results if r.get("incident_id")})
        return {"run_id": run_id, "status": status.value, "processing_version": self.version,
                "requested": len(ids), "counts": counts, "stage_counts": stage,
                "duration_ms": round(duration, 2), "errors": errors,
                "incident_ids": touched, "results": results}

    async def _chronological(self, ids: list[str]) -> list[str]:
        """Deterministic order: (event_time, event_id). History-dependent rules (rate of change,
        baselines, anomaly lifecycle) must see events in observation order, not request order.
        Unknown ids are kept (reported NOT_FOUND) at the end."""
        if not ids:
            return []
        async with self.session_factory() as s:
            known = (await s.execute(select(EventModel.event_id, EventModel.event_time).where(
                EventModel.event_id.in_(ids)))).all()
        ordered = [e for e, _ in sorted(known, key=lambda r: (ensure_aware(r[1]), r[0]))]
        return ordered + sorted(set(ids) - set(ordered))

    async def unprocessed_event_ids(self, limit: int) -> list[str]:
        async with self.session_factory() as s:
            done = select(EventProcessingModel.event_id).where(
                EventProcessingModel.processing_version == self.version)
            rows = await s.execute(
                select(EventModel.event_id).where(EventModel.event_id.not_in(done))
                .order_by(EventModel.event_time.desc()).limit(limit))
            return [r[0] for r in rows]

    # ------------------------------------------------------------------ one event
    async def _process_one(self, event_id: str, *, run_id: str, force: bool,
                           now: datetime) -> dict[str, Any]:
        async with self.session_factory() as s:
            try:
                return await self._process_in_session(s, event_id, run_id=run_id, force=force,
                                                      now=now)
            except Exception as exc:  # noqa: BLE001 - isolate the event, record the failure
                await s.rollback()
                logger.exception("event processing failed",
                                 extra={"event_id": event_id, "run_id": run_id})
                await self._record_failure(event_id, run_id, f"{type(exc).__name__}: {exc}")
                return {"event_id": event_id, "status": EventProcessingStatus.FAILED.value,
                        "error": f"{type(exc).__name__}"}

    async def _record_failure(self, event_id: str, run_id: str, message: str) -> None:
        async with self.session_factory() as s:
            row = (await s.execute(select(EventProcessingModel).where(
                EventProcessingModel.event_id == event_id,
                EventProcessingModel.processing_version == self.version))).scalar_one_or_none()
            if row is not None:
                row.status = EventProcessingStatus.FAILED.value
                row.error = message[:2000]
                row.run_id = run_id
                await s.commit()

    async def _claim(self, s: AsyncSession, event_id: str, run_id: str, force: bool
                     ) -> tuple[EventProcessingModel | None, bool]:
        """Atomically claim (event, version). Returns (row, reused)."""
        row = EventProcessingModel(event_id=event_id, processing_version=self.version,
                                   run_id=run_id, status="RUNNING", processed_at=utc_now())
        try:
            async with s.begin_nested():
                s.add(row)
            await s.commit()
            return row, False
        except IntegrityError:
            await s.rollback()
        existing = (await s.execute(select(EventProcessingModel).where(
            EventProcessingModel.event_id == event_id,
            EventProcessingModel.processing_version == self.version))).scalar_one()
        if not force and existing.status != EventProcessingStatus.FAILED.value:
            return existing, True
        existing.attempts += 1
        existing.run_id = run_id
        existing.status = "RUNNING"
        existing.error = None
        await s.commit()
        return existing, False

    async def _process_in_session(self, s: AsyncSession, event_id: str, *, run_id: str,
                                  force: bool, now: datetime) -> dict[str, Any]:
        model = (await s.execute(select(EventModel).where(EventModel.event_id == event_id))
                 ).scalar_one_or_none()
        if model is None:
            return {"event_id": event_id, "status": EventProcessingStatus.NOT_FOUND.value,
                    "error": "unknown event_id"}
        event = EventService.to_canonical(model)
        pk = model.id  # read before _claim commits (committed attributes expire)
        row, reused = await self._claim(s, event_id, run_id, force)
        assert row is not None
        if reused:
            return {"event_id": event_id, "status": EventProcessingStatus.REUSED.value,
                    "incident_id": row.selected_incident_id,
                    "candidate_outcome": row.candidate_outcome}

        neighbours = await self._dedup_neighbours(s, event, pk)
        ctx = await self._anomaly_context(s, event)
        out = evaluate_event(event, self.cfg, now=now, neighbours=neighbours, anomaly_ctx=ctx)

        v = out.validation
        row.validation_verdict = v.verdict.value
        row.validation_issues = [i.model_dump(mode="json") for i in v.issues]
        row.quality_score = v.quality_score
        row.is_late = v.is_late
        trace: dict[str, Any] = {"now": now.isoformat(), "eligibility": out.eligibility_reason}
        stage = {"validated": 1, "late": int(v.is_late),
                 "valid_with_warnings": int(v.verdict == ValidationVerdict.VALID_WITH_WARNINGS)}

        if not v.processable:
            row.status = (EventProcessingStatus.REJECTED if v.verdict == ValidationVerdict.REJECTED
                          else EventProcessingStatus.QUARANTINED).value
            row.trace = trace
            status = row.status
            await s.commit()
            return {"event_id": event_id, "status": status, "stage": stage,
                    "validation": v.verdict.value}

        d = out.dedup
        assert d is not None
        row.dedup_decision = d.decision.value
        row.dedup_method = d.method
        row.duplicate_of = d.duplicate_of
        row.processing_fingerprint = d.fingerprint
        row.counts_as_corroboration = d.counts_as_corroboration
        stage["exact_duplicates"] = int(d.decision == DedupDecision.EXACT_DUPLICATE)
        stage["possible_duplicates"] = int(d.decision == DedupDecision.POSSIBLE_DUPLICATE)
        trace["dedup"] = d.explanation

        anomaly_ids = await AnomalyService(s).apply(
            out.findings, event_id=event_id, event_time=event.event_time, run_id=run_id,
            processing_version=self.version, evaluated=out.evaluated)
        row.anomaly_ids = anomaly_ids
        stage["anomaly_findings"] = len(out.findings)

        incident_id = None
        if out.eligible:
            cands = CandidateService(s, self.cfg.candidates)
            candidates = await cands.retrieve(event)
            decision = match_event(event, candidates, self.cfg, quality=v.quality_score)
            incident_id, _ = await cands.persist(
                event, decision, eligible_to_seed=True,
                corroborating=d.counts_as_corroboration, severity=out.peak_severity,
                run_id=run_id, processing_version=self.version)
            row.candidate_outcome = decision.outcome.value
            row.selected_incident_id = incident_id
            trace["candidates"] = {"explanation": decision.explanation,
                                   "next_step": decision.recommended_next_step,
                                   "considered": len(decision.candidates)}
            key = {"MATCH_CANDIDATE": "matched", "AMBIGUOUS": "ambiguous",
                   "NEEDS_REVIEW": "needs_review"}.get(decision.outcome.value)
            if key:
                stage[key] = 1
            elif incident_id:
                stage["seeded"] = 1
        row.status = EventProcessingStatus.PROCESSED.value
        row.trace = trace
        row.processed_at = utc_now()
        outcome = row.candidate_outcome
        await s.commit()
        return {"event_id": event_id, "status": EventProcessingStatus.PROCESSED.value,
                "stage": stage, "validation": v.verdict.value, "dedup": d.decision.value,
                "anomaly_ids": anomaly_ids, "candidate_outcome": outcome,
                "incident_id": incident_id}

    # ------------------------------------------------------------------ context loading
    async def _dedup_neighbours(self, s: AsyncSession, event: CanonicalEvent, pk: int
                                ) -> list[CanonicalEvent]:
        """Earlier-persisted events of the same type in a small window (bounded, indexed)."""
        w = timedelta(seconds=max(self.cfg.dedup.near_window_seconds,
                                  max(self.cfg.dedup.time_precision_seconds.values())))
        rows = (await s.execute(
            select(EventModel).where(
                EventModel.event_type == event.event_type.value,
                EventModel.event_time.between(event.event_time - w, event.event_time + w),
                EventModel.id < pk,
            ).order_by(EventModel.id).limit(_NEIGHBOUR_LIMIT)
        )).scalars().all()
        return [EventService.to_canonical(r) for r in rows]

    async def _anomaly_context(self, s: AsyncSession, event: CanonicalEvent) -> AnomalyContext:
        names = {m.name for m in event.measurements}
        if not names:
            return AnomalyContext()
        window_h = max([b.window_hours for b in self.cfg.baselines] + [6])
        lo = event.event_time - timedelta(hours=window_h)
        category = event.source_id.split(".", 1)[0]
        subject = subject_of(event)
        stmt = select(EventModel).where(
            EventModel.event_type == event.event_type.value,
            EventModel.event_time >= lo, EventModel.event_time < event.event_time,
            EventModel.source_id.like(f"{category}.%"),
        )
        if event.location and event.location.place_id:
            stmt = stmt.where(EventModel.place_id == event.location.place_id)
        rows = (await s.execute(stmt.order_by(EventModel.event_time.desc())
                                .limit(_HISTORY_LIMIT))).scalars().all()
        prior = [EventService.to_canonical(r) for r in reversed(rows)]
        prior = [p for p in prior if subject_of(p) == subject]
        flagged = set()
        if prior:
            flagged = {r[0] for r in await s.execute(
                select(AnomalyObservationModel.event_id).where(
                    AnomalyObservationModel.event_id.in_([p.event_id for p in prior]),
                    AnomalyObservationModel.action.in_(["created", "updated", "reopened"])))}
        ctx = AnomalyContext()
        for p in prior:
            for m in p.measurements:
                if m.name in names:
                    ctx.history.setdefault(m.name, []).append(Reading(
                        event_id=p.event_id, event_time=p.event_time, value=m.value,
                        unit=m.unit, period_seconds=m.period_seconds,
                        was_anomalous=p.event_id in flagged))
        loc = event.location
        conflict = [n for n in self.cfg.sensor_health.conflict_measurements if n in names]
        if conflict and loc is not None and loc.has_coordinates:
            sh = self.cfg.sensor_health
            dw = timedelta(seconds=sh.conflict_window_seconds)
            dlat = sh.conflict_radius_m / 111_000.0
            nrows = (await s.execute(select(EventModel).where(
                EventModel.event_type == event.event_type.value,
                EventModel.event_time.between(event.event_time - dw, event.event_time + dw),
                EventModel.latitude.between(loc.latitude - dlat, loc.latitude + dlat),
                EventModel.event_id != event.event_id,
            ).order_by(EventModel.id).limit(_NEIGHBOUR_LIMIT))).scalars().all()
            for r in nrows:
                n = EventService.to_canonical(r)
                if subject_of(n) == subject or not (n.location and n.location.has_coordinates):
                    continue
                for m in n.measurements:
                    if m.name in conflict:
                        ctx.neighbours.setdefault(m.name, []).append(Reading(
                            event_id=n.event_id, event_time=n.event_time, value=m.value,
                            unit=m.unit, latitude=n.location.latitude,
                            longitude=n.location.longitude, subject=subject_of(n)))
        return ctx

    # ------------------------------------------------------------------ source-level
    async def _scan_sources(self, run_id: str, *, now: datetime) -> list[str]:
        """Stale-source and repeated-malformed checks. Observability, never incidents."""
        from app.core.config import get_settings

        settings = get_settings()
        sh = self.cfg.sensor_health
        touched: list[str] = []
        async with self.session_factory() as s:
            sources = (await s.execute(select(SourceHealthModel))).scalars().all()
            svc = AnomalyService(s)
            marker = f"run:{run_id}"
            since = now - timedelta(seconds=sh.malformed_window_seconds)
            quarantined = dict((await s.execute(
                select(QuarantineModel.source_id, func.count()).where(
                    QuarantineModel.created_at >= since).group_by(QuarantineModel.source_id)
            )).all())
            for src in sources:
                if src.mode == "disabled":
                    continue
                latest = ensure_aware(src.latest_event_time) if src.latest_event_time else None
                findings = [f for f in (
                    detect_stale_source(src.source_id, latest, now, settings.freshness_for(src.source_id)),
                    detect_repeated_malformed(src.source_id, int(quarantined.get(src.source_id, 0)),
                                              sh.malformed_window_seconds, sh.malformed_min_count),
                ) if f is not None]
                evaluated = [("sensor.stale_source", src.source_id, f"source:{src.source_id}", None)] \
                    if latest is not None else []
                touched += await svc.apply(findings, event_id=marker, event_time=now,
                                           run_id=run_id, processing_version=self.version,
                                           evaluated=evaluated)
            await s.commit()
        return touched



def get_processing_service() -> ProcessingService:
    """Build the service from current settings (no caching: tests swap engines per test)."""
    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.processing.config import get_processing_config

    settings = get_settings()
    return ProcessingService(get_session_factory(), get_processing_config(),
                             sqlite=settings.async_database_url.startswith("sqlite"))
