"""Stage A — validation and quality assessment.

Schema validity is kept separate from domain anomalies: a perfectly valid water-level reading can
still be anomalously high, and that is Stage C's job, not this one.

Outcomes:

* ``VALID`` — no issues.
* ``VALID_WITH_WARNINGS`` — processable, with recorded caveats (late, stale, approximate...).
* ``QUARANTINED`` — kept for review, not processed further (excessively old, future-dated,
  unknown unit, upstream-invalid).
* ``REJECTED`` — structurally invalid (cannot be a canonical event at all).

A late event is *not* invalid. Lateness is a warning; the original ``event_time`` is preserved.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from app.processing.config import ValidationPolicy
from app.processing.correlation import SENSOR_HEALTH_TYPES
from app.processing.quality import quality_score
from app.schemas.common import LocationPrecision, QualityStatus, SourceKind
from app.schemas.event import (
    NON_MEASUREMENT_TYPES,
    UNIT_ALIASES,
    CanonicalEvent,
    MeasurementAggregation,
)
from app.schemas.processing import ReasonCode, ValidationIssue, ValidationResult, ValidationVerdict

__all__ = ["validate_event", "validate_payload", "KNOWN_UNITS"]

#: Canonical unit spellings plus dimensionless units used by adapters.
KNOWN_UNITS: frozenset[str] = frozenset(UNIT_ALIASES.values()) | {"ratio", "count", "deg", "km"}


def _verdict(issues: list[ValidationIssue]) -> ValidationVerdict:
    severities = {i.severity for i in issues}
    if "reject" in severities:
        return ValidationVerdict.REJECTED
    if "quarantine" in severities:
        return ValidationVerdict.QUARANTINED
    if issues:
        return ValidationVerdict.VALID_WITH_WARNINGS
    return ValidationVerdict.VALID


def validate_event(
    event: CanonicalEvent,
    policy: ValidationPolicy,
    *,
    now: datetime,
    source_reliability: float = 1.0,
) -> ValidationResult:
    """Validate an already-constructed canonical event against processing policies."""
    issues: list[ValidationIssue] = []

    def add(code: ReasonCode, severity: str, message: str, field: str | None = None) -> None:
        issues.append(ValidationIssue(code=code, severity=severity, message=message, field=field))

    if event.schema_version not in policy.supported_schema_versions:
        add(ReasonCode.UNSUPPORTED_SCHEMA_VERSION, "quarantine",
            f"schema_version {event.schema_version!r} is not supported by this processing "
            f"version (supported: {policy.supported_schema_versions})", "schema_version")

    if event.event_time.tzinfo is None or event.ingest_time.tzinfo is None:
        add(ReasonCode.NAIVE_TIMESTAMP, "reject", "timestamps must be timezone-aware", "event_time")
        return _result(issues, False, source_reliability)

    if event.source_event_id is not None and not event.source_event_id.strip():
        add(ReasonCode.INCONSISTENT_IDENTIFIER, "quarantine",
            "source_event_id is present but blank", "source_event_id")

    # --- time policies -----------------------------------------------------------------
    age = (now - event.event_time).total_seconds()
    if -age > policy.future_tolerance_seconds:
        add(ReasonCode.FUTURE_TIMESTAMP, "quarantine",
            f"event_time is {-age:.0f}s in the future (tolerance "
            f"{policy.future_tolerance_seconds}s)", "event_time")
    elif age > policy.max_age_seconds:
        add(ReasonCode.EXCESSIVELY_OLD, "quarantine",
            f"event_time is {age / 86400:.1f} days old (max {policy.max_age_seconds / 86400:.0f} "
            "days); likely a clock or replay error", "event_time")
    elif age > policy.stale_after_seconds:
        add(ReasonCode.STALE_OBSERVATION, "warning",
            f"observation is {age / 3600:.1f} h old; processed but down-weighted", "event_time")

    delay = (event.ingest_time - event.event_time).total_seconds()
    is_late = delay > policy.late_after_seconds
    if is_late:
        add(ReasonCode.LATE_ARRIVAL, "warning",
            f"arrived {delay:.0f}s after it was observed; original event_time preserved",
            "ingest_time")

    # --- location ------------------------------------------------------------------------
    loc = event.location
    needs_location = any(event.event_type.value.startswith(p)
                         for p in policy.location_required_prefixes)
    if loc is not None and loc.has_coordinates:
        if not (-90 <= loc.latitude <= 90 and -180 <= loc.longitude <= 180):  # type: ignore[operator]
            add(ReasonCode.INVALID_COORDINATES, "reject", "coordinates out of range", "location")
        elif loc.precision == LocationPrecision.APPROXIMATE:
            add(ReasonCode.LOCATION_APPROXIMATE, "warning",
                "location is approximate; spatial matching will not treat it as precise",
                "location.precision")
    elif loc is not None and loc.area_reference:
        add(ReasonCode.LOCATION_MISSING, "warning",
            f"no coordinates; area reference {loc.area_reference!r} only", "location")
    elif needs_location:
        add(ReasonCode.LOCATION_MISSING, "warning",
            "no coordinates or area reference; spatial matching is not possible", "location")

    # --- measurements -------------------------------------------------------------------
    if event.event_type not in NON_MEASUREMENT_TYPES and event.event_type not in SENSOR_HEALTH_TYPES:
        if not event.measurements:
            add(ReasonCode.MISSING_MEASUREMENT, "warning",
                "event type implies a reading but none is present (not treated as zero)",
                "measurements")
    for m in event.measurements:
        if not math.isfinite(m.value):
            add(ReasonCode.NON_FINITE_VALUE, "reject", f"{m.name} is not finite",
                f"measurements.{m.name}")
        if m.unit not in KNOWN_UNITS:
            add(ReasonCode.UNKNOWN_UNIT, "quarantine",
                f"{m.name} has unsupported unit {m.unit!r}", f"measurements.{m.name}.unit")
        if m.aggregation in (MeasurementAggregation.ACCUMULATION,
                             MeasurementAggregation.AVERAGE) and not m.period_seconds:
            add(ReasonCode.MISSING_PERIOD, "warning",
                f"{m.name} is an {m.aggregation.value} without a period", f"measurements.{m.name}")

    # --- upstream verdict ---------------------------------------------------------------
    if event.quality_status == QualityStatus.INVALID:
        add(ReasonCode.UPSTREAM_INVALID, "quarantine", "ingestion marked this event invalid",
            "quality_status")
    elif event.quality_status == QualityStatus.SUSPECT:
        add(ReasonCode.UPSTREAM_SUSPECT, "warning", "ingestion marked this event suspect",
            "quality_status")

    if event.source_kind == SourceKind.SYNTHETIC:
        # Informational: recorded so no downstream summary mistakes replay data for live data.
        issues.append(ValidationIssue(code=ReasonCode.SYNTHETIC_DATA, severity="info",
                                      message="synthetic/replay data; not a live observation"))

    return _result(issues, is_late, source_reliability)


def _result(issues: list[ValidationIssue], is_late: bool, reliability: float) -> ValidationResult:
    counted = [i for i in issues if i.severity != "info"]
    return ValidationResult(
        verdict=_verdict(counted),
        issues=issues,
        quality_score=quality_score(counted, source_reliability=reliability),
        is_late=is_late,
    )


_PYDANTIC_CODE_MAP = {
    "missing": ReasonCode.MISSING_REQUIRED_FIELD,
    "datetime_parsing": ReasonCode.MALFORMED_TIMESTAMP,
    "datetime_from_date_parsing": ReasonCode.MALFORMED_TIMESTAMP,
    "datetime_type": ReasonCode.MALFORMED_TIMESTAMP,
    "enum": ReasonCode.UNKNOWN_EVENT_TYPE,
    "greater_than_equal": ReasonCode.INVALID_COORDINATES,
    "less_than_equal": ReasonCode.INVALID_COORDINATES,
    "finite_number": ReasonCode.NON_FINITE_VALUE,
}


def validate_payload(
    payload: dict[str, Any], policy: ValidationPolicy, *, now: datetime
) -> tuple[CanonicalEvent | None, ValidationResult]:
    """Validate a raw mapping (e.g. a quarantined record) and map errors to reason codes."""
    try:
        event = CanonicalEvent.model_validate(payload)
    except PydanticValidationError as exc:
        issues = []
        for err in exc.errors():
            field = ".".join(str(p) for p in err.get("loc", ()))
            msg = str(err.get("msg", ""))
            code = _PYDANTIC_CODE_MAP.get(err.get("type", ""), ReasonCode.INVALID_FIELD)
            if "timezone" in msg:
                code = ReasonCode.NAIVE_TIMESTAMP
            elif "schema_version" in field:
                code = ReasonCode.UNSUPPORTED_SCHEMA_VERSION
            elif field.startswith("location") and code == ReasonCode.INVALID_FIELD:
                code = ReasonCode.INVALID_COORDINATES
            elif "finite" in msg:
                code = ReasonCode.NON_FINITE_VALUE
            issues.append(ValidationIssue(code=code, severity="reject", field=field, message=msg))
        return None, ValidationResult(verdict=ValidationVerdict.REJECTED, issues=issues,
                                      quality_score=0.0)
    return event, validate_event(event, policy, now=now)
