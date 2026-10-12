"""Source health: transitions, freshness, and the "missing is not safe" principle."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.timeutil import utc_now
from app.schemas.common import SourceStatus
from app.schemas.ingestion import RunError
from app.services.source_health import SourceHealthService, derive_status
from tests.conftest import make_settings

SLA = 900


def _status(**overrides):
    defaults = dict(
        enabled=True,
        runnable=True,
        consecutive_failures=0,
        error_category=None,
        since_last_success_seconds=0.0,
        latest_event_time=utc_now(),
        freshness_sla_seconds=SLA,
    )
    defaults.update(overrides)
    return derive_status(**defaults)


# ------------------------------------------------------------ pure transitions
def test_healthy_when_recent_and_working():
    assert _status() == SourceStatus.HEALTHY


def test_unknown_when_never_produced_data():
    """A source that has never run is not healthy - it is unknown."""
    assert _status(latest_event_time=None, since_last_success_seconds=None) == (
        SourceStatus.UNKNOWN
    )


def test_stale_when_last_data_exceeds_its_own_sla():
    """Staleness is measured against this source's own expectation."""
    assert _status(since_last_success_seconds=SLA + 1) == SourceStatus.STALE
    assert _status(since_last_success_seconds=SLA - 1) == SourceStatus.HEALTHY


def test_stale_wins_over_absence_of_errors():
    assert _status(consecutive_failures=0, since_last_success_seconds=SLA * 2) == (
        SourceStatus.STALE
    )


def test_single_failure_is_degraded_not_offline():
    assert _status(consecutive_failures=1) == SourceStatus.DEGRADED


def test_repeated_failures_escalate_to_offline():
    assert _status(consecutive_failures=3) == SourceStatus.OFFLINE


def test_missing_credential_is_misconfigured():
    assert _status(error_category="credential_missing") == SourceStatus.MISCONFIGURED
    assert _status(error_category="upstream_auth_error") == SourceStatus.MISCONFIGURED


def test_not_runnable_is_misconfigured():
    assert _status(runnable=False) == SourceStatus.MISCONFIGURED


def test_disabled_beats_everything():
    assert _status(enabled=False, consecutive_failures=9) == SourceStatus.DISABLED


def test_freshness_uses_per_source_sla():
    settings = make_settings(freshness_sla_seconds={"water.dataset": 60})
    assert settings.freshness_for("water.dataset") == 60
    # Unlisted sources fall back to the global default.
    assert settings.freshness_for("weather.live") == settings.default_freshness_sla_seconds


# --------------------------------------------------------------- persistence
async def test_ensure_rows_creates_one_row_per_adapter(session):
    from app.ingestion.providers import build_default_registry

    registry = build_default_registry()
    service = SourceHealthService(session)
    rows = await service.ensure_rows(registry.all())
    await session.commit()

    assert len(rows) == len(registry.all())
    ids = {row.source_id for row in rows}
    assert {"weather.live", "airquality.live", "traffic.live", "water.dataset",
            "citizen.manual", "replay.all"} <= ids


async def test_record_success_advances_the_watermark(session):
    from app.ingestion.providers import build_default_registry

    service = SourceHealthService(session)
    adapter = build_default_registry().get("water.dataset")
    await service.ensure_rows([adapter])
    await service.record_success(
        adapter.source_id,
        counts={"fetched": 5, "accepted": 4, "duplicate": 1, "rejected": 0, "quarantined": 0},
        latest_event_time=utc_now(),
        run_id="run-1",
    )
    await session.commit()

    states = await service.list_states([adapter])
    state = states[0]
    assert state.last_success_at is not None
    assert state.latest_event_time is not None
    assert state.records_accepted == 4
    assert state.records_duplicate == 1
    assert state.last_run_id == "run-1"
    assert state.is_fresh is True


async def test_record_failure_preserves_the_previous_watermark(session):
    """A failed run says nothing about how old the data we already hold is."""
    from app.ingestion.providers import build_default_registry

    service = SourceHealthService(session)
    adapter = build_default_registry().get("water.dataset")
    await service.ensure_rows([adapter])

    observed = utc_now() - timedelta(minutes=2)
    await service.record_success(
        adapter.source_id, counts={"accepted": 3}, latest_event_time=observed, run_id="run-ok"
    )
    await session.commit()

    await service.record_failure(
        adapter.source_id,
        error=RunError(category="upstream_timeout", message="provider timed out"),
        run_id="run-fail",
    )
    await session.commit()

    state = (await service.list_states([adapter]))[0]
    # Watermark retained, failure recorded.
    assert state.latest_event_time is not None
    assert state.error_category == "upstream_timeout"
    assert state.consecutive_failures == 1
    assert state.status == SourceStatus.DEGRADED


async def test_consecutive_failures_accumulate(session):
    """Regression: the failure counter must actually increment, not hold a coroutine."""
    from app.ingestion.providers import build_default_registry

    service = SourceHealthService(session)
    adapter = build_default_registry().get("water.dataset")
    await service.ensure_rows([adapter])

    for index in range(3):
        await service.record_failure(
            adapter.source_id,
            error=RunError(category="upstream_unavailable", message=f"attempt {index}"),
            run_id=f"run-{index}",
        )
        await session.commit()

    state = (await service.list_states([adapter]))[0]
    assert state.consecutive_failures == 3
    assert state.status == SourceStatus.OFFLINE


async def test_success_resets_the_failure_counter(session):
    from app.ingestion.providers import build_default_registry

    service = SourceHealthService(session)
    adapter = build_default_registry().get("water.dataset")
    await service.ensure_rows([adapter])

    await service.record_failure(
        adapter.source_id, error=RunError(category="timeout", message="x"), run_id="r1"
    )
    await service.record_failure(
        adapter.source_id, error=RunError(category="timeout", message="x"), run_id="r2"
    )
    await service.record_success(
        adapter.source_id, counts={"accepted": 1}, latest_event_time=utc_now(), run_id="r3"
    )
    await session.commit()

    state = (await service.list_states([adapter]))[0]
    assert state.consecutive_failures == 0
    assert state.error_category is None


async def test_health_lists_every_adapter_with_a_freshness_expectation(session):
    from app.ingestion.providers import build_default_registry

    registry = build_default_registry()
    service = SourceHealthService(session)
    states = await service.list_states(registry.all())
    assert len(states) == len(registry.all())
    for state in states:
        assert state.freshness_sla_seconds > 0
        assert state.source_id and state.category and state.provider
