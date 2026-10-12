"""Deterministic processing (Milestone 2): validation, deduplication, anomalies, candidates.

Layout
------
* ``config.py``      versioned, validated thresholds/weights/windows (``processing_version``)
* ``validator.py``   Stage A — validation & quality (reason-coded outcomes)
* ``quality.py``     transparent quality-score penalties
* ``deduplicate.py`` Stage B — versioned processing fingerprint, near-duplicate detection
* ``baselines.py``   robust median/MAD statistics
* ``anomaly.py``     Stage C — threshold, robust-baseline, rate-of-change, sensor-health rules
* ``correlation.py`` event families, compatibility matrix, geo helpers
* ``candidates.py``  Stages D/E — transparent candidate scoring and decisions
* ``pipeline.py``    pure stage sequencing for one event

Everything in this package is pure and deterministic; persistence and orchestration live in
``app.services.processing_service``. No LLM is used anywhere in this package.

The read side for downstream consumers remains :func:`get_processable_events`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.event_repository import EventFilter, EventRepository
from app.schemas.event import CanonicalEvent

__all__ = ["IMPLEMENTED", "get_processable_events"]

IMPLEMENTED = True


async def get_processable_events(
    session: AsyncSession,
    *,
    limit: int = 1000,
    event_filter: EventFilter | None = None,
) -> list[CanonicalEvent]:
    """Persisted events ordered by ``event_time`` ascending (chronologically consistent)."""
    from app.services.event_service import EventService

    repository = EventRepository(session)
    rows, _ = await repository.query(
        event_filter or EventFilter(), limit=limit, offset=0, order_by="event_time",
        descending=False,
    )
    return [EventService.to_canonical(row) for row in rows]
