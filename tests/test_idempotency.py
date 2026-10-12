"""Persistence guarantees: atomic idempotency, duplicate receipts, late events.

These are the tests that protect the product's core claim — *a duplicate delivery must never
become a second canonical event, and a late event must never be rewritten.*
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.core.timeutil import parse_timestamp
from app.db.base import Base
from app.db import session as sm
from app.schemas.common import QualityFlag, SourceKind, ValidationOutcome
from app.schemas.event import (
    EventLocation,
    EventType,
    Measurement,
    build_canonical_event,
)
from app.services.event_service import EventService
from tests.conftest import make_settings


def _event(source_event_id: str | None = "gw-1", **overrides):
    defaults = dict(
        source_id="water.dataset",
        source_event_id=source_event_id,
        event_type=EventType.WATER_LEVEL_OBSERVED,
        event_time=parse_timestamp("2026-10-12T09:30:00Z"),
        ingest_time=parse_timestamp("2026-10-12T09:31:00Z"),
        location=EventLocation(latitude=19.0760, longitude=72.8777),
        measurements=[Measurement.build("water_level", 1.24, "m")],
        source_kind=SourceKind.SYNTHETIC,
    )
    defaults.update(overrides)
    return build_canonical_event(**defaults)


# ------------------------------------------------------------- single insert
async def test_event_is_persisted(session):
    service = EventService(session)
    outcome = await service.persist_event(_event())
    await session.commit()
    assert outcome.outcome == ValidationOutcome.ACCEPTED
    stored = await service.get(outcome.event_id)
    assert stored is not None
    assert stored.event_type == "water_level_observed"


# ---------------------------------------------------------------- idempotency
async def test_same_source_event_id_is_a_duplicate(session):
    service = EventService(session)
    first = await service.persist_event(_event("gw-1"))
    await session.commit()
    second = await service.persist_event(_event("gw-1"))
    await session.commit()

    assert first.outcome == ValidationOutcome.ACCEPTED
    assert second.outcome == ValidationOutcome.DUPLICATE
    # The duplicate points at the original event, not a new one.
    assert second.event_id == first.event_id

    # Exactly one canonical event exists.
    from app.db.repositories.event_repository import EventFilter, EventRepository

    rows, total = await EventRepository(session).query(EventFilter(source_id="water.dataset"))
    assert total == 1
    assert len(rows) == 1


async def test_duplicate_receipt_is_recorded(session):
    service = EventService(session)
    first = await service.persist_event(_event("gw-1"))
    await session.commit()
    await service.persist_event(_event("gw-1"))
    await session.commit()

    receipts = await service.duplicate_receipts(first.event_id)
    assert len(receipts) == 1
    assert receipts[0].decision == "idempotency_key"
    assert receipts[0].payload_hash is not None  # what was delivered, without storing it twice


async def test_repeated_delivery_never_inflates_corroboration(session):
    """Deliver the same event five times: still exactly one canonical event."""
    service = EventService(session)
    for _ in range(5):
        await service.persist_event(_event("gw-dup"))
    await session.commit()

    from app.db.repositories.event_repository import EventFilter, EventRepository

    rows, total = await EventRepository(session).query(EventFilter(source_id="water.dataset"))
    assert total == 1
    # Five receipts, one event.
    assert len(await service.duplicate_receipts(rows[0].event_id)) == 4


async def test_fingerprint_catches_duplicates_without_provider_id(session):
    """Two deliveries with no source_event_id still collapse via the content fingerprint."""
    a = _event(None)
    b = _event(None)
    assert a.fingerprint == b.fingerprint

    service = EventService(session)
    first = await service.persist_event(a)
    await session.commit()
    second = await service.persist_event(b)
    await session.commit()

    assert first.outcome == ValidationOutcome.ACCEPTED
    assert second.outcome == ValidationOutcome.DUPLICATE


async def test_distinct_events_are_not_collapsed(session):
    """Fingerprint dedup must not merge genuinely different readings."""
    service = EventService(session)
    first = await service.persist_event(_event("g1"))
    second = await service.persist_event(
        _event("g2", measurements=[Measurement.build("water_level", 1.99, "m")])
    )
    await session.commit()
    assert first.outcome == ValidationOutcome.ACCEPTED
    assert second.outcome == ValidationOutcome.ACCEPTED


async def test_second_transaction_is_rejected_without_any_prior_read(session):
    """Atomicity: the constraint rejects the duplicate, not a read-before-write check.

    The second delivery performs no lookup first. It simply inserts and is rejected by the
    database, then resolves to the canonical row for the receipt.
    """
    service = EventService(session)
    first = await service.persist_event(_event("atomic-1"))
    await session.commit()

    async with sm.get_session_factory()() as other:
        other_service = EventService(other)
        outcome = await other_service.persist_event(_event("atomic-1"))
        await other.commit()

    assert first.outcome == ValidationOutcome.ACCEPTED
    assert outcome.outcome == ValidationOutcome.DUPLICATE
    assert outcome.event_id == first.event_id

    from app.db.repositories.event_repository import EventFilter, EventRepository

    _, total = await EventRepository(session).query(EventFilter(source_id="water.dataset"))
    assert total == 1


async def test_concurrent_delivery_still_yields_exactly_one_canonical_event(tmp_path):
    """Race two deliveries of the same event and assert the invariant that matters.

    Note on the environment: SQLite in-memory uses a single shared connection, so two sessions
    cannot hold genuinely independent write transactions. The property verified here is therefore
    the invariant - exactly one canonical event survives - rather than how the losing delivery is
    classified. On PostgreSQL, where each session has its own connection and MVCC snapshot, the
    loser is reliably classified as a duplicate; that path is covered by the test above.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    url = f"sqlite+aiosqlite:///{(tmp_path / 'race.db').as_posix()}"
    engine = create_async_engine(url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    event = _event("gw-race")

    async def deliver() -> str:
        async with factory() as sess:
            try:
                outcome = await EventService(sess).persist_event(event)
                await sess.commit()
                return outcome.outcome.value
            except Exception as exc:  # noqa: BLE001
                await sess.rollback()
                return f"error:{type(exc).__name__}"

    results = await asyncio.gather(deliver(), deliver())

    async with factory() as sess:
        from app.db.repositories.event_repository import EventFilter, EventRepository

        rows, total = await EventRepository(sess).query(EventFilter(source_id="water.dataset"))

    await engine.dispose()

    # The invariant: one canonical event, and at most one delivery accepted it.
    assert total == 1
    assert len([r for r in results if r == "accepted"]) == 1


async def test_batch_with_duplicates_commits_the_good_ones(session):
    """A duplicate in the middle of a batch must not roll back earlier accepted events."""
    service = EventService(session)
    summary = await service.persist_batch([
        _event("b1"),
        _event("b1"),  # exact re-delivery
        _event("b2", measurements=[Measurement.build("water_level", 2.5, "m")]),
    ])
    assert summary.accepted == 2
    assert summary.duplicate == 1


async def test_two_measurement_less_reports_are_not_collapsed(session):
    """Regression: two citizen reports for one area in the same minute are distinct.

    Reports carry no measurements, so a naive content fingerprint would be identical for both and
    the second would be discarded as a duplicate - destroying the corroboration the product exists
    to surface.
    """
    from app.schemas.event import build_canonical_event as build

    def report(reporter: str):
        return build(
            source_id="citizen.manual",
            source_event_id=reporter,
            event_type=EventType.WATERLOGGING_REPORTED,
            event_time=parse_timestamp("2026-10-12T09:12:30Z"),
            ingest_time=parse_timestamp("2026-10-12T09:12:45Z"),
            location=EventLocation(latitude=19.0760, longitude=72.8777, accuracy_m=40),
            measurements=[],
            source_kind=SourceKind.MANUAL,
        )

    a, b = report("reporter_a1"), report("reporter_b7")
    assert a.fingerprint != b.fingerprint

    service = EventService(session)
    first = await service.persist_event(a)
    second = await service.persist_event(b)
    await session.commit()

    assert first.outcome == ValidationOutcome.ACCEPTED
    assert second.outcome == ValidationOutcome.ACCEPTED

    # Re-delivering the *same* report still dedups.
    again = await service.persist_event(report("reporter_a1"))
    await session.commit()
    assert again.outcome == ValidationOutcome.DUPLICATE


# ----------------------------------------------------------------- late events
async def test_late_event_retains_its_observation_time(session):
    """An event observed earlier but arriving later keeps its original event_time."""
    service = EventService(session)
    await service.persist_event(_event("late-1"))
    # Same gauge, same minute, but observed at 09:00 and received at 09:50.
    late = _event(
        "late-2",
        event_time=parse_timestamp("2026-10-12T09:00:00Z"),
        ingest_time=parse_timestamp("2026-10-12T09:50:00Z"),
        measurements=[Measurement.build("water_level", 0.88, "m")],
    )
    outcome = await service.persist_event(late)
    await session.commit()

    assert outcome.outcome == ValidationOutcome.ACCEPTED
    stored = await service.get(outcome.event_id)
    restored = EventService.to_canonical(stored)
    assert restored.event_time == parse_timestamp("2026-10-12T09:00:00Z")
    assert restored.ingest_time == parse_timestamp("2026-10-12T09:50:00Z")
    assert stored.is_late is True


async def test_out_of_order_arrival_is_accepted_not_discarded(session):
    service = EventService(session)
    late_first = _event("oo-1", event_time=parse_timestamp("2026-10-12T08:00:00Z"))
    newer_second = _event("oo-2", event_time=parse_timestamp("2026-10-12T09:00:00Z"))
    for event in (late_first, newer_second):
        outcome = await service.persist_event(event)
        assert outcome.outcome == ValidationOutcome.ACCEPTED
    await session.commit()

    from app.db.repositories.event_repository import EventFilter, EventRepository

    # Event-time ordering is independent of arrival order.
    rows, total = await EventRepository(session).query(
        EventFilter(source_id="water.dataset"), order_by="event_time", descending=False
    )
    assert total == 2
    assert rows[0].event_time < rows[1].event_time


# ------------------------------------------------------------ round-tripping
async def test_canonical_event_round_trips_through_the_database(session):
    service = EventService(session)
    original = _event(
        "rt-1",
        measurements=[
            Measurement.build(
                "rainfall_1h", 28.4, "in",
                aggregation="accumulation", period_seconds=3600,
            )
        ],
    )
    await service.persist_event(original)
    await session.commit()

    stored = await service.get(original.event_id)
    restored = EventService.to_canonical(stored)

    assert restored.event_id == original.event_id
    assert restored.idempotency_key == original.idempotency_key
    assert restored.fingerprint == original.fingerprint
    assert restored.event_time == original.event_time
    assert restored.event_type == original.event_type
    assert restored.source_kind == original.source_kind

    measurement = restored.measurements[0]
    assert measurement.name == "rainfall_1h"
    assert measurement.aggregation.value == "accumulation"
    assert measurement.period_seconds == 3600
    # Original provider units survive the round trip: 28.4 inches -> 721.36 mm.
    assert measurement.original_unit == "in"
    assert measurement.original_value == pytest.approx(28.4)
    assert measurement.value == pytest.approx(28.4 * 25.4, abs=0.01)
    assert measurement.converted is True


async def test_zero_value_measurement_survives_persistence(session):
    """Zero is a real reading and must not be confused with absence."""
    service = EventService(session)
    event = _event("zero-1", measurements=[Measurement.build("water_level", 0.0, "m")])
    await service.persist_event(event)
    await session.commit()

    stored = await service.get(event.event_id)
    restored = EventService.to_canonical(stored)
    assert restored.measurements[0].value == 0.0
