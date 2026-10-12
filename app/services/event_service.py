"""Event orchestration: validate, deduplicate, persist, record lineage.

Idempotency is enforced by **database unique constraints**, not by a read-before-write check. A
read-then-insert sequence lets two concurrent deliveries of the same event both observe "not
present" and both insert. The insert either succeeds or raises ``IntegrityError``; there is no
window between the two.

Flow for every canonical event
------------------------------
1. Map to a row (immutable facts only).
2. Attempt insert; flush.
3. On ``IntegrityError``, identify the canonical row and write a **duplicate receipt**.
   The duplicate receipt is a debugging and audit artefact — it is never a second canonical event,
   and it is never counted as corroboration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.timeutil import ensure_aware
from app.db.models import EventModel
from app.db.repositories.duplicate_repository import DuplicateRepository, QuarantineRepository
from app.db.repositories.event_repository import EventRepository
from app.schemas.common import DuplicateDecision, ValidationOutcome
from app.schemas.event import CanonicalEvent
from app.schemas.ingestion import RecordOutcome

__all__ = ["EventService", "PersistSummary"]

logger = get_logger(__name__)


@dataclass(slots=True)
class PersistSummary:
    """Aggregate result of persisting a batch of canonical events."""

    accepted: int = 0
    duplicate: int = 0
    rejected: int = 0
    quarantined: int = 0
    accepted_event_ids: list[str] = field(default_factory=list)
    duplicate_event_ids: list[str] = field(default_factory=list)
    outcomes: list[RecordOutcome] = field(default_factory=list)
    latest_event_time: datetime | None = None

    def as_counts(self) -> dict[str, int]:
        return {
            "accepted": self.accepted,
            "duplicate": self.duplicate,
            "rejected": self.rejected,
            "quarantined": self.quarantined,
        }


class EventService:
    """Persists canonical events with atomic idempotency and full lineage."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.events = EventRepository(session)
        self.duplicates = DuplicateRepository(session)
        self.quarantine = QuarantineRepository(session)

    # -------------------------------------------------------------- mapping
    @staticmethod
    def to_model(event: CanonicalEvent) -> EventModel:
        """Convert a canonical event into a database row."""
        location = event.location
        return EventModel(
            event_id=event.event_id,
            source_id=event.source_id,
            source_event_id=event.source_event_id,
            idempotency_key=event.idempotency_key,
            fingerprint=event.fingerprint,
            event_type=event.event_type.value,
            source_kind=event.source_kind.value,
            event_time=event.event_time,
            ingest_time=event.ingest_time,
            latitude=location.latitude if location else None,
            longitude=location.longitude if location else None,
            accuracy_m=location.accuracy_m if location else None,
            location_precision=location.precision.value if location else None,
            place_id=location.place_id if location else None,
            area_reference=location.area_reference if location else None,
            geometry_ref=location.geometry_ref if location else None,
            radius_m=location.radius_m if location else None,
            measurements=[m.model_dump(mode="json") for m in event.measurements],
            payload=event.payload,
            text=event.text,
            quality_status=event.quality_status.value,
            quality_flags=[f.value for f in event.quality_flags],
            schema_version=event.schema_version,
            is_late=event.is_late,
            is_duplicate=False,
        )

    @staticmethod
    def to_canonical(row: EventModel) -> CanonicalEvent:
        """Rebuild a canonical event from a stored row."""
        from app.schemas.common import LocationPrecision, MeasurementAggregation, QualityFlag
        from app.schemas.common import QualityStatus, SourceKind
        from app.schemas.event import EventLocation, EventType, Measurement

        location = None
        if row.latitude is not None and row.longitude is not None:
            location = EventLocation(
                latitude=row.latitude,
                longitude=row.longitude,
                accuracy_m=row.accuracy_m,
                precision=LocationPrecision(row.location_precision)
                if row.location_precision
                else LocationPrecision.APPROXIMATE,
                place_id=row.place_id,
                area_reference=row.area_reference,
                geometry_ref=row.geometry_ref,
                radius_m=row.radius_m,
            )
        elif row.place_id or row.area_reference:
            location = EventLocation(
                precision=LocationPrecision.UNKNOWN,
                place_id=row.place_id,
                area_reference=row.area_reference,
            )

        measurements = []
        for item in row.measurements or []:
            try:
                measurements.append(
                    Measurement(
                        name=item["name"],
                        value=item["value"],
                        unit=item["unit"],
                        original_value=item.get("original_value"),
                        original_unit=item.get("original_unit"),
                        period_seconds=item.get("period_seconds"),
                        aggregation=MeasurementAggregation(
                            item.get("aggregation", "instantaneous")
                        ),
                        converted=bool(item.get("converted", False)),
                        lower_limit=item.get("lower_limit"),
                        upper_limit=item.get("upper_limit"),
                    )
                )
            except (KeyError, ValueError):
                # A stored measurement that no longer validates is skipped rather than crashing
                # a read; the raw dict remains available via the row.
                logger.warning(
                    "stored measurement failed validation on read",
                    extra={"event_id": row.event_id, "measurement": str(item)[:120]},
                )

        return CanonicalEvent(
            event_id=row.event_id,
            source_id=row.source_id,
            source_event_id=row.source_event_id,
            event_type=EventType(row.event_type),
            # PostgreSQL TIMESTAMPTZ round-trips the offset, but SQLite has no timezone type and
            # returns naive values. Timestamps are always *written* as UTC, so a naive value read
            # back means UTC and is re-tagged here rather than being rejected.
            event_time=ensure_aware(row.event_time),
            ingest_time=ensure_aware(row.ingest_time),
            location=location,
            measurements=measurements,
            source_kind=SourceKind(row.source_kind),
            quality_status=QualityStatus(row.quality_status),
            quality_flags=[QualityFlag(f) for f in (row.quality_flags or [])],
            text=row.text,
            payload=row.payload or {},
            schema_version=row.schema_version,
            idempotency_key=row.idempotency_key,
            fingerprint=row.fingerprint,
        )

    # --------------------------------------------------------------- writes
    async def persist_event(
        self,
        event: CanonicalEvent,
        *,
        run_id: str | None = None,
        dry_run: bool = False,
    ) -> RecordOutcome:
        """Persist one canonical event, returning a duplicate receipt when appropriate.

        The insert runs inside a SAVEPOINT so that a uniqueness violation rolls back only this
        statement. A full ``session.rollback()`` would discard every event already accepted earlier
        in the same batch.
        """
        if dry_run:
            return RecordOutcome(
                outcome=ValidationOutcome.ACCEPTED,
                event_id=event.event_id,
                source_event_id=event.source_event_id,
                message="Dry run: the event was validated but not persisted.",
            )

        model = self.to_model(event)
        model.first_run_id = run_id

        try:
            async with self.session.begin_nested():
                self.session.add(model)
                await self.session.flush()
        except IntegrityError:
            # The SAVEPOINT was rolled back by the context manager; the outer transaction, and
            # everything already accepted in it, is intact.
            return await self._record_duplicate(event, run_id=run_id)

        return RecordOutcome(
            outcome=ValidationOutcome.ACCEPTED,
            event_id=event.event_id,
            source_event_id=event.source_event_id,
        )

    async def _record_duplicate(
        self, event: CanonicalEvent, *, run_id: str | None
    ) -> RecordOutcome:
        """Identify the canonical row this delivery duplicates and write a receipt."""
        existing = await self.events.get_by_idempotency_key(event.idempotency_key)

        decision = DuplicateDecision.IDEMPOTENCY_KEY
        rule = "unique constraint on idempotency_key"

        if existing is None:
            existing = await self.events.get_by_fingerprint(event.fingerprint)
            decision = DuplicateDecision.FINGERPRINT
            rule = "unique constraint on fingerprint (content fallback)"

        if existing is None and event.source_event_id:
            existing = await self.events.get_by_source_event_id(
                event.source_id, event.source_event_id
            )
            decision = DuplicateDecision.SOURCE_EVENT_ID
            rule = "unique constraint on (source_id, source_event_id)"

        if existing is None:
            # The constraint fired on something we did not anticipate. Report it rather than
            # silently dropping the record.
            logger.warning(
                "integrity error without a resolvable duplicate row",
                extra={
                    "event_id": event.event_id,
                    "source_id": event.source_id,
                    "idempotency_key": event.idempotency_key,
                },
            )
            return RecordOutcome(
                outcome=ValidationOutcome.QUARANTINED,
                event_id=event.event_id,
                reason_code="unresolved_constraint_violation",
                message="The record violated a uniqueness constraint but no canonical row matched.",
            )

        await self.duplicates.record(
            event_id=existing.event_id,
            source_id=event.source_id,
            source_event_id=event.source_event_id,
            decision=decision.value,
            rule=rule,
            idempotency_key=event.idempotency_key,
            fingerprint=event.fingerprint,
            run_id=run_id,
            payload=event.payload,
        )

        return RecordOutcome(
            outcome=ValidationOutcome.DUPLICATE,
            event_id=existing.event_id,
            source_event_id=event.source_event_id,
            reason_code=decision.value,
            message=f"Duplicate delivery matched existing event {existing.event_id} via {rule}.",
            duplicate={
                "decision": decision.value,
                "matched_event_id": existing.event_id,
                "rule": rule,
                "idempotency_key": event.idempotency_key,
                "fingerprint": event.fingerprint,
            },
        )

    async def persist_batch(
        self,
        events: list[CanonicalEvent],
        *,
        run_id: str | None = None,
        dry_run: bool = False,
    ) -> PersistSummary:
        """Persist a batch, collecting per-record outcomes.

        Each event is committed independently so that one bad record cannot roll back good ones.
        """
        summary = PersistSummary()

        for event in events:
            try:
                outcome = await self.persist_event(event, run_id=run_id, dry_run=dry_run)
            except PydanticValidationError as exc:
                await self._quarantine(event, exc, run_id)
                summary.quarantined += 1
                outcome = RecordOutcome(
                    outcome=ValidationOutcome.QUARANTINED,
                    source_event_id=event.source_event_id,
                    reason_code="validation_failed",
                    message="The event failed schema validation during persistence.",
                )
            except Exception as exc:  # noqa: BLE001 - isolate per-record failures
                logger.exception(
                    "unexpected error persisting event",
                    extra={"event_id": event.event_id, "source_id": event.source_id},
                )
                await self._quarantine(event, exc, run_id)
                summary.quarantined += 1
                outcome = RecordOutcome(
                    outcome=ValidationOutcome.QUARANTINED,
                    source_event_id=event.source_event_id,
                    reason_code="persistence_error",
                    message=f"{type(exc).__name__} while persisting the event.",
                )

            self._tally(summary, outcome)

        if not dry_run:
            await self.session.commit()
        else:
            await self.session.rollback()

        return summary

    async def _quarantine(self, event: CanonicalEvent, exc: Exception, run_id: str | None) -> None:
        """Store an unusable record for inspection and safe replay.

        Runs inside its own savepoint and never commits, so a failure here cannot mask the
        original error or roll back the rest of the batch.
        """
        try:
            async with self.session.begin_nested():
                await self.quarantine.record(
                    source_id=event.source_id,
                    run_id=run_id,
                    reason_code="persistence_error",
                    message=f"{type(exc).__name__}",
                    field_errors=[],
                    payload={"event_id": event.event_id, "event": event.model_dump(mode="json")},
                )
        except Exception:  # noqa: BLE001 - quarantine must never mask the original failure
            logger.exception("failed to record quarantine entry")

    @staticmethod
    def _tally(summary: PersistSummary, outcome: RecordOutcome) -> None:
        summary.outcomes.append(outcome)
        if outcome.outcome == ValidationOutcome.ACCEPTED:
            summary.accepted += 1
            if outcome.event_id:
                summary.accepted_event_ids.append(outcome.event_id)
        elif outcome.outcome == ValidationOutcome.DUPLICATE:
            summary.duplicate += 1
            if outcome.event_id:
                summary.duplicate_event_ids.append(outcome.event_id)
        elif outcome.outcome == ValidationOutcome.QUARANTINED:
            summary.quarantined += 1
        else:
            summary.rejected += 1

    # -------------------------------------------------------------- reads
    async def get(self, event_id: str) -> EventModel | None:
        return await self.events.get_by_event_id(event_id)

    async def duplicate_receipts(self, event_id: str) -> list[Any]:
        return await self.duplicates.list_for_event(event_id)


def rejection_outcome(
    *, reason_code: str, message: str, source_event_id: str | None = None,
    outcome: ValidationOutcome = ValidationOutcome.REJECTED,
) -> RecordOutcome:
    """Build a rejection/quarantine outcome for an adapter-reported problem."""
    return RecordOutcome(
        outcome=outcome,
        source_event_id=source_event_id,
        reason_code=reason_code,
        message=message,
    )
