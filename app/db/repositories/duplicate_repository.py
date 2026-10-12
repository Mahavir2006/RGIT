"""Repositories for duplicate receipts and quarantined records."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DuplicateReceiptModel, QuarantineModel

__all__ = ["DuplicateRepository", "QuarantineRepository", "payload_hash"]


def payload_hash(payload: Any) -> str | None:
    """Stable hash of a payload, used to record *what* was delivered without storing it twice."""
    if payload is None:
        return None
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


class DuplicateRepository:
    """Records duplicate deliveries for audit and debugging."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        event_id: str,
        source_id: str,
        source_event_id: str | None,
        decision: str,
        rule: str,
        idempotency_key: str | None,
        fingerprint: str | None,
        run_id: str | None,
        payload: Any = None,
    ) -> DuplicateReceiptModel:
        model = DuplicateReceiptModel(
            event_id=event_id,
            source_id=source_id,
            source_event_id=source_event_id,
            decision=decision,
            rule=rule,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            run_id=run_id,
            payload_hash=payload_hash(payload),
        )
        self.session.add(model)
        await self.session.flush()
        return model

    async def list_for_event(self, event_id: str) -> list[DuplicateReceiptModel]:
        result = await self.session.execute(
            select(DuplicateReceiptModel)
            .where(DuplicateReceiptModel.event_id == event_id)
            .order_by(DuplicateReceiptModel.received_at)
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        from sqlalchemy import func

        result = await self.session.execute(select(func.count()).select_from(DuplicateReceiptModel))
        return int(result.scalar_one())


class QuarantineRepository:
    """Stores records that failed validation, for inspection and safe replay."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        source_id: str,
        reason_code: str,
        message: str | None,
        field_errors: list[dict[str, Any]] | None,
        payload: dict[str, Any],
        run_id: str | None = None,
    ) -> QuarantineModel:
        model = QuarantineModel(
            source_id=source_id,
            run_id=run_id,
            reason_code=reason_code,
            message=message,
            field_errors=field_errors or [],
            payload=payload or {},
        )
        self.session.add(model)
        await self.session.flush()
        return model

    async def list_recent(
        self, *, source_id: str | None = None, limit: int = 50
    ) -> list[QuarantineModel]:
        stmt = select(QuarantineModel)
        if source_id:
            stmt = stmt.where(QuarantineModel.source_id == source_id)
        stmt = stmt.order_by(QuarantineModel.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())
