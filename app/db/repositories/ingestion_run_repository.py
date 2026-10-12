"""Repository for ingestion-run records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionRunModel

__all__ = ["IngestionRunRepository"]


class IngestionRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, model: IngestionRunModel) -> IngestionRunModel:
        self.session.add(model)
        await self.session.flush()
        return model

    async def get(self, run_id: str) -> IngestionRunModel | None:
        result = await self.session.execute(
            select(IngestionRunModel).where(IngestionRunModel.run_id == run_id)
        )
        return result.scalar_one_or_none()

    async def has_active_run(self, source_id: str) -> bool:
        """True when a run for this source is pending or running.

        Used to prevent overlapping runs of the same source.
        """
        result = await self.session.execute(
            select(IngestionRunModel.run_id).where(
                IngestionRunModel.source_id == source_id,
                IngestionRunModel.status.in_(["pending", "running"]),
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_recent(
        self,
        *,
        source_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        since: datetime | None = None,
    ) -> tuple[list[IngestionRunModel], int]:
        stmt = select(IngestionRunModel)
        count_stmt = select(IngestionRunModel)
        if source_id:
            stmt = stmt.where(IngestionRunModel.source_id == source_id)
            count_stmt = count_stmt.where(IngestionRunModel.source_id == source_id)
        if since:
            stmt = stmt.where(IngestionRunModel.started_at >= since)
            count_stmt = count_stmt.where(IngestionRunModel.started_at >= since)

        total = len((await self.session.execute(count_stmt)).scalars().all())
        stmt = stmt.order_by(IngestionRunModel.started_at.desc()).limit(limit).offset(offset)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total
