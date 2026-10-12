"""Ingestion-run orchestration.

Responsibilities
----------------
* Run one adapter and turn its result into a persisted, auditable run record.
* **Isolate failures.** A source that raises must not prevent other sources from ingesting. The
  runner catches per-source errors, records them on that source's run, and carries on.
* Prevent overlapping runs of the same source.
* Optionally poll on a timer (``SCHEDULER_ENABLED``, off by default).

One run lifecycle
-----------------
``pending → running → succeeded | partial | failed | skipped``

``partial`` means some records were accepted but others were rejected or quarantined, or that
warnings were raised. A run is only ``succeeded`` when it is clean.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ConflictError
from app.core.logging import get_logger, request_context
from app.core.timeutil import utc_now
from app.db.models import IngestionRunModel
from app.db.repositories.ingestion_run_repository import IngestionRunRepository
from app.ingestion.base import FetchRequest, SourceAdapter
from app.ingestion.http import error_to_run_error
from app.schemas.common import RunStatus, SourceStatus, ValidationOutcome
from app.schemas.event import CanonicalEvent
from app.schemas.ingestion import IngestionRun, IngestRequest, RecordOutcome, RunError
from app.schemas.source import SourceDescriptor
from app.services.event_service import EventService
from app.services.source_health import SourceHealthService

__all__ = ["IngestionRunner", "new_run_id"]

logger = get_logger(__name__)


def new_run_id() -> str:
    """Generate a sortable run id."""
    stamp = utc_now().strftime("%Y%m%dT%H%M%S")
    return f"run_{stamp}_{uuid.uuid4().hex[:8]}"


class IngestionRunner:
    """Executes ingestion runs against one database session factory."""

    def __init__(
        self,
        session_factory,
        *,
        settings: Settings | None = None,
        registry=None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.registry = registry
        self._active_sources: set[str] = set()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------- helpers
    def _resolve(self, source_id: str) -> SourceAdapter:
        assert self.registry is not None, "runner requires a source registry"
        return self.registry.get(source_id)

    async def _try_acquire(self, source_id: str, force: bool) -> bool:
        """Reserve a source for a run, refusing re-entry unless forced.

        The in-process set guards against overlapping runs within one worker. The database check
        guards against a second worker.
        """
        async with self._lock:
            if not force and source_id in self._active_sources:
                return False
            self._active_sources.add(source_id)
        return True

    def _release(self, source_id: str) -> None:
        self._active_sources.discard(source_id)

    # ----------------------------------------------------------------- run
    async def run_source(
        self,
        source_id: str,
        *,
        request: IngestRequest | None = None,
        trigger: str = "api",
        adapter: SourceAdapter | None = None,
    ) -> IngestionRun:
        """Execute one ingestion run for one source.

        Never raises for a source-level failure: the failure is recorded on the returned run so
        that one broken connector cannot abort a multi-source ingestion.
        """
        request = request or IngestRequest()
        run_id = new_run_id()
        started = utc_now()

        try:
            adapter = adapter or self._resolve(source_id)
        except AppError as exc:
            # Unknown source: not attributable to a real connector run.
            raise

        if not await self._try_acquire(source_id, request.force):
            raise ConflictError(
                f"An ingestion run for '{source_id}' is already in progress.",
                code="run_already_active",
                retryable=True,
                details={"source_id": source_id, "run_id": run_id},
            )

        try:
            async with self.session_factory() as session:
                return await self._execute(
                    session,
                    adapter=adapter,
                    run_id=run_id,
                    started=started,
                    request=request,
                    trigger=trigger,
                )
        finally:
            self._release(source_id)

    async def _execute(
        self,
        session: AsyncSession,
        *,
        adapter: SourceAdapter,
        run_id: str,
        started: datetime,
        request: IngestRequest,
        trigger: str,
    ) -> IngestionRun:
        health = SourceHealthService(session)
        runs = IngestionRunRepository(session)
        event_service = EventService(session)

        correlation_id = f"run_{uuid.uuid4().hex[:12]}"

        run_row = await runs.create(
            IngestionRunModel(
                run_id=run_id,
                source_id=adapter.source_id,
                trigger=trigger,
                status=RunStatus.RUNNING.value,
                correlation_id=correlation_id,
                started_at=started,
            )
        )
        await session.commit()

        await health.record_attempt(adapter.source_id, mode=adapter.effective_mode())

        events: list[CanonicalEvent] = []
        adapter_outcomes: list[RecordOutcome] = []
        warnings: list[str] = []
        errors: list[RunError] = []
        provider_meta: dict = {}
        pages = 0
        truncated = False
        latest_event_time: datetime | None = None
        failure: AppError | None = None
        accepted_ids: list[str] = []

        fetch_request = FetchRequest(
            source_id=adapter.source_id,
            correlation_id=correlation_id,
            dry_run=request.dry_run,
            fixture=request.fixture,
            shuffle=request.shuffle,
            shuffle_seed=request.shuffle_seed,
            rebase=request.rebase,
        )

        # --- fetch + persist, isolated per source -----------------------------
        with request_context(correlation_id, source_id=adapter.source_id):
            try:
                result = await adapter.fetch_events(fetch_request)
                events = result.events
                adapter_outcomes = result.outcomes
                warnings.extend(result.warnings)
                errors.extend(result.errors)
                provider_meta = dict(result.provider_meta)
                pages = result.pages_fetched
                truncated = result.truncated
                latest_event_time = _max_event_time(events)

                summary = await event_service.persist_batch(
                    events, run_id=run_id, dry_run=request.dry_run
                )
                accepted = summary.accepted
                accepted_ids = list(summary.accepted_event_ids)
                duplicate = summary.duplicate
                quarantined = summary.quarantined
                # Adapter-reported per-record rejections are merged with persistence outcomes.
                rejected = summary.rejected + sum(
                    1
                    for o in adapter_outcomes
                    if o.outcome in (ValidationOutcome.REJECTED, ValidationOutcome.QUARANTINED)
                )
                fetched = len(events)

            except AppError as exc:
                # Source-level failure: recorded, isolated, never re-raised to the caller.
                failure = exc
                error = error_to_run_error(exc)
                errors.append(error)
                accepted = duplicate = rejected = quarantined = 0
                fetched = 0
                logger.warning(
                    "ingestion source failed",
                    extra={
                        "source_id": adapter.source_id,
                        "run_id": run_id,
                        "error_category": exc.code,
                        "retryable": exc.retryable,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - never let one source break the caller
                failure = None
                error = error_to_run_error(exc)
                errors.append(error)
                accepted = duplicate = rejected = quarantined = 0
                fetched = 0
                logger.exception(
                    "unexpected ingestion error",
                    extra={"source_id": adapter.source_id, "run_id": run_id},
                )

            # --- finalise the run -------------------------------------------
            finished = utc_now()
            duration_ms = (finished - started).total_seconds() * 1000.0

            if failure is not None:
                status = RunStatus.FAILED
            elif rejected or quarantined or errors or truncated:
                status = RunStatus.PARTIAL
            else:
                status = RunStatus.SUCCEEDED

            counts = {
                "fetched": fetched,
                "accepted": accepted,
                "duplicate": duplicate,
                "rejected": rejected,
                "quarantined": quarantined,
            }

            run_row.status = status.value
            run_row.finished_at = finished
            run_row.duration_ms = duration_ms
            run_row.records_fetched = fetched
            run_row.records_accepted = accepted
            run_row.records_duplicate = duplicate
            run_row.records_rejected = rejected
            run_row.records_quarantined = quarantined
            run_row.latest_event_time = latest_event_time
            run_row.error_category = errors[0].category if errors else None
            run_row.errors = [e.model_dump(mode="json") for e in errors]
            run_row.warnings = warnings
            run_row.outcome_counts = counts
            run_row.notes = {
                "pages_fetched": pages,
                "truncated": truncated,
                "dry_run": request.dry_run,
                "provider_meta": provider_meta,
            }
            await session.commit()

            # --- update source health ---------------------------------------
            health_service = SourceHealthService(session)
            if failure is not None or (errors and accepted == 0):
                await health_service.record_failure(
                    adapter.source_id,
                    error=errors[0] if errors else RunError(
                        category="unknown", message="Ingestion failed."
                    ),
                    run_id=run_id,
                    counts=counts,
                    mode=adapter.effective_mode(),
                )
            else:
                await health_service.record_success(
                    adapter.source_id,
                    counts=counts,
                    latest_event_time=latest_event_time,
                    run_id=run_id,
                    warnings=warnings,
                    mode=adapter.effective_mode(),
                )
            await session.commit()

            # --- hand off to deterministic processing --------------------------
            if accepted_ids and not request.dry_run and self.settings.processing_auto_on_ingest:
                run_row.notes = {**run_row.notes,
                                 "processing": await self._process_accepted(accepted_ids, run_id)}
                await session.commit()

            logger.info(
                "ingestion run complete",
                extra={
                    "run_id": run_id,
                    "source_id": adapter.source_id,
                    "status": status.value,
                    "duration_ms": round(duration_ms, 2),
                    **counts,
                },
            )

            return IngestionRun(
                run_id=run_id,
                source_id=adapter.source_id,
                trigger=trigger,
                status=status,
                correlation_id=correlation_id,
                started_at=started,
                finished_at=finished,
                duration_ms=duration_ms,
                records_fetched=fetched,
                records_accepted=accepted,
                records_rejected=rejected,
                records_quarantined=quarantined,
                records_duplicate=duplicate,
                latest_event_time=latest_event_time,
                error_category=run_row.error_category,
                errors=errors,
                warnings=warnings,
                outcome_counts=counts,
                notes=run_row.notes,
            )

    async def _process_accepted(self, event_ids: list[str], run_id: str) -> dict:
        """Process newly persisted events. Isolated: never fails the ingestion run."""
        from app.services.processing_service import get_processing_service

        try:
            service = get_processing_service()
            summaries = []
            for start in range(0, len(event_ids), service.cfg.batch_max):
                summaries.append(await service.process_events(
                    event_ids[start:start + service.cfg.batch_max], trigger=f"ingest:{run_id}"))
            incidents = sorted({i for s in summaries for i in s["incident_ids"]})
            if incidents and self.settings.intelligence_auto_trigger:
                await _auto_trigger_intelligence(incidents, service.version)
            return {"run_ids": [s["run_id"] for s in summaries],
                    "status": [s["status"] for s in summaries], "incident_ids": incidents}
        except Exception as exc:  # noqa: BLE001 - processing must not break ingestion
            logger.exception("post-ingestion processing failed", extra={"run_id": run_id})
            return {"status": "FAILED", "error": type(exc).__name__}

    # ---------------------------------------------------------- multi-source
    async def run_many(
        self, source_ids: list[str], *, trigger: str = "schedule"
    ) -> list[IngestionRun]:
        """Run several sources, isolating each one's failure from the others."""
        results: list[IngestionRun] = []
        for source_id in source_ids:
            try:
                results.append(await self.run_source(source_id, trigger=trigger))
            except AppError as exc:
                logger.warning(
                    "skipped ingestion source",
                    extra={"source_id": source_id, "error_code": exc.code},
                )
            except Exception:  # noqa: BLE001 - keep going for unrelated sources
                logger.exception("unhandled error in multi-source run", extra={"source_id": source_id})
        return results


async def _auto_trigger_intelligence(incident_ids: list[str], processing_version: str) -> None:
    """Queue intelligence analysis for touched incidents (opt-in: INTELLIGENCE_AUTO_TRIGGER)."""
    from app.db.session import get_session_factory
    from app.integration.intelligence_bridge import get_intelligence_service, trigger_analysis

    if get_intelligence_service() is None:
        return
    async with get_session_factory()() as session:
        for incident_id in incident_ids:
            try:
                await trigger_analysis(session, incident_id, processing_version, wait=False)
            except Exception:  # noqa: BLE001
                logger.exception("intelligence auto-trigger failed",
                                 extra={"incident_id": incident_id})


def _max_event_time(events: list[CanonicalEvent]) -> datetime | None:
    """Newest event time in a batch, used to advance the source watermark."""
    if not events:
        return None
    return max(event.event_time for event in events)
