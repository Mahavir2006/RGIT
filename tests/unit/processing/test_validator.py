"""Stage A: validation outcomes and reason codes."""

from __future__ import annotations

from datetime import timedelta

from app.processing.config import ValidationPolicy
from app.processing.validator import validate_event, validate_payload
from app.schemas.processing import ReasonCode, ValidationVerdict
from tests.fixtures.processing.factory import T0, make_event, report, water

POLICY = ValidationPolicy()
NOW = T0 + timedelta(minutes=1)


def codes(result) -> set[ReasonCode]:
    return {i.code for i in result.issues}


def test_valid_event():
    r = validate_event(water("e1", 0.5), POLICY, now=NOW)
    assert r.verdict == ValidationVerdict.VALID
    assert r.issues == []
    assert r.quality_score == 1.0


def test_missing_required_fields_rejected_with_reason():
    payload = water("e1", 0.5).model_dump()
    del payload["event_type"], payload["idempotency_key"]
    event, r = validate_payload(payload, POLICY, now=NOW)
    assert event is None and r.verdict == ValidationVerdict.REJECTED
    assert ReasonCode.MISSING_REQUIRED_FIELD in codes(r)
    assert all(i.message for i in r.issues)


def test_invalid_coordinates_rejected():
    payload = water("e1", 0.5).model_dump()
    payload["location"]["latitude"] = 123.0
    _, r = validate_payload(payload, POLICY, now=NOW)
    assert r.verdict == ValidationVerdict.REJECTED
    assert ReasonCode.INVALID_COORDINATES in codes(r)


def test_naive_and_malformed_timestamps():
    payload = water("e1", 0.5).model_dump()
    payload["event_time"] = payload["event_time"].replace(tzinfo=None)
    _, r = validate_payload(payload, POLICY, now=NOW)
    assert ReasonCode.NAIVE_TIMESTAMP in codes(r)

    payload["event_time"] = "not-a-time"
    _, r = validate_payload(payload, POLICY, now=NOW)
    assert ReasonCode.MALFORMED_TIMESTAMP in codes(r)


def test_unknown_unit_is_quarantined_not_dropped():
    e = make_event("e1", measurements=[{"name": "water_level", "value": 2.0, "unit": "furlongs"}])
    r = validate_event(e, POLICY, now=NOW)
    assert r.verdict == ValidationVerdict.QUARANTINED
    assert ReasonCode.UNKNOWN_UNIT in codes(r)


def test_missing_location_where_permitted_is_a_warning():
    e = report("r1", "water on the road", lat=None, lon=None, area="Andheri East")
    r = validate_event(e, POLICY, now=NOW)
    assert r.verdict == ValidationVerdict.VALID_WITH_WARNINGS
    assert ReasonCode.LOCATION_MISSING in codes(r)


def test_late_but_valid_event_is_not_rejected():
    e = water("e1", 0.5, ingest_delay_s=3600)
    r = validate_event(e, POLICY, now=T0 + timedelta(hours=1))
    assert r.processable and r.is_late
    assert ReasonCode.LATE_ARRIVAL in codes(r)
    assert e.event_time == T0  # original observation time preserved


def test_unsupported_schema_version_quarantined():
    e = water("e1", 0.5)
    r = validate_event(e, ValidationPolicy(supported_schema_versions=["2.0"]), now=NOW)
    assert r.verdict == ValidationVerdict.QUARANTINED
    assert ReasonCode.UNSUPPORTED_SCHEMA_VERSION in codes(r)


def test_future_stale_and_excessively_old():
    e = water("e1", 0.5)
    assert ReasonCode.FUTURE_TIMESTAMP in codes(
        validate_event(e, POLICY, now=T0 - timedelta(hours=1)))
    stale = validate_event(e, POLICY, now=T0 + timedelta(hours=7))
    assert stale.verdict == ValidationVerdict.VALID_WITH_WARNINGS
    assert ReasonCode.STALE_OBSERVATION in codes(stale)
    old = validate_event(e, POLICY, now=T0 + timedelta(days=40))
    assert old.verdict == ValidationVerdict.QUARANTINED
    assert ReasonCode.EXCESSIVELY_OLD in codes(old)


def test_missing_measurement_is_not_zero():
    e = make_event("e1", measurements=[])
    r = validate_event(e, POLICY, now=NOW)
    assert ReasonCode.MISSING_MEASUREMENT in codes(r)
    assert r.processable
