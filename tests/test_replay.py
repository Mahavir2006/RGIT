"""Deterministic replay: stable identity, labelled provenance, out-of-order arrival."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.errors import NotFoundError
from app.ingestion.base import FetchRequest
from app.ingestion.replay import FIXTURES, ReplayAdapter
from app.schemas.common import QualityFlag, SourceKind
from tests.conftest import make_settings


def _adapter(samples_dir, **overrides) -> ReplayAdapter:
    return ReplayAdapter(make_settings(replay_fixtures_dir=str(samples_dir), **overrides))


def _req(**overrides) -> FetchRequest:
    base = dict(source_id="replay.all", correlation_id="t")
    base.update(overrides)
    return FetchRequest(**base)


async def test_all_categories_are_covered_by_fixtures(samples_dir):
    """The five required source categories each have a fixture."""
    assert {"weather", "air_quality", "traffic", "water", "citizen"} <= set(FIXTURES)
    adapter = _adapter(samples_dir)
    result = await adapter.fetch_events(_req(fixture="all"))
    source_ids = {e.source_id for e in result.events}
    categories = {sid.split(".")[0] for sid in source_ids}
    assert {"weather", "airquality", "traffic", "citizen"} <= categories
    # water comes from the combined scenario
    assert any("water" in sid for sid in source_ids)


async def test_every_replayed_event_is_labelled_synthetic(samples_dir):
    adapter = _adapter(samples_dir)
    result = await adapter.fetch_events(_req(fixture="monsoon_waterlogging"))
    assert result.events
    for event in result.events:
        assert event.source_kind == SourceKind.SYNTHETIC
        assert QualityFlag.SYNTHETIC_DATA in event.quality_flags
        assert event.payload.get("synthetic") is True


async def test_event_identity_is_stable_across_runs(samples_dir):
    """Same fixture in, same identity out - this is what makes replay reproducible."""
    adapter = _adapter(samples_dir)
    first = await adapter.fetch_events(_req(fixture="monsoon_waterlogging"))
    second = await adapter.fetch_events(_req(fixture="monsoon_waterlogging"))
    assert [e.event_id for e in first.events] == [e.event_id for e in second.events]
    assert [e.idempotency_key for e in first.events] == [
        e.idempotency_key for e in second.events
    ]
    assert [e.fingerprint for e in first.events] == [e.fingerprint for e in second.events]


async def test_identity_is_independent_of_arrival_order(samples_dir):
    """Shuffling arrival must not change identity, only the order events are delivered in."""
    adapter = _adapter(samples_dir)
    ordered = await adapter.fetch_events(_req(fixture="monsoon_waterlogging"))
    shuffled = await adapter.fetch_events(
        _req(fixture="monsoon_waterlogging", shuffle=True, shuffle_seed=1337)
    )
    assert {e.event_id for e in ordered.events} == {e.event_id for e in shuffled.events}
    # The same set, delivered in a different order.
    assert [e.event_id for e in ordered.events] != [e.event_id for e in shuffled.events]


async def test_shuffle_is_reproducible_for_a_given_seed(samples_dir):
    adapter = _adapter(samples_dir)
    a = await adapter.fetch_events(
        _req(fixture="monsoon_waterlogging", shuffle=True, shuffle_seed=7)
    )
    b = await adapter.fetch_events(
        _req(fixture="monsoon_waterlogging", shuffle=True, shuffle_seed=7)
    )
    c = await adapter.fetch_events(
        _req(fixture="monsoon_waterlogging", shuffle=True, shuffle_seed=8)
    )
    assert [e.event_id for e in a.events] == [e.event_id for e in b.events]
    assert [e.event_id for e in a.events] != [e.event_id for e in c.events]


async def test_shuffle_preserves_event_time(samples_dir):
    """Out-of-order arrival must not rewrite observation times."""
    adapter = _adapter(samples_dir)
    ordered = await adapter.fetch_events(_req(fixture="monsoon_waterlogging"))
    shuffled = await adapter.fetch_events(
        _req(fixture="monsoon_waterlogging", shuffle=True, shuffle_seed=99)
    )
    ordered_times = sorted(e.event_time for e in ordered.events)
    shuffled_times = sorted(e.event_time for e in shuffled.events)
    assert ordered_times == shuffled_times


async def test_rebase_moves_events_to_the_present(samples_dir):
    adapter = _adapter(samples_dir, replay_rebase_to_now=True)
    result = await adapter.fetch_events(_req(fixture="monsoon_waterlogging"))
    newest = max(e.event_time for e in result.events)
    # Within an hour of now, rather than at the fixture's literal 2026-10-12 timestamps.
    from datetime import timedelta

    from app.core.timeutil import utc_now

    assert utc_now() - newest < timedelta(hours=1)


async def test_rebase_disabled_keeps_literal_timestamps(samples_dir):
    adapter = _adapter(samples_dir, replay_rebase_to_now=False)
    result = await adapter.fetch_events(_req(fixture="monsoon_waterlogging"))
    assert any(e.event_time.year == 2026 and e.event_time.month == 10 for e in result.events)


async def test_unknown_fixture_is_reported(samples_dir):
    adapter = _adapter(samples_dir)
    with pytest.raises(NotFoundError) as exc:
        await adapter.fetch_events(_req(fixture="does-not-exist"))
    assert "available" in exc.value.details


async def test_unknown_event_type_in_fixture_is_skipped_not_fatal(tmp_path, samples_dir):
    """An adapter or fixture bug must not abort the whole replay."""
    import json

    bad = tmp_path / "bad.json"
    records = [
        {"event_type": "teleportation_observed", "event_time": "2026-10-12T09:00:00Z"},
        {
            "source_id": "weather.replay",
            "event_type": "rainfall_observed",
            "event_time": "2026-10-12T09:00:00Z",
            "location": {"latitude": 19.07, "longitude": 72.87},
            "measurements": [
                {"name": "rainfall_1h", "value": 5.0, "unit": "mm",
                 "aggregation": "accumulation", "period_seconds": 3600}
            ],
        },
    ]
    bad.write_text(json.dumps({"events": records}), encoding="utf-8")

    adapter = ReplayAdapter(make_settings(replay_fixtures_dir=str(tmp_path)))
    built = [
        event
        for event in (
            adapter._build_event(record, index, offset=timedelta(0))
            for index, record in enumerate(records)
        )
        if event is not None
    ]
    assert len(built) == 1
    assert built[0].event_type.value == "rainfall_observed"


async def test_rainfall_accumulation_semantics_survive_replay(samples_dir):
    adapter = _adapter(samples_dir)
    result = await adapter.fetch_events(_req(fixture="weather"))
    rainfall = [
        m for e in result.events for m in e.measurements if m.name.startswith("rainfall")
    ]
    assert rainfall
    for measurement in rainfall:
        assert measurement.aggregation.value == "accumulation"
        assert measurement.period_seconds == 3600
