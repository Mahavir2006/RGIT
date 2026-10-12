"""Synthetic canonical events for processing tests. No network, no provider data."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from app.schemas.event import CanonicalEvent

#: Fixed reference instant so every test is reproducible.
T0 = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)

#: Mumbai, Andheri East (illustrative coordinates).
LAT, LON = 19.1136, 72.8697


def _h(*parts: Any) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:24]


def make_event(
    event_id: str,
    *,
    event_type: str = "water_level_observed",
    source_id: str = "water.dataset",
    minutes: float = 0,
    ingest_delay_s: float = 5,
    lat: float | None = LAT,
    lon: float | None = LON,
    precision: str = "precise",
    place_id: str | None = "WGD-04",
    area: str | None = None,
    measurements: list[dict[str, Any]] | None = None,
    source_kind: str = "live_api",
    text: str | None = None,
    source_event_id: str | None = None,
    base: datetime = T0,
    **extra: Any,
) -> CanonicalEvent:
    t = base + timedelta(minutes=minutes)
    location: dict[str, Any] | None = None
    if lat is not None or place_id or area:
        location = {"latitude": lat, "longitude": lon, "place_id": place_id,
                    "area_reference": area,
                    "precision": precision if lat is not None else ("area" if area else "unknown")}
    if measurements is None:
        measurements = [{"name": "water_level", "value": 0.5, "unit": "m"}]
    data = {
        "event_id": event_id, "source_id": source_id, "source_event_id": source_event_id,
        "event_type": event_type, "event_time": t,
        "ingest_time": t + timedelta(seconds=ingest_delay_s), "location": location,
        "measurements": measurements, "source_kind": source_kind, "text": text,
        "idempotency_key": f"idk_{_h(event_id)}", "fingerprint": f"fp_{_h(event_id, 'fp')}",
    }
    data.update(extra)
    return CanonicalEvent.model_validate(data)


def water(event_id: str, value: float, *, minutes: float = 0, **kw: Any) -> CanonicalEvent:
    return make_event(event_id, minutes=minutes,
                      measurements=[{"name": "water_level", "value": value, "unit": "m"}], **kw)


def rain(event_id: str, mm: float, *, minutes: float = 0, **kw: Any) -> CanonicalEvent:
    kw.setdefault("place_id", None)
    return make_event(event_id, event_type="rainfall_observed", source_id="weather.live",
                      minutes=minutes, measurements=[{
                          "name": "rainfall_1h", "value": mm, "unit": "mm",
                          "aggregation": "accumulation", "period_seconds": 3600}], **kw)


def report(event_id: str, text: str, *, minutes: float = 0, **kw: Any) -> CanonicalEvent:
    kw.setdefault("place_id", None)
    return make_event(event_id, event_type="waterlogging_reported", source_id="citizen.manual",
                      minutes=minutes, measurements=[], source_kind="manual", text=text, **kw)


def traffic(event_id: str, ratio: float, *, minutes: float = 0, speed: float | None = None,
            **kw: Any) -> CanonicalEvent:
    kw.setdefault("place_id", "seg-77")
    ms = [{"name": "speed_ratio", "value": ratio, "unit": "ratio"}]
    if speed is not None:
        ms.append({"name": "speed", "value": speed, "unit": "km/h"})
    return make_event(event_id, event_type="traffic_speed_observed", source_id="traffic.live",
                      minutes=minutes, measurements=ms, **kw)
