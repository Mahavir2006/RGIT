"""Water-level dataset adapter: mapping, units, thresholds, and bad-row quarantine."""

from __future__ import annotations

import json

import pytest

from app.core.errors import NotFoundError, UpstreamUnavailableError
from app.ingestion.base import FetchRequest
from app.ingestion.water import WaterDatasetAdapter
from tests.conftest import make_settings


def _request() -> FetchRequest:
    return FetchRequest(source_id="water.dataset", correlation_id="test")


async def test_default_csv_dataset_ingests(samples_dir):
    adapter = WaterDatasetAdapter(make_settings(replay_fixtures_dir=str(samples_dir)))
    result = await adapter.fetch_events(_request())
    assert len(result.events) == 8
    assert result.errors == []

    event = result.events[0]
    assert event.source_id == "water.dataset"
    # File-backed data is never presented as a live observation.
    assert event.source_kind.value in ("historical", "synthetic")

    names = {m.name for m in event.measurements}
    assert "water_level" in names
    assert "water_level_threshold" in names
    assert event.payload["station_id"] == "WGD-04"
    assert event.payload["datum"] == "MSL"


async def test_threshold_travels_with_its_own_unit(samples_dir):
    adapter = WaterDatasetAdapter(make_settings(replay_fixtures_dir=str(samples_dir)))
    result = await adapter.fetch_events(_request())
    threshold = next(m for m in result.events[0].measurements
                     if m.name == "water_level_threshold")
    assert threshold.value == pytest.approx(0.75)
    assert threshold.unit == "m"


async def test_station_without_threshold_records_absence(samples_dir):
    """An absent threshold is recorded as absent, never defaulted to a 'safe' value."""
    adapter = WaterDatasetAdapter(make_settings(replay_fixtures_dir=str(samples_dir)))
    result = await adapter.fetch_events(_request())
    malad = next(e for e in result.events if e.payload["station_id"] == "WGD-09")
    assert malad.payload["threshold_present"] is False
    assert "optional_measurement_absent" in [f.value for f in malad.quality_flags]
    assert not any(m.name == "water_level_threshold" for m in malad.measurements)


async def test_station_with_threshold_is_unaffected(samples_dir):
    adapter = WaterDatasetAdapter(make_settings(replay_fixtures_dir=str(samples_dir)))
    result = await adapter.fetch_events(_request())
    powai = next(e for e in result.events if e.payload["station_id"] == "WGD-07")
    assert powai.payload["threshold_present"] is True
    assert any(m.name == "water_level_threshold" for m in powai.measurements)


async def test_identity_is_deterministic_across_runs(samples_dir):
    adapter = WaterDatasetAdapter(make_settings(replay_fixtures_dir=str(samples_dir)))
    first = await adapter.fetch_events(_request())
    second = await adapter.fetch_events(_request())
    assert [e.event_id for e in first.events] == [e.event_id for e in second.events]
    assert [e.idempotency_key for e in first.events] == [
        e.idempotency_key for e in second.events
    ]


async def test_json_dataset_is_supported(tmp_path, samples_dir):
    path = tmp_path / "water.json"
    path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "station_id": "GAUGE-J",
                        "observed_at": "2026-10-12T09:00:00Z",
                        "water_level": 132.0,
                        "unit": "cm",
                        "latitude": 19.1,
                        "longitude": 72.8,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    adapter = WaterDatasetAdapter(
        make_settings(water_dataset_path=str(path), replay_fixtures_dir=str(samples_dir))
    )
    result = await adapter.fetch_events(_request())
    assert len(result.events) == 1
    # cm normalised to m, original retained.
    assert result.events[0].measurements[0].value == pytest.approx(1.32)
    assert result.events[0].measurements[0].original_unit == "cm"


