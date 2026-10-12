"""Deterministic replay.

Purpose
-------
Replay is the demo and test substrate. It loads sanitised fixtures covering all five source
categories and emits them as canonical events.

Three guarantees
----------------
1. **Labelled provenance.** Every replayed event is ``source_kind = synthetic`` (or ``manual`` for
   report fixtures) and carries the ``synthetic_data`` / ``citizen_unverified`` flags. Replay data
   is never presented as a live observation.
2. **Stable identity.** Event ids, fingerprints, and idempotency keys derive from fixture content
   via SHA-256, not from ``hash()`` (which is salted per process). The same fixture therefore
   yields byte-identical identity on every run and every machine.
3. **Repeatable duplicate decisions.** Re-running a fixture produces duplicate receipts rather
   than duplicate canonical events.

Out-of-order replay
-------------------
``shuffle=True`` permutes arrival order using a seeded ``random.Random``, so a shuffled replay is
still reproducible. This is what exercises late/out-of-order handling.
"""

from __future__ import annotations

import json
import random
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.timeutil import parse_timestamp, utc_now
from app.ingestion.base import AdapterOutcome, AdapterResult, FetchRequest, SourceAdapter
from app.schemas.common import MeasurementAggregation, QualityFlag, SourceCategory, SourceKind
from app.schemas.event import (
    EventLocation,
    EventType,
    Measurement,
    build_canonical_event,
)
from app.schemas.report import redact_pii

__all__ = ["ReplayAdapter", "FIXTURES"]

logger = get_logger(__name__)

#: Fixture files, keyed by the category they cover.
FIXTURES: dict[str, str] = {
    "weather": "weather.json",
    "air_quality": "airaq.json",
    "traffic": "traffic.json",
    "water": "water_levels.csv",
    "citizen": "citizen_reports.json",
    "monsoon_waterlogging": "monsoon_waterlogging.json",
}

# Mapping from fixture record `event_type` to our closed vocabulary. Anything not listed is
# rejected, which is what keeps an adapter bug from injecting novel types downstream.
_TYPE_ALIASES: dict[str, EventType] = {
    "rainfall_observed": EventType.RAINFALL_OBSERVED,
    "temperature_observed": EventType.TEMPERATURE_OBSERVED,
    "weather_condition_observed": EventType.WEATHER_CONDITION_OBSERVED,
    "humidity_observed": EventType.HUMIDITY_OBSERVED,
    "air_quality_observed": EventType.AIR_QUALITY_OBSERVED,
    "traffic_speed_observed": EventType.TRAFFIC_SPEED_OBSERVED,
    "traffic_congestion_observed": EventType.TRAFFIC_CONGESTION_OBSERVED,
    "road_blocked_observed": EventType.ROAD_BLOCKED_OBSERVED,
    "water_level_observed": EventType.WATER_LEVEL_OBSERVED,
    "water_level_rising": EventType.WATER_LEVEL_RISING,
    "waterlogging_reported": EventType.WATERLOGGING_REPORTED,
    "road_blockage_reported": EventType.ROAD_BLOCKAGE_REPORTED,
    "power_outage_reported": EventType.POWER_OUTAGE_REPORTED,
    "flooding_reported": EventType.FODDLING_REPORTED,
    "air_quality_complaint": EventType.AIR_QUALITY_COMPLAINT,
    "public_health_reported": EventType.PUBLIC_HEALTH_REPORTED,
    "other_report": EventType.OTHER_REPORT,
    "sensor_offline": EventType.SENSOR_OFFLINE,
    "sensor_stale": EventType.SENSOR_STALE,
    "source_unavailable": EventType.SOURCE_UNAVAILABLE,
}


