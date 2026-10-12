"""Canonical event schema: valid construction and the validation guards."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.timeutil import parse_timestamp
from app.schemas.common import (
    LocationPrecision,
    MeasurementAggregation,
    QualityFlag,
    QualityStatus,
    SourceKind,
)
from app.schemas.event import (
    CanonicalEvent,
    CanonicalEventCreate,
    EventLocation,
    EventType,
    Measurement,
    build_canonical_event,
    compute_fingerprint,
    derive_idempotency_key,
)


# ------------------------------------------------------------------ valid path
def test_valid_event_round_trips():
    measurement = Measurement.build(
        "rainfall_1h", 28.4, "mm",
        aggregation=MeasurementAggregation.ACCUMULATION, period_seconds=3600,
    )
    event = build_canonical_event(
        source_id="weather.replay",
        source_event_id="wx-1",
        event_type=EventType.RAINFALL_OBSERVED,
        event_time=parse_timestamp("2026-10-12T08:30:00+05:30"),
        location=EventLocation(latitude=19.0760, longitude=72.8777, accuracy_m=50),
        measurements=[measurement],
        source_kind=SourceKind.SYNTHETIC,
    )
    assert event.event_id.startswith("evt_")
    assert event.idempotency_key
    assert event.fingerprint.startswith("fp_")
    assert event.schema_version == "1.0"
    assert event.event_time.tzinfo is not None
    # Event time is stored as UTC while preserving the instant.
    assert event.event_time == parse_timestamp("2026-10-12T03:00:00Z")


def test_event_time_and_ingest_time_are_independent():
    event = build_canonical_event(
        source_id="water.dataset",
        event_type=EventType.WATER_LEVEL_OBSERVED,
        event_time=parse_timestamp("2026-10-12T09:30:00Z"),
        ingest_time=parse_timestamp("2026-10-12T09:45:00Z"),
        location=EventLocation(latitude=19.07, longitude=72.87),
        measurements=[Measurement.build("water_level", 1.24, "m")],
    )
    assert event.event_time != event.ingest_time
    assert (event.ingest_time - event.event_time).total_seconds() == 900


def test_measurement_preserves_original_value_and_unit():
    measurement = Measurement.build("water_level", 1.42, "ft")
    assert measurement.unit == "m"
    assert measurement.original_unit == "ft"
    assert measurement.original_value == 1.42
    assert measurement.converted is True
    assert measurement.value == pytest.approx(0.4328, abs=1e-3)


def test_synthetic_provenance_is_flagged():
    event = build_canonical_event(
        source_id="replay.all",
        event_type=EventType.OTHER_REPORT,
        event_time=parse_timestamp("2026-10-12T08:00:00Z"),
        source_kind=SourceKind.SYNTHETIC,
    )
    assert QualityFlag.SYNTHETIC_DATA in event.quality_flags


def test_missing_location_is_flagged_not_invented():
    event = build_canonical_event(
        source_id="citizen.manual",
        event_type=EventType.WATERLOGGING_REPORTED,
        event_time=parse_timestamp("2026-10-12T09:12:00Z"),
        location=EventLocation.from_area("Andheri East"),
        source_kind=SourceKind.MANUAL,
    )
    assert event.location is not None
    assert event.location.latitude is None
    assert QualityFlag.LOCATION_MISSING in event.quality_flags
    assert event.location.area_reference == "Andheri East"


# ------------------------------------------------------------- invalid inputs
@pytest.mark.parametrize("latitude,longitude", [(95.0, 0.0), (-95.0, 0.0), (0.0, 181.0)])
def test_invalid_coordinates_rejected(latitude, longitude):
    with pytest.raises(ValidationError):
        EventLocation(latitude=latitude, longitude=longitude)


def test_coordinates_must_be_supplied_in_pairs():
    with pytest.raises(ValidationError, match="supplied together"):
        EventLocation(latitude=19.07)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_measurements_rejected(value):
    with pytest.raises(ValidationError, match="finite"):
        Measurement(name="rainfall", value=value, unit="mm")


def test_accumulation_without_period_rejected():
    """A total with no window is meaningless and invites intensity misreading."""
    with pytest.raises(ValidationError, match="period_seconds"):
        Measurement.build("rainfall_1h", 28.4, "mm",
                          aggregation=MeasurementAggregation.ACCUMULATION)


def test_naive_timestamp_rejected_on_event():
    with pytest.raises(ValidationError, match="timezone-aware"):
        CanonicalEvent(
            event_id="evt_x", source_id="s", event_type=EventType.OTHER_REPORT,
            event_time=datetime(2026, 1, 1),  # naive
            ingest_time=parse_timestamp("2026-01-01T00:00:01Z"),
            source_kind=SourceKind.MANUAL, idempotency_key="k", fingerprint="f",
        )


def test_unsupported_schema_version_rejected():
    with pytest.raises(ValidationError, match="unsupported schema_version"):
        CanonicalEvent(
            event_id="evt_x", source_id="s", event_type=EventType.OTHER_REPORT,
            event_time=parse_timestamp("2026-01-01T00:00:00Z"),
            ingest_time=parse_timestamp("2026-01-01T00:00:01Z"),
            source_kind=SourceKind.MANUAL, idempotency_key="k", fingerprint="f",
            schema_version="9.9",
        )


def test_unknown_event_type_rejected():
    with pytest.raises(ValidationError):
        CanonicalEventCreate(
            source_id="s", event_type="not_a_real_type",
            event_time=parse_timestamp("2026-01-01T00:00:00Z"),
        )


def test_empty_measurement_set_marks_measurement_bearing_event_suspect():
    event = build_canonical_event(
        source_id="water.dataset",
        event_type=EventType.WATER_LEVEL_OBSERVED,
        event_time=parse_timestamp("2026-10-12T08:00:00Z"),
        location=EventLocation(latitude=19.07, longitude=72.87),
        measurements=[],
    )
    assert event.quality_status == QualityStatus.SUSPECT


def test_zero_measurement_is_preserved_not_treated_as_missing():
    """Zero is a real reading; it must never be conflated with absence."""
    event = build_canonical_event(
        source_id="water.dataset",
        event_type=EventType.WATER_LEVEL_OBSERVED,
        event_time=parse_timestamp("2026-10-12T08:00:00Z"),
        location=EventLocation(latitude=19.07, longitude=72.87),
        measurements=[Measurement.build("water_level", 0.0, "m")],
    )
    assert event.measurements[0].value == 0.0
    assert event.quality_status == QualityStatus.VALID


# -------------------------------------------------------------------- identity
def test_fingerprint_is_deterministic_across_calls():
    location = EventLocation(latitude=19.0760, longitude=72.8777)
    measurement = Measurement.build("water_level", 1.24, "m")
    args = dict(
        source_id="water.dataset", event_type=EventType.WATER_LEVEL_OBSERVED,
        event_time=parse_timestamp("2026-10-12T09:30:00Z"), location=location,
        measurements=[measurement],
    )
    assert compute_fingerprint(**args) == compute_fingerprint(**args)


def test_measurement_order_does_not_change_fingerprint():
    location = EventLocation(latitude=19.07, longitude=72.87)
    a = Measurement.build("water_level", 1.24, "m")
    b = Measurement.build("temperature", 26.5, "c")
    args = dict(
        source_id="s", event_type=EventType.WATER_LEVEL_OBSERVED,
        event_time=parse_timestamp("2026-10-12T09:30:00Z"), location=location,
    )
    assert compute_fingerprint(**args, measurements=[a, b]) == \
        compute_fingerprint(**args, measurements=[b, a])


def test_idempotency_key_precedence_prefers_source_event_id():
    key = derive_idempotency_key(
        source_id="s", source_event_id="provider-1", explicit_key="client-1",
        fingerprint="fp_abc",
    )
    assert key.startswith("idk_seid_")


def test_idempotency_key_falls_back_to_fingerprint():
    key = derive_idempotency_key(
        source_id="s", source_event_id=None, explicit_key=None, fingerprint="fp_abc"
    )
    assert key == "idk_fp_abc"


def test_source_event_ids_are_scoped_by_source():
    a = derive_idempotency_key(source_id="s1", source_event_id="x", explicit_key=None,
                               fingerprint="fp_1")
    b = derive_idempotency_key(source_id="s2", source_event_id="x", explicit_key=None,
                               fingerprint="fp_2")
    assert a != b


# -------------------------------------------------------------- inbound create
def test_canonical_event_create_derives_identity():
    create = CanonicalEventCreate(
        source_id="weather.manual",
        source_event_id="abc",
        event_type=EventType.RAINFALL_OBSERVED,
        event_time="2026-10-12T08:30:00Z",
        location=EventLocation(latitude=19.07, longitude=72.87),
        measurements=[Measurement.build("rainfall_1h", 10.0, "mm",
                                        aggregation=MeasurementAggregation.ACCUMULATION,
                                        period_seconds=3600)],
    )
    event = create.to_canonical()
    assert event.event_id and event.idempotency_key and event.fingerprint
    assert event.ingest_time.tzinfo is not None


def test_naive_inbound_timestamp_is_accepted_but_flagged():
    create = CanonicalEventCreate(
        source_id="weather.manual",
        event_type=EventType.RAINFALL_OBSERVED,
        event_time="2026-10-12T08:30:00",
        location=EventLocation(latitude=19.07, longitude=72.87),
        measurements=[Measurement.build("rainfall_1h", 10.0, "mm",
                                        aggregation=MeasurementAggregation.ACCUMULATION,
                                        period_seconds=3600)],
    )
    event = create.to_canonical()
    assert QualityFlag.NAIVE_TIMESTAMP_ASSUMED_UTC in event.quality_flags
    # Interpreted as UTC, not as server-local time.
    assert event.event_time == datetime(2026, 10, 12, 8, 30, tzinfo=timezone.utc)


def test_unparseable_inbound_timestamp_rejected():
    with pytest.raises(ValueError):
        CanonicalEventCreate(
            source_id="s", event_type=EventType.OTHER_REPORT,
            event_time="the day before yesterday",
        )


# ------------------------------------------------------------- unit conversion
@pytest.mark.parametrize(
    "name,value,unit,expected_unit,expected_value,expected_original_unit",
    [
        ("water_level", 1.42, "ft", "m", 0.4328, "ft"),
        ("water_level", 150.0, "cm", "m", 1.5, "cm"),
        ("rainfall", 25.4, "in", "mm", 645.16, "in"),
        ("speed", 10.0, "m/s", "km/h", 36.0, "m/s"),
        # Unit *spelling* is normalised ("F" -> "f"); the original *value* is preserved exactly.
        ("temperature", 32.0, "F", "c", 0.0, "f"),
        ("temperature", 300.0, "K", "c", 26.85, "k"),
    ],
)
def test_unit_conversion_is_correct(
    name, value, unit, expected_unit, expected_value, expected_original_unit
):
    measurement = Measurement.build(name, value, unit)
    assert measurement.unit == expected_unit
    assert measurement.value == pytest.approx(expected_value, abs=0.01)
    assert measurement.original_unit == expected_original_unit
    assert measurement.original_value == value
    assert measurement.converted is True
