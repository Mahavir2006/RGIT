"""Repository for per-source health state."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SourceHealthModel

__all__ = ["SourceHealthRepository"]


class SourceHealthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, source_id: str) -> SourceHealthModel | None:
        result = await self.session.execute(
            select(SourceHealthModel).where(SourceHealthModel.source_id == source_id)
        )
        return result.scalar_one_or_none()

    async def upsert(self, source_id: str, defaults: dict) -> SourceHealthModel:
        """Fetch-or-create a health row and apply field updates."""
        model = await self.get(source_id)
        if model is None:
            model = SourceHealthModel(source_id=source_id)
            self.session.add(model)
        for key, value in defaults.items():
            if hasattr(model, key):
                setattr(model, key, value)
        await self.session.flush()
        return model

    async def increment_counters(self, source_id: str, counts: dict[str, int]) -> SourceHealthModel:
        """Add run-level counts to a source's cumulative totals.

        These counters are lifetime totals per source, not per-run values, so a run must *add* to
        them. Assigning would let a later duplicate-only run reset an earlier success to zero and
        make the health view lie about how much data the source has delivered.
        """
        model = await self.get(source_id)
        if model is None:
            model = SourceHealthModel(source_id=source_id)
            self.session.add(model)
            # A brand-new row starts from zero, so an add and an assign coincide.
            for column, amount in counts.items():
                if hasattr(model, column) and isinstance(amount, int):
                    setattr(model, column, amount)
        else:
            for column, amount in counts.items():
                if hasattr(model, column) and isinstance(amount, int):
                    setattr(model, column, int(getattr(model, column) or 0) + amount)
        await self.session.flush()
        return model

    async def list_all(self) -> list[SourceHealthModel]:
        result = await self.session.execute(
            select(SourceHealthModel).order_by(SourceHealthModel.source_id)
        )
        return list(result.scalars().all())
