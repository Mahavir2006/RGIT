"""Source catalogue, health, ingestion trigger, and run history endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import Depends, APIRouter, Header, Query

from app.api.deps import DbSession, RequestId
from app.api.envelope import paginated, success
from app.core.errors import NotFoundError
from app.core.security import require_write_key
from app.db.repositories.ingestion_run_repository import IngestionRunRepository
from app.ingestion.base import SourceAdapter
from app.ingestion.providers import registry
from app.schemas.common import Envelope, RunStatus, SourceMode, SourceStatus
from app.schemas.ingestion import (
    IngestionRun,
    IngestionRunSummary,
    IngestRequest,
)
from app.schemas.source import SourceHealthResponse, SourceListItem
from app.services.ingestion_runner import IngestionRunner
from app.services.source_health import SourceHealthService

__all__ = ["router"]

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=Envelope, summary="List configured sources and their modes")
async def list_sources(request_id: RequestId) -> Envelope:
    """Return every registered connector with its mode, requirements, and known gaps.

    Credential values are never included — only whether a variable is configured.
    """
    items = []
    for adapter in registry.all():
        descriptor = adapter.describe()
        items.append(
            SourceListItem(
                **descriptor.model_dump(),
                status=SourceStatus.UNKNOWN.value,
            )
        )
    return success({"sources": items, "total": len(items)}, request_id)


@router.get("/health", response_model=Envelope, summary="Source health and freshness")
async def source_health(session: DbSession, request_id: RequestId) -> Envelope:
    """Return per-source health.

    A missing or stale feed is an observability gap, not evidence that a location is safe. This
    endpoint therefore reports freshness explicitly and never infers safety.
    """
    service = SourceHealthService(session)
    states = await service.list_states(registry.all())

    def count(status_value: str) -> int:
        return sum(1 for s in states if s.status == status_value)

    response = SourceHealthResponse(
        total=len(states),
        healthy=count(SourceStatus.HEALTHY.value),
        degraded=count(SourceStatus.DEGRADED.value),
        stale=count(SourceStatus.STALE.value),
        offline=count(SourceStatus.OFFLINE.value),
        misconfigured=count(SourceStatus.MISCONFIGURED.value),
        disabled=count(SourceStatus.DISABLED.value),
        unknown=count(SourceStatus.UNKNOWN.value),
        all_fresh=all(s.is_fresh for s in states if s.latest_event_time is not None),
        sources=states,
    )
    return success(response.model_dump(mode="json"), request_id)


@router.post(
    "/{source_id}/ingest",
    response_model=Envelope,
    summary="Trigger an ingestion run for one source",
    dependencies=[Depends(require_write_key)],
)
async def trigger_ingestion(
    source_id: str,
    session: DbSession,
    request_id: RequestId,
    payload: IngestRequest | None = None,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Envelope:
    """Run one source adapter and persist what it returns.

    Requires the write API key. A source-level failure is reported inside a ``failed`` run rather
    than as a 5xx, so that one broken connector does not abort a wider ingestion.
    """
    require_write_key(x_api_key)

    adapter: SourceAdapter = registry.resolve(source_id)  # raises NotFoundError for unknown ids

    from app.db.session import get_session_factory

    runner = IngestionRunner(get_session_factory(), registry=registry)
    run = await runner.run_source(adapter.source_id, request=payload or IngestRequest())
    return success(run.model_dump(mode="json"), request_id)


@router.get(
    "/{source_id}",
    response_model=Envelope,
    summary="Describe one source",
)
async def get_source(source_id: str, request_id: RequestId) -> Envelope:
    adapter = registry.resolve(source_id)
    return success(adapter.describe().model_dump(mode="json"), request_id)


@router.get("/{source_id}/runs", response_model=Envelope, summary="Recent runs for one source")
async def source_runs(
    source_id: str,
    session: DbSession,
    request_id: RequestId,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> Envelope:
    registry.get(source_id)  # validate the id
    repository = IngestionRunRepository(session)
    rows, total = await repository.list_recent(
        source_id=source_id, limit=page_size, offset=(page - 1) * page_size
    )
    items = [_to_summary(row).model_dump(mode="json") for row in rows]
    return paginated(items, total, page, page_size, request_id)


# ------------------------------------------------------------------- run list
# Registered on a separate router in main.py because the path is /ingestion/runs, not /sources.
ingestion_router = APIRouter(prefix="/ingestion", tags=["ingestion"])

#: ``POST /api/v1/ingest/{source}`` — the canonical ingestion trigger named in the API contract.
ingest_router = APIRouter(prefix="/ingest", tags=["ingestion"])


@ingest_router.post(
    "/{source_id}",
    response_model=Envelope,
    summary="Trigger an ingestion run for one source",
    dependencies=[Depends(require_write_key)],
)
async def trigger_ingest(
    source_id: str,
    request_id: RequestId,
    payload: IngestRequest | None = None,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Envelope:
    """Run one source adapter and persist what it returns.

    Requires the write API key. A source-level failure is reported inside a ``failed`` run rather
    than as a 5xx, so that one broken connector does not abort a wider ingestion.

    Replay-specific options (``fixture``, ``shuffle``, ``shuffle_seed``, ``rebase``) apply to the
    ``replay.all`` source and are ignored by live adapters.
    """
    require_write_key(x_api_key)

    # Accepts a full id (``weather.live``) or an unambiguous alias (``weather``, ``replay``).
    adapter = registry.resolve(source_id)  # raises NotFoundError for an unknown source

    from app.db.session import get_session_factory

    runner = IngestionRunner(get_session_factory(), registry=registry)
    run = await runner.run_source(adapter.source_id, request=payload or IngestRequest())
    return success(run.model_dump(mode="json"), request_id)


@ingestion_router.get(
    "/runs", response_model=Envelope, summary="Recent ingestion runs across all sources"
)
async def list_runs(
    session: DbSession,
    request_id: RequestId,
    source_id: str | None = Query(default=None),
    status_filter: RunStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> Envelope:
    """Return recent ingestion runs with their accepted/rejected/duplicate counts."""
    repository = IngestionRunRepository(session)
    rows, total = await repository.list_recent(
        source_id=source_id, limit=page_size, offset=(page - 1) * page_size
    )
    if status_filter is not None:
        rows = [r for r in rows if r.status == status_filter.value]
        total = len(rows)
    items = [_to_summary(row).model_dump(mode="json") for row in rows]
    return paginated(items, total, page, page_size, request_id)


def _to_summary(row: Any) -> IngestionRunSummary:
    return IngestionRunSummary(
        run_id=row.run_id,
        source_id=row.source_id,
        trigger=row.trigger,
        status=RunStatus(row.status),
        started_at=row.started_at,
        finished_at=row.finished_at,
        duration_ms=row.duration_ms,
        records_fetched=row.records_fetched,
        records_accepted=row.records_accepted,
        records_rejected=row.records_rejected,
        records_quarantined=row.records_quarantined,
        records_duplicate=row.records_duplicate,
        error_category=row.error_category,
    )
