"""Stage C: anomaly rules and robust baselines (pure functions)."""

from __future__ import annotations

from datetime import timedelta

from app.processing.anomaly import (
    AnomalyContext,
    Reading,
    detect_anomalies,
    detect_stale_source,
)
from app.processing.baselines import robust_baseline
from app.processing.config import ProcessingConfig
from app.schemas.anomaly import AnomalyKind, AnomalyType
from tests.fixtures.processing.factory import LAT, LON, T0, make_event, rain, traffic, water

CFG = ProcessingConfig()


def types(findings) -> set[AnomalyType]:
    return {f.anomaly_type for f in findings}


def history(values, *, step_min=10, unit="m", anomalous=()):
    return [Reading(event_id=f"h{i}", event_time=T0 - timedelta(minutes=step_min * (len(values) - i)),
                    value=v, unit=unit, was_anomalous=i in anomalous) for i, v in enumerate(values)]


def test_normal_measurement_has_no_anomaly():
    assert detect_anomalies(water("e", 0.4), AnomalyContext(), CFG) == []


def test_threshold_exceeded_is_explained_with_unit_and_rule():
    [f] = [f for f in detect_anomalies(rain("r", 32.0), AnomalyContext(), CFG)]
    assert f.anomaly_type == AnomalyType.THRESHOLD_EXCEEDED and f.severity.value == "HIGH"
    assert f.rule_id == "rainfall_1h_high" and f.unit == "mm" and f.threshold == 30.0
    assert "32 mm >= 30 mm" in f.explanation


def test_station_threshold_from_dataset_overrides_default():
    e = make_event("e", measurements=[{"name": "water_level", "value": 0.62, "unit": "m"},
                                      {"name": "water_level_threshold", "value": 0.6, "unit": "m"}])
    [f] = detect_anomalies(e, AnomalyContext(), CFG)
    assert f.threshold == 0.6 and "station threshold" in f.explanation


def test_threshold_needs_matching_period_and_unit():
    six_hour = make_event("e", event_type="rainfall_observed", source_id="weather.live",
                          place_id=None, measurements=[{
                              "name": "rainfall_1h", "value": 90.0, "unit": "mm",
                              "aggregation": "accumulation", "period_seconds": 21600}])
    assert detect_anomalies(six_hour, AnomalyContext(), CFG) == []


def test_missing_measurement_produces_nothing():
    assert detect_anomalies(make_event("e", measurements=[]), AnomalyContext(), CFG) == []


def test_robust_baseline_anomaly():
    vals = [0.40, 0.42, 0.41, 0.43, 0.39, 0.40, 0.42, 0.41, 0.40, 0.43, 0.41, 0.42]
    ctx = AnomalyContext(history={"water_level": history(vals, step_min=120)})
    fs = [f for f in detect_anomalies(water("e", 0.70), ctx, CFG)
          if f.anomaly_type == AnomalyType.BASELINE_DEVIATION]
    assert len(fs) == 1
    f = fs[0]
    assert f.score and f.score > 6 and f.sample_count == 12 and f.baseline_window_hours == 72
    assert f.expected_range["median"] == 0.41


def test_zero_mad_and_insufficient_history_never_produce_a_z_score():
    flat = robust_baseline(5.0, [(1.0, False)] * 20, min_samples=12)
    assert not flat.usable and flat.reason == "ZERO_MAD" and flat.robust_z is None
    few = robust_baseline(5.0, [(1.0, False), (2.0, False)], min_samples=12)
    assert not few.usable and few.reason == "INSUFFICIENT_HISTORY"


def test_baseline_excludes_previously_anomalous_samples():
    hist = [(1.0, False)] * 6 + [(9.0, True)] * 6 + [(1.1, False), (0.9, False)] * 3
    stats = robust_baseline(1.0, hist, min_samples=12)
    assert stats.excluded == 6 and stats.median == 1.0


def test_rate_of_change_records_previous_current_elapsed_and_rate():
    ctx = AnomalyContext(history={"water_level": history([0.50], step_min=20)})
    [f] = [f for f in detect_anomalies(water("e", 0.80), ctx, CFG)
           if f.anomaly_type == AnomalyType.RAPID_CHANGE]
    assert f.details["previous_value"] == 0.5 and f.details["current_value"] == 0.8
    assert f.details["elapsed_seconds"] == 1200 and round(f.details["rate_per_hour"], 3) == 0.9
    assert f.kind == AnomalyKind.ENVIRONMENTAL


def test_rate_of_change_never_mixes_units():
    ctx = AnomalyContext(history={"water_level": history([50.0], step_min=20, unit="cm")})
    assert AnomalyType.RAPID_CHANGE not in types(detect_anomalies(water("e", 0.8), ctx, CFG))


def test_implausible_jump_is_sensor_health_not_environmental():
    ctx = AnomalyContext(history={"water_level": history([0.5], step_min=2)})
    fs = detect_anomalies(water("e", 3.0), ctx, CFG)
    jump = [f for f in fs if f.anomaly_type == AnomalyType.IMPLAUSIBLE_JUMP]
    assert jump and jump[0].kind == AnomalyKind.SENSOR_HEALTH
    assert AnomalyType.RAPID_CHANGE not in types(fs)


def test_traffic_speed_deterioration():
    ctx = AnomalyContext(history={"speed": history([45.0], step_min=15, unit="km/h")})
    fs = detect_anomalies(traffic("t", 0.25, speed=15.0), ctx, CFG)
    assert {AnomalyType.RAPID_CHANGE, AnomalyType.THRESHOLD_EXCEEDED} <= types(fs)


def test_flatlined_sensor():
    ctx = AnomalyContext(history={"water_level": history([0.5] * 5, step_min=20)})
    fs = detect_anomalies(water("e", 0.5), ctx, CFG)
    [flat] = [f for f in fs if f.anomaly_type == AnomalyType.FLATLINE]
    assert flat.kind == AnomalyKind.SENSOR_HEALTH


def test_stale_source_is_observability_only():
    f = detect_stale_source("water.dataset", T0, T0 + timedelta(hours=2), 900)
    assert f and f.anomaly_type == AnomalyType.STALE_SOURCE and f.kind == AnomalyKind.SENSOR_HEALTH
    assert "not evidence" in f.explanation
    assert detect_stale_source("water.dataset", None, T0, 900) is None  # never seen: unknown
    assert detect_stale_source("water.dataset", T0, T0 + timedelta(minutes=5), 900) is None


def test_contradictory_nearby_sensors():
    peer = Reading(event_id="p", event_time=T0, value=0.1, unit="m", latitude=LAT + 0.002,
                   longitude=LON, subject="place:WGD-05")
    ctx = AnomalyContext(neighbours={"water_level": [peer]})
    [c] = [f for f in detect_anomalies(water("e", 1.2), ctx, CFG)
           if f.anomaly_type == AnomalyType.SENSOR_CONFLICT]
    assert c.kind == AnomalyKind.SENSOR_HEALTH and c.details["neighbour_event_ids"] == ["p"]


def test_detection_is_deterministic():
    ctx = AnomalyContext(history={"water_level": history([0.5], step_min=20)})
    a = [f.model_dump() for f in detect_anomalies(water("e", 1.3), ctx, CFG)]
    b = [f.model_dump() for f in detect_anomalies(water("e", 1.3), ctx, CFG)]
    assert a == b and a
