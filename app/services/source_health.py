"""Source-health tracking.

The central rule: **a source is not healthy because the API process is up.** Health reflects the
last real attempt to obtain data, and staleness is measured against that source's own freshness
expectation, not a global cadence.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.timeutil import ensure_aware, utc_now
from app.db.models import SourceHealthModel
from app.db.repositories.source_repository import SourceHealthRepository
from app.schemas.common import SourceStatus
from app.schemas.ingestion import RunError
from app.schemas.source import SourceHealthState

__all__ = ["SourceHealthService", "derive_status"]

logger = get_logger(__name__)


#: Ingestion summary keys -> ``SourceHealthModel`` column names. The counters are *cumulative*
#: totals per source, not per-run values, so a key/column mismatch would silently drop them.
_COUNT_COLUMNS = {
    "fetched": "records_fetched",
    "accepted": "records_accepted",
    "duplicate": "records_duplicate",
    "rejected": "records_rejected",
    "quarantined": "records_quarantined",
}


def _count_updates(counts: dict[str, int] | None) -> dict[str, int]:
    """Translate ingestion summary keys into health-table column names."""
    if not counts:
        return {}
    return {
        column: int(counts[key])
        for key, column in _COUNT_COLUMNS.items()
        if key in counts and isinstance(counts[key], int)
    }


def _age_seconds(value: datetime | None, *, now: datetime | None = None) -> float | None:
    """Seconds elapsed since ``value``, or None when absent.

    PostgreSQL TIMESTAMPTZ round-trips the offset; SQLite has no timezone type and returns naive
    values. Timestamps are always written as UTC, so a naive value is re-tagged here rather than
    producing an offset-naive/aware subtraction error.
    """
    if value is None:
        return None
    reference = now or utc_now()
    return max(0.0, (reference - ensure_aware(value)).total_seconds())

#: Failure counts at which a source is considered degraded rather than merely having failed once.
DEGRADED_AFTER_FAILURES = 1
OFFLINE_AFTER_FAILURES = 3


def derive_status(
    *,
    enabled: bool,
    runnable: bool,
    consecutive_failures: int,
    error_category: str | None,
    since_last_success_seconds: float | None,
    latest_event_time: datetime | None,
    freshness_sla_seconds: int,
    now: datetime | None = None,
) -> SourceStatus:
    """Compute a source's health state.

    Precedence matters and follows the principle that missing data is not good news:

    1. Disabled / misconfigured wins over everything.
    2. Repeated failures escalate to offline.
    3. Staleness wins over the absence of failures: a source that has not reported within its own
       freshness window is stale even if its last run "succeeded".
    4. Only then is a source healthy.
    """
    current = now or utc_now()

    if not enabled:
        return SourceStatus.DISABLED
    if not runnable:
        return SourceStatus.MISCONFIGURED
    if error_category in ("credential_missing", "upstream_auth_error"):
        return SourceStatus.MISCONFIGURED
    if consecutive_failures >= OFFLINE_AFTER_FAILURES:
        return SourceStatus.OFFLINE
    if consecutive_failures >= DEGRADED_AFTER_FAILURES:
        return SourceStatus.DEGRADED

    if since_last_success_seconds is not None and since_last_success_seconds > freshness_sla_seconds:
        return SourceStatus.STALE

    # A source that has never produced data is unknown, not healthy.
    if latest_event_time is None and since_last_success_seconds is None:
        return SourceStatus.UNKNOWN

    return SourceStatus.HEALTHY


class SourceHealthService:
    """Reads and updates per-source health state."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SourceHealthRepository(session)

    async def ensure_rows(self, adapters: list) -> list[SourceHealthModel]:
        """Make sure a row exists for every registered adapter, preserving prior state."""
        settings = get_settings()
        rows: list[SourceHealthModel] = []
        for adapter in adapters:
            existing = await self.repo.get(adapter.source_id)
            if existing is None:
                rows.append(
                    await self.repo.upsert(
                        adapter.source_id,
                        {
                            "display_name": adapter.display_name,
                            "category": adapter.category.value,
                            "provider": adapter.provider,
                            "mode": adapter.effective_mode(),
                            "enabled": True,
                            "status": (
                                SourceStatus.UNKNOWN.value
                                if adapter.can_run_live() or adapter.supports_replay
                                else SourceStatus.MISCONFIGURED.value
                            ),
                            "freshness_sla_seconds": settings.freshness_for(adapter.source_id),
                            "missing_settings": adapter.missing_settings(),
                        },
                    )
                )
            else:
                rows.append(existing)
        return rows

    async def record_attempt(self, source_id: str, **fields: object) -> None:
        """Mark that an ingestion attempt has begun."""
        await self.repo.upsert(source_id, {"last_attempt_at": utc_now(), **fields})

    async def record_success(
        self,
        source_id: str,
        *,
        counts: dict[str, int],
        latest_event_time: datetime | None,
        run_id: str,
        warnings: list[str] | None = None,
        mode: str | None = None,
    ) -> SourceHealthModel:
        """Record a successful ingestion run and advance the watermark."""
        now = utc_now()
        updates: dict[str, object] = {
            "last_success_at": now,
            "consecutive_failures": 0,
            "error_category": None,
            "error_summary": None,
            "warnings": warnings or [],
            "last_run_id": run_id,
        }
        if latest_event_time is not None:
            updates["latest_event_time"] = latest_event_time
            updates["last_event_time_at"] = now
        if mode:
            updates["mode"] = mode

        model = await self.repo.upsert(source_id, updates)
        # Counters are lifetime totals per source, so a run adds to them rather than replacing.
        await self.repo.increment_counters(source_id, _count_updates(counts))
        model = await self.repo.get(source_id) or model
        model.status = derive_status(
            enabled=model.enabled,
            runnable=True,
            consecutive_failures=model.consecutive_failures,
            error_category=model.error_category,
            since_last_success_seconds=_age_seconds(model.last_success_at, now=now),
            latest_event_time=model.latest_event_time,
            freshness_sla_seconds=model.freshness_sla_seconds,
            now=now,
        ).value
        return model

    async def record_failure(
        self,
        source_id: str,
        *,
        error: RunError,
        run_id: str,
        counts: dict[str, int] | None = None,
        mode: str | None = None,
    ) -> SourceHealthModel:
        """Record an ingestion failure without touching the last-success watermark.

        The previous ``latest_event_time`` is deliberately preserved: a failed run says nothing
        about how old the data we already hold is.
        """
        now = utc_now()
        updates: dict[str, object] = {
            "consecutive_failures": (await self._current_failures(source_id)) + 1,
            "error_category": error.category,
            # Already redacted upstream; never store a raw provider body.
            "error_summary": error.message[:500],
            "last_run_id": run_id,
            "warnings": [],
        }
        if mode:
            updates["mode"] = mode

        model = await self.repo.upsert(source_id, updates)
        # Counters are lifetime totals; a failed run still adds whatever it did manage to fetch.
        await self.repo.increment_counters(source_id, _count_updates(counts))
        model = await self.repo.get(source_id) or model
        model.status = derive_status(
            enabled=model.enabled,
            runnable=True,
            consecutive_failures=model.consecutive_failures,
            error_category=model.error_category,
            since_last_success_seconds=_age_seconds(model.last_success_at, now=now),
            latest_event_time=model.latest_event_time,
            freshness_sla_seconds=model.freshness_sla_seconds,
            now=now,
        ).value
        return model

    async def _current_failures(self, source_id: str) -> int:
        model = await self.repo.get(source_id)
        return model.consecutive_failures if model else 0

    # ------------------------------------------------------------- reporting
    async def list_states(self, adapters: list) -> list[SourceHealthState]:
        """Build the health view for every registered adapter."""
        await self.ensure_rows(adapters)
        rows = {row.source_id: row for row in await self.repo.list_all()}
        now = utc_now()
        states: list[SourceHealthState] = []

        for adapter in adapters:
            row = rows.get(adapter.source_id)
            if row is None:  # pragma: no cover - ensure_rows guarantees a row
                continue

            since_success = _age_seconds(row.last_success_at, now=now)
            ingest_lag = _age_seconds(row.latest_event_time, now=now)
            # A source is fresh when its newest observation is inside its own SLA window.
            is_fresh = ingest_lag is not None and ingest_lag <= row.freshness_sla_seconds

            states.append(
                SourceHealthState(
                    source_id=row.source_id,
                    display_name=row.display_name or adapter.display_name,
                    category=row.category or adapter.category.value,
                    provider=row.provider or adapter.provider,
                    mode=row.mode or adapter.effective_mode(),
                    status=row.status or SourceStatus.UNKNOWN.value,
                    enabled=row.enabled,
                    runnable=adapter.can_run_live() or adapter.supports_replay,
                    last_attempt_at=row.last_attempt_at,
                    last_success_at=row.last_success_at,
                    latest_event_time=row.latest_event_time,
                    last_event_time_at=row.last_event_time_at,
                    ingest_lag_seconds=ingest_lag,
                    since_last_success_seconds=since_success,
                    records_fetched=row.records_fetched,
                    records_accepted=row.records_accepted,
                    records_rejected=row.records_rejected,
                    records_quarantined=row.records_quarantined,
                    records_duplicate=row.records_duplicate,
                    freshness_sla_seconds=row.freshness_sla_seconds,
                    is_fresh=is_fresh,
                    consecutive_failures=row.consecutive_failures,
                    error_category=row.error_category,
                    error_summary=row.error_summary,
                    warnings=list(row.warnings or []),
                    missing_settings=list(row.missing_settings or adapter.missing_settings()),
                    last_run_id=row.last_run_id,
                    updated_at=row.updated_at,
                )
            )
        return states