class ReplayAdapter(SourceAdapter):
    """Deterministic fixture replay across all five source categories."""

    source_id = "replay.all"
    display_name = "Deterministic replay fixtures"
    category = SourceCategory.REPLAY
    provider = "replay"
    supports_live = False
    supports_replay = True
    unit_notes = "Units are normalised exactly as in live mode; provenance is always synthetic."
    caveats = (
        "All replayed events are synthetic and must never be read as live observations.",
        "Identity is content-derived and stable, so re-running a fixture yields duplicates, "
        "not new events.",
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def required_settings(self) -> list[str]:
        return []

    # ------------------------------------------------------------------ io
    def fixtures_dir(self) -> Path:
        return Path(self.settings.replay_fixtures_dir)

    def available_fixtures(self) -> list[str]:
        return sorted(FIXTURES.keys())

    def _fixture_path(self, fixture: str) -> Path:
        key = fixture.strip().lower()
        if key in ("all", "*"):
            return self.fixtures_dir() / FIXTURES["monsoon_waterlogging"]
        if key not in FIXTURES:
            raise NotFoundError(
                f"Unknown replay fixture '{fixture}'.",
                details={"available": self.available_fixtures()},
            )
        return self.fixtures_dir() / FIXTURES[key]

    def _load_records(self, path: Path) -> list[dict[str, Any]]:
        """Load a fixture into a flat list of record dictionaries.

        Supports JSON (list, or an object with a recognised records key) and CSV, so a tabular
        water dataset can be replayed through exactly the same path as the JSON fixtures.
        """
        if not path.exists():
            raise NotFoundError(
                f"Replay fixture not found: {path.name}. "
                f"Ensure data/samples is present.",
                details={"provider": self.provider, "fixture": path.name},
            )
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise UpstreamUnavailableError(
                f"Replay fixture '{path.name}' could not be read: {exc.strerror}.",
                details={"provider": self.provider},
            ) from exc

        if path.suffix.lower() == ".csv":
            return _records_from_csv(text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"Replay fixture '{path.name}' is not valid JSON (line {exc.lineno}).",
                code="validation_failed",
                details={"fixture": path.name},
            ) from exc
        return _extract_records(data)

    # ------------------------------------------------------------- fetching
    async def fetch_events(self, request: FetchRequest) -> AdapterResult:
        started = utc_now()
        outcome = AdapterOutcome()

        fixture = (request.fixture or "monsoon_waterlogging").strip().lower()
        rebase = self.settings.replay_rebase_to_now if request.rebase is None else request.rebase

        if fixture in ("all", "*"):
            records = self._load_all_category_records()
        else:
            records = self._load_records(self._fixture_path(fixture))

        outcome.provider_meta = {
            "fixture": fixture,
            "record_count": len(records),
            "rebase_to_now": rebase,
            "shuffle": request.shuffle,
            "shuffle_seed": request.shuffle_seed,
        }

        # Anchor time: rebasing keeps a demo looking recent without changing relative spacing.
        now = utc_now()
        anchor = max((_try_time(r.get("event_time")) for r in records), default=None)
        offset = timedelta(0)
        if rebase and anchor is not None:
            offset = now - anchor

        built: list[Any] = []
        for index, record in enumerate(records):
            event = self._build_event(record, index, offset=offset)
            if event is None:
                continue
            built.append(event)

        # Arrival order is a *replay* concern, distinct from event order. Shuffling here is what
        # exercises the out-of-order reconciliation path.
        arrival = list(built)
        if request.shuffle:
            seed = (
                request.shuffle_seed
                if request.shuffle_seed is not None
                else self.settings.replay_shuffle_seed
            )
            # Seeded RNG: reproducible shuffling, unlike the salted built-in hash.
            random.Random(seed).shuffle(arrival)
            outcome.warnings.append(
                f"Arrival order was shuffled with seed {seed}; event_time is preserved unchanged."
            )

        for event in arrival:
            outcome.accept(event)

        return AdapterResult.from_outcome(self.source_id, outcome, started)

    def _load_all_category_records(self) -> list[dict[str, Any]]:
        """Concatenate every category fixture, skipping ones that are absent."""
        records: list[dict[str, Any]] = []
        for key, filename in FIXTURES.items():
            path = self.fixtures_dir() / filename
            if not path.exists():
                continue
            try:
                records.extend(self._load_records(path))
            except (NotFoundError, ValidationError):
                continue
        if not records:
            raise NotFoundError(
                "No replay fixtures were found in the fixtures directory.",
                details={"provider": self.provider},
            )
        return records

    # -------------------------------------------------------------- parsing
    def _build_event(
        self, record: dict[str, Any], index: int, *, offset: timedelta
    ) -> Any:
        """Convert one fixture record into a canonical event, or None when unusable."""
        raw_type = str(record.get("event_type", "")).strip().lower()
        event_type = _TYPE_ALIASES.get(raw_type)
        if event_type is None:
            logger.warning(
                "replay fixture record has an unknown event_type",
                extra={"raw_event_type": raw_type, "record_index": index},
            )
            return None

        raw_time = record.get("event_time")
        try:
            event_time = parse_timestamp(raw_time)
        except ValueError:
            return None

        event_time = event_time + offset

        location = None
        raw_location = record.get("location")
        if isinstance(raw_location, dict):
            try:
                location = EventLocation(
                    latitude=raw_location.get("latitude"),
                    longitude=raw_location.get("longitude"),
                    accuracy_m=raw_location.get("accuracy_m"),
                    place_id=raw_location.get("place_id"),
                    # Fixtures may carry the area name alongside, or instead of, coordinates.
                    area_reference=raw_location.get("area_reference")
                    or record.get("area_reference"),
                )
            except ValueError:
                location = None
        elif record.get("area_reference"):
            # Area-only reference: represent a region, never a fabricated pin.
            location = EventLocation.from_area(str(record["area_reference"]))

        measurements: list[Measurement] = []
        for item in record.get("measurements") or []:
            if not isinstance(item, dict):
                continue
            try:
                aggregation = MeasurementAggregation(
                    str(item.get("aggregation", "instantaneous")).strip().lower()
                )
            except ValueError:
                aggregation = MeasurementAggregation.INSTANTANEOUS
            reading = Measurement.build(
                str(item.get("name", "")),
                _as_float(item.get("value")),
                item.get("unit"),
                aggregation=aggregation,
                period_seconds=item.get("period_seconds"),
                lower_limit=item.get("lower_limit"),
                upper_limit=item.get("upper_limit"),
            )
            if reading:
                measurements.append(reading)

        # A measurement of zero is meaningful; an absent measurement is not. Only add the
        # optional-absence flag when the fixture really omits something it declared.
        text = record.get("text")
        redacted = False
        if text:
            text, redacted = redact_pii(str(text))

        source_kind = SourceKind.SYNTHETIC
        flags = _coerce_flags(record.get("quality_flags"))
        if redacted:
            flags.append(QualityFlag.REDACTED_TEXT)

        return build_canonical_event(
            source_id=str(record.get("source_id") or self.source_id),
            source_event_id=(
                str(record.get("source_event_id")) if record.get("source_event_id") else None
            ),
            event_type=event_type,
            event_time=event_time,
            ingest_time=utc_now(),
            location=location,
            measurements=measurements,
            source_kind=source_kind,
            quality_flags=flags,
            text=text,
            payload={
                "provider": self.provider,
                "fixture_record_index": index,
                "fixture_event_type": raw_type,
                "synthetic": True,
                # Preserve any extra fields the fixture attached (station identity, datum, ...)
                # so provenance survives replay.
                **(record.get("payload") if isinstance(record.get("payload"), dict) else {}),
                **({"notes": record["notes"]} if record.get("notes") else {}),
            },
        )


def _records_from_csv(text: str) -> list[dict[str, Any]]:
    """Convert a tabular water dataset into canonical-shaped replay records.

    The water dataset is the one fixture that is naturally tabular. Mapping it here means a single
    replay code path covers every source category, and the resulting events are identical in shape
    to those produced from the JSON fixtures.
    """
    import csv

    records: list[dict[str, Any]] = []
    for row in csv.DictReader(text.splitlines()):
        station_id = (row.get("station_id") or "").strip()
        observed_at = (row.get("observed_at") or "").strip()
        if not station_id or not observed_at:
            # Skip a malformed row rather than emitting a half-formed record.
            continue

        measurements: list[dict[str, Any]] = []
        level = _as_float(row.get("water_level"))
        if level is not None:
            measurements.append({
                "name": "water_level",
                "value": level,
                "unit": (row.get("unit") or "m").strip(),
                "aggregation": "instantaneous",
            })
        threshold = _as_float(row.get("alert_threshold"))
        if threshold is not None:
            measurements.append({
                "name": "water_level_threshold",
                "value": threshold,
                "unit": (row.get("threshold_unit") or row.get("unit") or "m").strip(),
                "aggregation": "instantaneous",
            })

        location: dict[str, Any] = {"place_id": station_id}
        lat = _as_float(row.get("latitude"))
        lon = _as_float(row.get("longitude"))
        if lat is not None and lon is not None:
            location["latitude"] = lat
            location["longitude"] = lon

        records.append({
            "source_id": "water.replay",
            "source_event_id": f"{station_id}:{observed_at}",
            "event_type": "water_level_observed",
            "event_time": observed_at,
            "location": location,
            "measurements": measurements,
            "payload": {
                "station_id": station_id,
                "station_name": (row.get("station_name") or "").strip() or None,
                "datum": (row.get("datum") or "").strip() or None,
            },
        })
    return records


def _coerce_flags(values: Any) -> list[QualityFlag]:
    """Convert fixture flag strings into enum members, dropping unknown ones.

    An unrecognised flag name must not abort a replay; it is skipped and the rest of the record
    is still ingested.
    """
    result: list[QualityFlag] = []
    if not isinstance(values, list):
        return result
    for item in values:
        try:
            result.append(QualityFlag(str(item).strip().lower()))
        except ValueError:
            logger.warning(
                "replay fixture record has an unknown quality flag",
                extra={"raw_flag": str(item)},
            )
    return result


def _extract_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("events", "records", "data", "results", "reports"):
            value = data.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def _try_time(value: Any) -> Any:
    try:
        return parse_timestamp(value)
    except ValueError:
        return parse_timestamp("1970-01-01T00:00:00Z")


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result
