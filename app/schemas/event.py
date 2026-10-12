"""The canonical event contract, version 1.0.

Every source — weather, air quality, traffic, water, citizen reports, replay fixtures — is
normalised into exactly this envelope. Adapters build these objects; they never touch the
database. The persistence layer stores them verbatim.

Versioning
----------
``schema_version`` is part of the record and is validated on ingress. An unsupported version is
rejected explicitly rather than being coerced, so a future migration is a deliberate act.

Invariants enforced here
------------------------
* ``event_time`` and ``ingest_time`` are always distinct, timezone-aware, and stored in UTC.
* Measurements keep their original value and unit; any conversion is explicit and recorded.
* Accumulation-style measurements must declare a period, so rainfall totals are never rendered
  as instantaneous intensity.
* ``location`` may be absent, but only for event types that permit it, and then the absence is
  recorded rather than being papered over with a false pin.
* Missing values are never coerced to zero.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.errors import ErrorDetail, ValidationError
from app.core.timeutil import ensure_aware, parse_timestamp, utc_now
from app.schemas.common import (
    LocationPrecision,
    MeasurementAggregation,
    QualityFlag,
    QualityStatus,
    SourceKind,
)

__all__ = [
    "SCHEMA_VERSION",
    "EventType",
    "Measurement",
    "EventLocation",
    "CanonicalEvent",
    "CanonicalEventCreate",
    "SUPPORTED_SCHEMA_VERSIONS",
    "compute_fingerprint",
    "derive_idempotency_key",
    "derive_event_id",
    "build_canonical_event",
    "new_event_id",
]

SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS = {"1.0"}


class EventType(str, Enum):
    """Closed event-type vocabulary.

    A closed set keeps downstream scoring stable: Milestone 2's candidate matcher can rely on
    type compatibility without encountering novel values from an adapter bug.
    """

    # --- weather
    RAINFALL_OBSERVED = "rainfall_observed"
    TEMPERATURE_OBSERVED = "temperature_observed"
    WEATHER_CONDITION_OBSERVED = "weather_condition_observed"
    HUMIDITY_OBSERVED = "humidity_observed"
    WIND_OBSERVED = "wind_observed"

    # --- air quality
    AIR_QUALITY_OBSERVED = "air_quality_observed"

    # --- traffic
    TRAFFIC_SPEED_OBSERVED = "traffic_speed_observed"
    TRAFFIC_CONGESTION_OBSERVED = "traffic_congestion_observed"
    TRAFFIC_TRAVEL_TIME_OBSERVED = "traffic_travel_time_observed"
    ROAD_BLOCKED_OBSERVED = "road_blocked_observed"

    # --- water
    WATER_LEVEL_OBSERVED = "water_level_observed"
    WATER_LEVEL_RISING = "water_level_rising"

    # --- citizen reports
    WATERLOGGING_REPORTED = "waterlogging_reported"
    ROAD_BLOCKAGE_REPORTED = "road_blockage_reported"
    POWER_OUTAGE_REPORTED = "power_outage_reported"
    FODDLING_REPORTED = "flooding_reported"
    AIR_QUALITY_COMPLAINT = "air_quality_complaint"
    PUBLIC_HEALTH_REPORTED = "public_health_reported"
    OTHER_REPORT = "other_report"

    # --- system / health (mostly produced by adapters)
    SENSOR_OFFLINE = "sensor_offline"
    SENSOR_STALE = "sensor_stale"
    SOURCE_UNAVAILABLE = "source_unavailable"


# Event types for which a location is mandatory. A location-less event of another type is
# accepted but flagged, because a provider may legitimately omit coordinates.
LOCATION_REQUIRED_TYPES: frozenset[EventType] = frozenset({
    EventType.RAINFALL_OBSERVED,
    EventType.AIR_QUALITY_OBSERVED,
    EventType.TRAFFIC_SPEED_OBSERVED,
    EventType.WATER_LEVEL_OBSERVED,
    EventType.WATER_LEVEL_RISING,
    EventType.TRAFFIC_CONGESTION_OBSERVED,
    EventType.ROAD_BLOCKED_OBSERVED,
})

# Event types that may legitimately arrive without coordinates.
LOCATION_OPTIONAL_TYPES: frozenset[EventType] = frozenset({
    EventType.SENSOR_OFFLINE,
    EventType.SOURCE_UNAVAILABLE,
    EventType.WEATHER_CONDITION_OBSERVED,
    EventType.POWER_OUTAGE_REPORTED,
    EventType.OTHER_REPORT,
})

# Event types that carry no numeric reading at all. For any other type, an event with zero
# measurements is treated as suspect rather than valid.
NON_MEASUREMENT_TYPES: frozenset[EventType] = frozenset({
    EventType.SENSOR_OFFLINE,
    EventType.SENSOR_STALE,
    EventType.SOURCE_UNAVAILABLE,
    EventType.WEATHER_CONDITION_OBSERVED,
    EventType.ROAD_BLOCKED_OBSERVED,
    EventType.ROAD_BLOCKAGE_REPORTED,
    EventType.WATERLOGGING_REPORTED,
    EventType.POWER_OUTAGE_REPORTED,
    EventType.FODDLING_REPORTED,
    EventType.AIR_QUALITY_COMPLAINT,
    EventType.PUBLIC_HEALTH_REPORTED,
    EventType.OTHER_REPORT,
})


def _dedupe(items: list[QualityFlag]) -> list[QualityFlag]:
    """Remove duplicate flags while preserving first-seen order."""
    seen: set[QualityFlag] = set()
    result: list[QualityFlag] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


# --------------------------------------------------------------------- units
# Canonical unit per measurement name, plus the conversions we are willing to perform.
# Conversion is only defined for the pairs listed here; anything else keeps the original unit
# and is flagged as unsupported rather than silently mangled.
UNIT_ALIASES: dict[str, str] = {
    # length
    "mm": "mm", "millimeter": "mm", "millimetre": "mm", "millimeters": "mm", "millimetres": "mm",
    "cm": "cm", "centimeter": "cm", "centimetre": "cm",
    "m": "m", "meter": "m", "metre": "m", "meters": "m", "metres": "m",
    "km": "km", "kilometer": "km", "kilometre": "km",
    "in": "in", "inch": "in", "inches": "in",
    "ft": "ft", "foot": "ft", "feet": "ft",
    # temperature (offset conversions handled separately)
    "c": "c", "°c": "c", "celsius": "c", "degc": "c", "deg_c": "c",
    "k": "k", "kelvin": "k",
    "f": "f", "°f": "f", "fahrenheit": "f", "degf": "f", "deg_f": "f",
    # speed
    "km/h": "km/h", "kmh": "km/h", "kph": "km/h", "km_h": "km/h", "kilometer_per_hour": "km/h",
    "mph": "mph", "mi/h": "mph",
    "m/s": "m/s", "ms-1": "m/s", "mps": "m/s", "meter_per_second": "m/s",
    "kn": "kn", "knot": "kn", "knots": "kn",
    # air quality / gas concentration
    "µg/m3": "ug/m3", "ug/m3": "ug/m3", "μg/m3": "ug/m3", "µg/m³": "ug/m3", "ug/m³": "ug/m3",
    "ppm": "ppm", "ppb": "ppb",
    "aqi": "aqi", "index": "index",
    # pressure / misc
    "hpa": "hPa", "mbar": "hPa", "millibar": "hPa", "hectopascal": "hPa", "hectopascals": "hPa",
    "pa": "Pa", "pascal": "Pa",
    "%": "%", "percent": "%", "pct": "%",
    "s": "s", "sec": "s", "second": "s", "seconds": "s",
    "min": "min", "minute": "min", "minutes": "min",
    "h": "h", "hr": "h", "hour": "h", "hours": "h",
    "d": "d", "day": "d", "days": "d",
}

# Multiplicative conversions into the canonical unit for a measurement family.
#
# Each entry is `(factor, unit)` read as: to express 1 <unit> in the canonical unit, multiply by
# <factor>. Equivalently, value_in_canonical = value_in_unit * factor.
_LINEAR_CONVERSIONS: dict[str, list[tuple[float, str]]] = {
    # key: canonical unit
    "mm": [(1.0, "mm"), (10.0, "cm"), (1000.0, "m"), (25.4, "in"), (304.8, "ft")],
    "cm": [(0.1, "mm"), (1.0, "cm"), (100.0, "m"), (2.54, "in"), (30.48, "ft")],
    "m": [(0.001, "mm"), (0.01, "cm"), (1.0, "m"), (0.0254, "in"), (0.3048, "ft")],
    "km/h": [(1.0, "km/h"), (1.609344, "mph"), (3.6, "m/s"), (1.852, "kn")],
    "mph": [(0.621371, "km/h"), (1.0, "mph"), (2.236936, "m/s"), (0.868976, "kn")],
    "m/s": [(0.277778, "km/h"), (0.44704, "mph"), (1.0, "m/s"), (1.943844, "kn")],
    "kn": [(0.539957, "km/h"), (1.150779, "mph"), (0.514444, "m/s"), (1.0, "kn")],
    "hPa": [(1.0, "hPa"), (100.0, "Pa")],
    "Pa": [(0.01, "hPa"), (1.0, "Pa")],
}

# Which canonical unit each measurement family prefers. Longer, more specific prefixes come
# first so that `wind_speed` resolves to the speed family rather than falling through.
CANONICAL_UNIT_FOR_PREFIX: dict[str, str] = {
    "rainfall": "mm",
    "snowfall": "mm",
    "water_level": "m",
    "wind_speed": "km/h",
    "speed": "km/h",
    "temperature": "c",
    "pressure": "hPa",
    "concentration": "ug/m3",
}

MEASUREMENT_NAME_PREFIXES = tuple(CANONICAL_UNIT_FOR_PREFIX.keys())


def normalize_unit(unit: str | None) -> str | None:
    """Map a provider's unit string onto the canonical spelling, or return None."""
    if unit is None:
        return None
    key = str(unit).strip()
    if not key:
        return None
    return UNIT_ALIASES.get(key, UNIT_ALIASES.get(key.lower(), key))


