"""Repositories: the only layer that talks to the database.

Milestone 2 (anomaly detection, candidate retrieval, evidence fusion) will consume events
through :class:`EventRepository`. Keeping persistence behind this interface means the processing
subsystem never needs to know about SQLAlchemy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EventModel

__all__ = ["EventRepository", "EventFilter"]


class EventFilter:
    """Declarative filter for event queries."""

    def __init__(
        self,
        *,
        source_id: str | None = None,
        source_ids: list[str] | None = None,
        source_category: str | None = None,
        event_type: str | None = None,
        event_types: list[str] | None = None,
        source_kind: str | None = None,
        quality_status: str | None = None,
        is_late: bool | None = None,
        event_time_from: datetime | None = None,
        event_time_to: datetime | None = None,
        ingest_time_from: datetime | None = None,
        latitude_min: float | None = None,
        latitude_max: float | None = None,
        longitude_min: float | None = None,
        longitude_max: float | None = None,
        event_id: str | None = None,
        source_event_id: str | None = None,
    ) -> None:
        self.source_id = source_id
        self.source_ids = source_ids
        self.source_category = source_category
        self.event_type = event_type
        self.event_types = event_types
        self.source_kind = source_kind
        self.quality_status = quality_status
        self.is_late = is_late
        self.event_time_from = event_time_from
        self.event_time_to = event_time_to
        self.ingest_time_from = ingest_time_from
        self.latitude_min = latitude_min
        self.latitude_max = latitude_max
        self.longitude_min = longitude_min
        self.longitude_max = longitude_max
        self.event_id = event_id
        self.source_event_id = source_event_id


class EventRepository:
    """Read/write access to canonical events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------- writes
    async def add(self, model: EventModel) -> EventModel:
        """Stage an event for insertion. Uniqueness is enforced at flush time."""
        self.session.add(model)
        return model

    async def flush(self) -> None:
        await self.session.flush()

    async def get_by_idempotency_key(self, key: str) -> EventModel | None:
        result = await self.session.execute(
            select(EventModel).where(EventModel.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def get_by_source_event_id(
        self, source_id: str, source_event_id: str
    ) -> EventModel | None:
        result = await self.session.execute(
            select(EventModel).where(
                EventModel.source_id == source_id,
                EventModel.source_event_id == source_event_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_fingerprint(self, fingerprint: str) -> EventModel | None:
        result = await self.session.execute(
            select(EventModel).where(EventModel.fingerprint == fingerprint)
        )
        return result.scalar_one_or_none()

    async def get_by_event_id(self, event_id: str) -> EventModel | None:
        result = await self.session.execute(
            select(EventModel).where(EventModel.event_id == event_id)
        )
        return result.scalar_one_or_none()

    # -------------------------------------------------------------- reads
    def _apply_filter(self, stmt: Any, flt: EventFilter) -> Any:
        if flt.event_id:
            stmt = stmt.where(EventModel.event_id == flt.event_id)
        if flt.source_id:
            stmt = stmt.where(EventModel.source_id == flt.source_id)
        if flt.source_ids:
            stmt = stmt.where(EventModel.source_id.in_(flt.source_ids))
        if flt.source_category:
            # Source ids are namespaced as "<category>.<mode>", so a prefix match is enough.
            stmt = stmt.where(EventModel.source_id.like(f"{flt.source_category}.%"))
        if flt.event_type:
            stmt = stmt.where(EventModel.event_type == flt.event_type)
        if flt.event_types:
            stmt = stmt.where(EventModel.event_type.in_(flt.event_types))
        if flt.source_kind:
            stmt = stmt.where(EventModel.source_kind == flt.source_kind)
        if flt.quality_status:
            stmt = stmt.where(EventModel.quality_status == flt.quality_status)
        if flt.is_late is not None:
            stmt = stmt.where(EventModel.is_late.is_(flt.is_late))
        if flt.source_event_id:
            stmt = stmt.where(EventModel.source_event_id == flt.source_event_id)
        if flt.event_time_from:
            stmt = stmt.where(EventModel.event_time >= flt.event_time_from)
        if flt.event_time_to:
            stmt = stmt.where(EventModel.event_time <= flt.event_time_to)
        if flt.ingest_time_from:
            stmt = stmt.where(EventModel.ingest_time >= flt.ingest_time_from)
        if flt.latitude_min is not None:
            stmt = stmt.where(EventModel.latitude >= flt.latitude_min)
        if flt.latitude_max is not None:
            stmt = stmt.where(EventModel.latitude <= flt.latitude_max)
        if flt.longitude_min is not None:
            stmt = stmt.where(EventModel.longitude >= flt.longitude_min)
        if flt.longitude_max is not None:
            stmt = stmt.where(EventModel.longitude <= flt.longitude_max)
        return stmt

    async def query(
        self,
        flt: EventFilter,
        *,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "event_time",
        descending: bool = True,
    ) -> tuple[list[EventModel], int]:
        """Return a page of events plus the total matching count."""
        column = getattr(EventModel, order_by, EventModel.event_time)
        stmt = select(EventModel)
        stmt = self._apply_filter(stmt, flt)
        stmt = stmt.order_by(column.desc() if descending else column.asc())
        stmt = stmt.limit(limit).offset(offset)

        count_stmt = select(func.count()).select_from(EventModel)
        count_stmt = self._apply_filter(count_stmt, flt)

        rows = (await self.session.execute(stmt)).scalars().all()
        total = (await self.session.execute(count_stmt)).scalar_one()
        return list(rows), int(total)

    async def list_all_for_source(self, source_id: str, limit: int = 1000) -> list[EventModel]:
        stmt = (
            select(EventModel)
            .where(EventModel.source_id == source_id)
            .order_by(EventModel.event_time.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def latest_event_time_for_source(self, source_id: str) -> datetime | None:
        stmt = select(func.max(EventModel.event_time)).where(EventModel.source_id == source_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count(self, flt: EventFilter | None = None) -> int:
        stmt = select(func.count()).select_from(EventModel)
        if flt is not None:
            stmt = self._apply_filter(stmt, flt)
        return int((await self.session.execute(stmt)).scalar_one())

    async def source_ids(self) -> list[str]:
        stmt = select(EventModel.source_id).distinct()
        return list((await self.session.execute(stmt)).scalars().all())
