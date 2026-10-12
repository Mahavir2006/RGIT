"""Event families, type compatibility, and shared helpers (geo distance, subject keys).

A *family* groups canonical event types that describe the same kind of phenomenon. The
compatibility matrix (configured in :class:`CandidateConfig`) says how plausibly two families can
belong to one incident. It influences ranking only; it is not a causal claim.
"""

from __future__ import annotations

import math

from app.schemas.event import CanonicalEvent, EventType

__all__ = ["family_of", "compatibility", "haversine_m", "subject_of", "area_of",
           "primary_measurement", "INCIDENT_FAMILIES", "SENSOR_HEALTH_TYPES"]

_FAMILY: dict[EventType, str] = {
    EventType.RAINFALL_OBSERVED: "rain",
    EventType.WATER_LEVEL_OBSERVED: "hydro",
    EventType.WATER_LEVEL_RISING: "hydro",
    EventType.TRAFFIC_SPEED_OBSERVED: "traffic",
    EventType.TRAFFIC_CONGESTION_OBSERVED: "traffic",
    EventType.TRAFFIC_TRAVEL_TIME_OBSERVED: "traffic",
    EventType.ROAD_BLOCKED_OBSERVED: "traffic",
    EventType.AIR_QUALITY_OBSERVED: "air",
    EventType.WATERLOGGING_REPORTED: "report_flood",
    EventType.FODDLING_REPORTED: "report_flood",
    EventType.ROAD_BLOCKAGE_REPORTED: "report_road",
    EventType.AIR_QUALITY_COMPLAINT: "report_air",
    EventType.POWER_OUTAGE_REPORTED: "report_power",
    EventType.PUBLIC_HEALTH_REPORTED: "report_health",
}

#: Families that can seed or join an incident. Weather context (temperature, wind...) cannot.
INCIDENT_FAMILIES = frozenset(_FAMILY.values())

SENSOR_HEALTH_TYPES = frozenset(
    {EventType.SENSOR_OFFLINE, EventType.SENSOR_STALE, EventType.SOURCE_UNAVAILABLE}
)

#: Primary numeric reading per event type, for summaries handed downstream.
_PRIMARY: dict[str, tuple[str, ...]] = {
    "rain": ("rainfall_1h", "rainfall_3h", "rainfall"),
    "hydro": ("water_level",),
    "traffic": ("speed_ratio", "speed"),
    "air": ("pm25_concentration", "pm10_concentration"),
}


def family_of(event_type: EventType | str) -> str | None:
    try:
        return _FAMILY.get(EventType(event_type))
    except ValueError:
        return None


def compatibility(matrix: dict[str, dict[str, float]], a: str | None, b: str | None) -> float:
    """Symmetric lookup; unknown pairs are incompatible (0.0)."""
    if a is None or b is None:
        return 0.0
    return max(matrix.get(a, {}).get(b, 0.0), matrix.get(b, {}).get(a, 0.0))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def subject_of(event: CanonicalEvent) -> str:
    """Stable sensor/station/segment identity for grouping readings from one instrument."""
    loc = event.location
    if loc and loc.place_id:
        return f"place:{loc.place_id}"
    seg = event.payload.get("segment_id") or event.payload.get("station_id")
    if seg:
        return f"place:{seg}"
    if loc and loc.has_coordinates:
        return f"geo:{loc.latitude:.4f},{loc.longitude:.4f}"
    return f"source:{event.source_id}"


def area_of(event: CanonicalEvent) -> str | None:
    loc = event.location
    return loc.area_reference.strip().lower() if loc and loc.area_reference else None


def primary_measurement(event: CanonicalEvent) -> tuple[str, float, str] | None:
    fam = family_of(event.event_type)
    by_name = {m.name: m for m in event.measurements}
    for name in _PRIMARY.get(fam or "", ()):
        if name in by_name:
            m = by_name[name]
            return m.name, m.value, m.unit
    if event.measurements:
        m = event.measurements[0]
        return m.name, m.value, m.unit
    return None