@pytest.mark.parametrize(
    "row,reason",
    [
        ({"observed_at": "2026-10-12T09:00:00Z", "water_level": 1.0, "unit": "m"},
         "missing_required_field"),
        ({"station_id": "S1", "water_level": 1.0, "unit": "m"},
         "missing_required_field"),
        ({"station_id": "S1", "observed_at": "2026-10-12T09:00:00Z", "unit": "m"},
         "missing_required_field"),
        ({"station_id": "S1", "observed_at": "2026-10-12T09:00:00Z", "water_level": 1.0},
         "missing_required_field"),
        ({"station_id": "S1", "observed_at": "not-a-time", "water_level": 1.0, "unit": "m"},
         "invalid_timestamp"),
        ({"station_id": "S1", "observed_at": "2026-10-12T09:00:00Z",
          "water_level": "deep", "unit": "m"}, "invalid_measurement_value"),
    ],
)
async def test_bad_rows_are_quarantined_with_a_reason(tmp_path, samples_dir, row, reason):
    path = tmp_path / "bad.csv"
    header = "station_id,observed_at,water_level,unit"
    path.write_text(
        header + "\n" + ",".join(str(row.get(k, "")) for k in header.split(",")) + "\n",
        encoding="utf-8",
    )
    adapter = WaterDatasetAdapter(
        make_settings(water_dataset_path=str(path), replay_fixtures_dir=str(samples_dir))
    )
    result = await adapter.fetch_events(_request())
    assert result.events == []
    assert result.outcomes[0].outcome.value == "quarantined"
    assert result.outcomes[0].reason_code == reason


async def test_missing_dataset_raises_actionable_error(samples_dir):
    adapter = WaterDatasetAdapter(
        make_settings(water_dataset_path="does/not/exist.csv",
                      replay_fixtures_dir=str(samples_dir))
    )
    with pytest.raises(NotFoundError) as exc:
        await adapter.fetch_events(_request())
    assert "WATER_DATASET_PATH" in str(exc.value)


async def test_custom_mapping_is_applied(tmp_path, samples_dir):
    path = tmp_path / "custom.csv"
    path.write_text(
        "gauge,when,level,unit\nGAUGE-X,2026-10-12T09:00:00Z,0.9,m\n", encoding="utf-8"
    )
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps({"station_id": "gauge", "observed_at": "when", "water_level": "level"}),
        encoding="utf-8",
    )
    adapter = WaterDatasetAdapter(
        make_settings(water_dataset_path=str(path), water_mapping_path=str(mapping),
                      replay_fixtures_dir=str(samples_dir))
    )
    result = await adapter.fetch_events(_request())
    assert len(result.events) == 1
    assert result.events[0].payload["station_id"] == "GAUGE-X"


async def test_invalid_mapping_file_is_reported(tmp_path, samples_dir):
    mapping = tmp_path / "mapping.json"
    mapping.write_text("{not json", encoding="utf-8")
    adapter = WaterDatasetAdapter(
        make_settings(water_mapping_path=str(mapping), replay_fixtures_dir=str(samples_dir))
    )
    with pytest.raises(UpstreamUnavailableError):
        await adapter.fetch_events(_request())


async def test_station_without_coordinates_is_not_given_a_fake_pin(tmp_path, samples_dir):
    path = tmp_path / "nocood.csv"
    path.write_text(
        "station_id,observed_at,water_level,unit\n"
        "GAUGE-NC,2026-10-12T09:00:00Z,0.4,m\n",
        encoding="utf-8",
    )
    adapter = WaterDatasetAdapter(
        make_settings(water_dataset_path=str(path), replay_fixtures_dir=str(samples_dir))
    )
    result = await adapter.fetch_events(_request())
    event = result.events[0]
    assert event.location.latitude is None
    assert event.location.place_id == "GAUGE-NC"
    assert "location_missing" in [f.value for f in event.quality_flags]


def test_no_live_endpoint_is_claimed():
    adapter = WaterDatasetAdapter()
    assert adapter.supports_live is False
    assert any("no live water-level endpoint" in c.lower() for c in adapter.caveats)