def canonical_unit_for(name: str) -> str | None:
    """Return the preferred canonical unit for a measurement name, if one is defined."""
    lowered = name.lower()
    for prefix in MEASUREMENT_NAME_PREFIXES:
        if lowered.startswith(prefix):
            return CANONICAL_UNIT_FOR_PREFIX[prefix]
    return None


def _convert_linear(value: float, from_unit: str, to_unit: str) -> float | None:
    """Convert between two units of the same family; return None when undefined."""
    for canonical, table in _LINEAR_CONVERSIONS.items():
        if to_unit != canonical:
            continue
        for factor, unit in table:
            if unit == from_unit:
                return value * factor
    return None


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float | None:
    """Convert temperature readings, including the affine Fahrenheit/Kelvin cases."""
    to_celsius: float | None = None
    if from_unit == "c":
        to_celsius = value
    elif from_unit == "f":
        to_celsius = (value - 32.0) * 5.0 / 9.0
    elif from_unit == "k":
        to_celsius = value - 273.15
    if to_celsius is None:
        return None
    if to_unit == "c":
        return to_celsius
    if to_unit == "f":
        return to_celsius * 9.0 / 5.0 + 32.0
    if to_unit == "k":
        return to_celsius + 273.15
    return None


def convert_measurement_value(name: str, value: float, from_unit: str | None,
                              to_unit: str | None) -> float | None:
    """Convert a measurement value to the preferred canonical unit, or return None."""
    if to_unit is None or from_unit is None or from_unit == to_unit:
        return value if to_unit is not None else None
    if name.lower().startswith("temperature"):
        return _convert_temperature(value, from_unit, to_unit)
    return _convert_linear(value, from_unit, to_unit)


# --------------------------------------------------------------------- models
class Measurement(BaseModel):
    """A single typed reading.

    ``original_value``/``original_unit`` are always retained so that a later analyst can
    reproduce what the provider actually reported. ``converted`` records whether the canonical
    ``value`` differs from the original.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    value: float
    unit: str = Field(min_length=1, max_length=24)
    original_value: float | None = None
    original_unit: str | None = None
    period_seconds: int | None = Field(default=None, ge=0)
    aggregation: MeasurementAggregation = MeasurementAggregation.INSTANTANEOUS
    converted: bool = False
    lower_limit: float | None = None
    upper_limit: float | None = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = value.strip().lower().replace(" ", "_").replace("-", "_")
        if not cleaned:
            raise ValueError("measurement name must not be empty")
        return cleaned

    @field_validator("value", "original_value")
    @classmethod
    def _finite(cls, value: float | None) -> float | None:
        """Reject NaN and infinity — they are not measurements."""
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("measurement value must be a finite number")
        return value

    @field_validator("unit", "original_unit")
    @classmethod
    def _clean_unit(cls, value: str | None) -> str | None:
        return normalize_unit(value)

    @model_validator(mode="after")
    def _check_semantics(self) -> "Measurement":
        if self.original_value is None:
            object.__setattr__(self, "original_value", self.value)
        if self.original_unit is None:
            object.__setattr__(self, "original_unit", self.unit)

        # An accumulation without a period is meaningless and, more importantly, invites
        # downstream code to compare a total against an intensity.
        if self.aggregation == MeasurementAggregation.ACCUMULATION and not self.period_seconds:
            raise ValueError(
                "an accumulation measurement requires period_seconds so that a total is never "
                "compared against an instantaneous intensity"
            )
        if self.period_seconds == 0:
            raise ValueError("period_seconds must be greater than zero")

        if self.lower_limit is not None and self.upper_limit is not None:
            if self.lower_limit > self.upper_limit:
                raise ValueError("lower_limit must not exceed upper_limit")

        # Conversion consistency: `converted` must reflect reality.
        expected = (self.original_value != self.value) or (self.original_unit != self.unit)
        if expected and not self.converted:
            object.__setattr__(self, "converted", True)
        return self

    @classmethod
    def build(
        cls,
        name: str,
        value: float | None,
        unit: str | None,
        *,
        aggregation: MeasurementAggregation = MeasurementAggregation.INSTANTANEOUS,
        period_seconds: int | None = None,
        normalize_to: str | None = None,
        lower_limit: float | None = None,
        upper_limit: float | None = None,
    ) -> "Measurement | None":
        """Construct a measurement, converting to the canonical unit when defined.

        Returns ``None`` when ``value`` is ``None``. A missing reading is *not* zero, so callers
        must decide whether an absent optional measurement is simply omitted.
        """
        if value is None:
            return None

        original_value = float(value)
        original_unit = normalize_unit(unit)
        if not original_unit:
            raise ValidationError(
                f"measurement '{name}' is missing a unit",
                field_errors=[{"field": f"measurements.{name}.unit",
                               "code": ErrorDetail.UNSUPPORTED_UNIT}],
            )

        target = normalize_to if normalize_to is not None else canonical_unit_for(name)
        converted_value = original_value
        converted_unit = original_unit
        if target and target != original_unit:
            result = convert_measurement_value(name, original_value, original_unit, target)
            if result is not None:
                converted_value, converted_unit = result, target

        return cls(
            name=name,
            value=converted_value,
            unit=converted_unit,
            original_value=original_value,
            original_unit=original_unit,
            period_seconds=period_seconds,
            aggregation=aggregation,
            converted=converted_value != original_value or converted_unit != original_unit,
            lower_limit=lower_limit,
            upper_limit=upper_limit,
        )


class EventLocation(BaseModel):
    """A georeference for an event.

    Coordinates are optional. When they are absent, ``precision`` must be ``AREA`` or ``UNKNOWN``
    and an ``area_reference`` should be supplied, so the UI can show a region rather than a
    falsely precise pin.
    """

    model_config = ConfigDict(extra="forbid")

    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    accuracy_m: float | None = Field(default=None, ge=0.0)
    precision: LocationPrecision = LocationPrecision.APPROXIMATE
    place_id: str | None = Field(default=None, max_length=128)
    area_reference: str | None = Field(default=None, max_length=255)
    geometry_ref: str | None = Field(
        default=None,
        max_length=512,
        description="Optional reference to stored geometry (GeoJSON URI or object-store key).",
    )
    radius_m: float | None = Field(default=None, ge=0.0)
    datum: str | None = Field(default=None, max_length=32)

    @field_validator("latitude", "longitude", "accuracy_m", "radius_m")
    @classmethod
    def _finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("location values must be finite numbers")
        return value

    @model_validator(mode="after")
    def _check_pairing(self) -> "EventLocation":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be supplied together")

        if self.latitude is None:
            # No coordinates: precision cannot be precise or approximate.
            if self.precision in (LocationPrecision.PRECISE, LocationPrecision.APPROXIMATE):
                object.__setattr__(self, "precision", LocationPrecision.UNKNOWN)
        else:
            # Coordinates present: an 'area' precision is a contradiction.
            if self.precision == LocationPrecision.AREA:
                raise ValueError("precision 'area' is inconsistent with explicit coordinates")
            if self.precision == LocationPrecision.UNKNOWN:
                object.__setattr__(self, "precision", LocationPrecision.APPROXIMATE)
        return self

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @classmethod
    def from_area(cls, area_reference: str, **kwargs: Any) -> "EventLocation":
        """Build an area-level location without coordinates."""
        return cls(precision=LocationPrecision.AREA, area_reference=area_reference, **kwargs)


class CanonicalEvent(BaseModel):
    """The versioned canonical event envelope produced by every adapter."""

    model_config = ConfigDict(extra="forbid", validate_assignment=False)

    event_id: str
    source_id: str = Field(min_length=1, max_length=128)
    source_event_id: str | None = Field(default=None, max_length=256)
    event_type: EventType

    event_time: datetime
    ingest_time: datetime

    location: EventLocation | None = None
    measurements: list[Measurement] = Field(default_factory=list)

    source_kind: SourceKind
    quality_status: QualityStatus = QualityStatus.VALID
    quality_flags: list[QualityFlag] = Field(default_factory=list)

    # Text from a citizen report. Restricted: never returned to read-only clients.
    text: str | None = Field(default=None, max_length=4000)
    payload: dict[str, Any] = Field(default_factory=dict)

    schema_version: str = SCHEMA_VERSION
    idempotency_key: str
    fingerprint: str

    @field_validator("event_id")
    @classmethod
    def _event_id_shape(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("event_id must not be empty")
        if len(cleaned) > 128:
            raise ValueError("event_id must not exceed 128 characters")
        return cleaned

    @field_validator("source_id")
    @classmethod
    def _source_id_shape(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("source_id must not be empty")
        return cleaned

    @field_validator("event_time", "ingest_time")
    @classmethod
    def _tz_aware(cls, value: datetime) -> datetime:
        """Every timestamp is timezone-aware. A naive value is an ingestion bug, not a coercion."""
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return ensure_aware(value)

    @field_validator("schema_version")
    @classmethod
    def _supported_version(cls, value: str) -> str:
        if value not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"unsupported schema_version '{value}'; supported: "
                f"{sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        return value

    @field_validator("payload")
    @classmethod
    def _payload_shape(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):  # pragma: no cover - guarded by the type annotation
            raise ValueError("payload must be an object")
        return value

    @model_validator(mode="after")
    def _finalise(self) -> "CanonicalEvent":
        """Derive quality flags and the quality verdict from the event's own content.

        Rules:
        * A missing location is flagged, never invented.
        * Synthetic provenance is recorded as synthetic provenance — it is not "stale".
        * A measurement-bearing event with no measurements is suspect, not valid.
        """
        flags: list[QualityFlag] = list(self.quality_flags)

        if self.location is None or not self.location.has_coordinates:
            flags.append(QualityFlag.LOCATION_MISSING)
        elif self.location.precision == LocationPrecision.APPROXIMATE:
            flags.append(QualityFlag.LOCATION_PRECISION_LOW)

        # Synthetic provenance must never be mistaken for live evidence. `source_kind` remains the
        # authoritative field; this flag makes the distinction visible wherever a summary is
        # rendered without the full provenance block.
        if self.source_kind == SourceKind.SYNTHETIC:
            flags.append(QualityFlag.SYNTHETIC_DATA)
        elif self.source_kind == SourceKind.HISTORICAL:
            flags.append(QualityFlag.REPLAY_DATA)

        # Observation later than receipt implies provider clock skew. Recorded, not rejected.
        if self.event_time > self.ingest_time + timedelta(seconds=1):
            flags.append(QualityFlag.PROVIDER_PARTIAL_PAYLOAD)
            self.quality_status = QualityStatus.SUSPECT

        # Preserve insertion order while removing duplicates.
        object.__setattr__(self, "quality_flags", _dedupe(flags))

        # A missing reading is not a zero reading. An event whose type implies a reading but which
        # carries none is suspect rather than valid.
        if self.event_type not in NON_MEASUREMENT_TYPES and not self.measurements:
            object.__setattr__(self, "quality_status", QualityStatus.SUSPECT)

        return self

    @property
    def is_late(self) -> bool:
        """True when the event arrived meaningfully after the newest event it could extend."""
        return self.ingest_time > self.event_time + timedelta(seconds=60)

    @property
    def age_seconds(self) -> float:
        return max(0.0, (utc_now() - self.event_time).total_seconds())

    def to_response_dict(self, *, include_payload: bool = True,
                         include_text: bool = False) -> dict[str, Any]:
        """Serialise for an API response, omitting restricted fields when asked.

        ``text`` is a citizen-provided field and is withheld unless explicitly requested by a
        caller with the appropriate permission.
        """
        data = self.model_dump(mode="json")
        if not include_text:
            data.pop("text", None)
        if not include_payload:
            data["payload"] = {"_withheld": True, "reason": "raw payload withheld for this client"}
        return data


class CanonicalEventCreate(BaseModel):
    """Inbound canonical event for ``POST /api/v1/events``.

    Identity and provenance fields that the *server* must own (``ingest_time``,
    ``idempotency_key``, ``fingerprint``) are not accepted from the client; they are derived.
    """

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=128)
    source_event_id: str | None = Field(default=None, max_length=256)
    event_type: EventType
    event_time: datetime | str | int | float
    location: EventLocation | None = None
    measurements: list[Measurement] = Field(default_factory=list)
    source_kind: SourceKind = SourceKind.MANUAL
    text: str | None = Field(default=None, max_length=4000)
    payload: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    idempotency_key: str | None = Field(
        default=None,
        max_length=256,
        description="Optional caller-supplied key. When absent, one is derived from content.",
    )

    @field_validator("event_time", mode="before")
    @classmethod
    def _coerce_event_time(cls, value: Any) -> Any:
        """Accept ISO-8601 strings and epoch numbers, but reject nonsense early."""
        if value is None or isinstance(value, (int, float, datetime)):
            return value
        if isinstance(value, str):
            # Raise a clear error rather than letting the datetime parser produce a confusing one.
            parse_timestamp(value)
            return value
        raise TypeError(f"unsupported event_time type: {type(value).__name__}")

    def to_canonical(
        self,
        *,
        ingest_time: datetime | None = None,
        event_id: str | None = None,
    ) -> CanonicalEvent:
        """Materialise a fully-populated canonical event."""
        event_time = parse_timestamp(self.event_time)
        now = ensure_aware(ingest_time or utc_now())

        flags: list[QualityFlag] = []
        if isinstance(self.event_time, str) and _has_no_utc_offset(self.event_time):
            # A bare local timestamp is ambiguous. We interpret it as UTC and say so, rather than
            # silently guessing the operator's locale.
            flags.append(QualityFlag.NAIVE_TIMESTAMP_ASSUMED_UTC)

        canonical = CanonicalEvent(
            event_id=event_id or new_event_id(),
            source_id=self.source_id.strip(),
            source_event_id=(self.source_event_id or "").strip() or None,
            event_type=self.event_type,
            event_time=event_time,
            ingest_time=now,
            location=self.location,
            measurements=self.measurements,
            source_kind=self.source_kind,
            quality_status=QualityStatus.VALID,
            quality_flags=flags,
            text=self.text,
            payload=self.payload,
            schema_version=self.schema_version,
            idempotency_key="",  # replaced below
            fingerprint="",  # replaced below
        )
        fingerprint = compute_fingerprint(
            source_id=canonical.source_id,
            event_type=canonical.event_type,
            event_time=event_time,
            location=canonical.location,
            measurements=canonical.measurements,
            source_event_id=canonical.source_event_id,
        )
        idempotency_key = derive_idempotency_key(
            source_id=canonical.source_id,
            source_event_id=canonical.source_event_id,
            explicit_key=self.idempotency_key,
            fingerprint=fingerprint,
        )
        return canonical.model_copy(
            update={"fingerprint": fingerprint, "idempotency_key": idempotency_key}
        )


# ------------------------------------------------------------------- identity
_UTC_OFFSET_RE = re.compile(r"(?:Z|z|[+-]\d{2}:?\d{2})$")


def _has_no_utc_offset(raw: str) -> bool:
    """True when an ISO-8601 string carries no timezone designator."""
    return not _UTC_OFFSET_RE.search(raw.strip())


def new_event_id() -> str:
    """Generate a ULID-like, lexicographically sortable event id."""
    return f"evt_{uuid.uuid4().hex[:20]}"


def _round_or_none(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _measurement_signature(measurements: Iterable[Measurement]) -> list[dict[str, Any]]:
    """Build a stable, order-independent representation of the measurement set."""
    items = []
    for measurement in measurements:
        items.append({
            "n": measurement.name,
            "u": measurement.unit,
            # 4 significant decimals: enough to distinguish readings, coarse enough to absorb
            # provider float noise.
            "v": None if measurement.value is None else round(float(measurement.value), 4),
            "p": measurement.period_seconds,
            "a": measurement.aggregation.value,
        })
    return sorted(items, key=lambda item: (item["n"], str(item["u"])))


def compute_fingerprint(
    *,
    source_id: str,
    event_type: EventType | str,
    event_time: datetime,
    location: EventLocation | None,
    measurements: Iterable[Measurement],
    source_event_id: str | None = None,
) -> str:
    """Compute the fallback content fingerprint used when no provider id is available.

    Deliberately coarse. Fingerprint dedup is a safety net, not truth: it can merge two genuinely
    distinct readings that happen to fall in the same time bucket and round to the same
    coordinates. Source-specific overrides are possible in Milestone 2.

    Measurement-less events
    -----------------------
    When an event carries no measurements there is nothing in the content to distinguish one
    report from the next. Two citizen reports for the same area in the same minute are *distinct
    observations*, and collapsing them would destroy exactly the corroboration the product exists
    to surface. So for a measurement-less event the source event id (or reporter key) is folded
    into the fingerprint, and re-delivery still dedups while separate reports stay separate.
    """
    moment = ensure_aware(event_time)
    measurement_list = list(measurements)
    canonical: dict[str, Any] = {
        "source_id": source_id,
        "event_type": event_type.value if isinstance(event_type, EventType) else str(event_type),
        # 60-second bucket: providers frequently restate the same observation.
        "time_bucket": int(moment.timestamp() // 60),
        "lat": _round_or_none(location.latitude if location else None, 4),
        "lon": _round_or_none(location.longitude if location else None, 4),
        "measurements": _measurement_signature(measurement_list),
    }
    if not measurement_list and source_event_id:
        canonical["source_event_id"] = source_event_id
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"fp_{digest[:32]}"


def derive_idempotency_key(
    *,
    source_id: str,
    source_event_id: str | None,
    explicit_key: str | None,
    fingerprint: str,
) -> str:
    """Derive the idempotency key using the documented precedence hierarchy.

    1. Provider / source event id — the strongest identity a source can offer.
    2. Explicit caller-supplied idempotency key.
    3. Content fingerprint — the fallback.

    Note that provider event ids are scoped by ``source_id``: two sources may legitimately use
    the same upstream identifier.
    """
    if source_event_id:
        payload = f"{source_id}::{source_event_id}"
        return "idk_seid_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    if explicit_key:
        payload = f"{source_id}::{explicit_key}"
        return "idk_expl_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return f"idk_fp_{fingerprint.removeprefix('fp_')}"


def derive_event_id(*, source_id: str, source_event_id: str | None, fingerprint: str) -> str:
    """Derive a deterministic, process-independent event id.

    Python's built-in ``hash()`` is salted per process (PYTHONHASHSEED), so it must never be used
    here: replay reproducibility requires that the same fixture yields the same id on every run.
    """
    seed = f"{source_id}|{source_event_id}" if source_event_id else fingerprint
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"evt_{digest}"


def build_canonical_event(
    *,
    source_id: str,
    event_type: EventType,
    event_time: datetime,
    source_event_id: str | None = None,
    ingest_time: datetime | None = None,
    location: EventLocation | None = None,
    measurements: list[Measurement] | None = None,
    source_kind: SourceKind = SourceKind.LIVE_API,
    quality_status: QualityStatus | None = None,
    quality_flags: list[QualityFlag] | None = None,
    payload: dict[str, Any] | None = None,
    text: str | None = None,
    schema_version: str = SCHEMA_VERSION,
) -> CanonicalEvent:
    """Build a fully-derived canonical event.

    This is the single construction path for adapters. It computes the fingerprint, the
    idempotency key, and the event id in one place so that identity rules cannot drift between
    connectors.
    """
    moment = ensure_aware(event_time)
    received = ensure_aware(ingest_time or utc_now())
    measurement_list = measurements or []

    fingerprint = compute_fingerprint(
        source_id=source_id,
        event_type=event_type,
        event_time=moment,
        location=location,
        measurements=measurement_list,
        source_event_id=source_event_id,
    )
    idempotency_key = derive_idempotency_key(
        source_id=source_id,
        source_event_id=source_event_id,
        explicit_key=None,
        fingerprint=fingerprint,
    )
    event_id = derive_event_id(
        source_id=source_id, source_event_id=source_event_id, fingerprint=fingerprint
    )

    return CanonicalEvent(
        event_id=event_id,
        source_id=source_id,
        source_event_id=source_event_id,
        event_type=event_type,
        event_time=moment,
        ingest_time=received,
        location=location,
        measurements=measurement_list,
        source_kind=source_kind,
        quality_status=quality_status or QualityStatus.VALID,
        quality_flags=list(quality_flags or []),
        text=text,
        payload=payload or {},
        schema_version=schema_version,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
    )
