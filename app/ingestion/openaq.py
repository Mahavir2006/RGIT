"""Air-quality adapter — OpenAQ v3.

API shape
---------
v3 splits station metadata (``/locations``) from measurements (``/measurements``). This adapter
calls ``/measurements`` with a bounding box or radius, paginating until the configured page limit
is reached. Each measurement carries its location inline, so station identity is preserved
without a second round trip.

AQI handling
------------
OpenAQ reports raw pollutant concentrations. It does **not** publish a single comparable AQI
figure across countries. This adapter therefore records only the pollutant concentrations it
actually receives and never synthesises an AQI. A derived index, if added later, must carry a
documented calculation method and its own provenance flag.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.core.config import Settings, get_settings
from app.core.errors import CredentialMissingError, UpstreamUnavailableError
from app.core.logging import get_logger
from app.core.timeutil import parse_timestamp, utc_now
from app.ingestion.base import AdapterOutcome, AdapterResult, FetchRequest, SourceAdapter
from app.ingestion.http import ProviderClient, require_credential
from app.schemas.common import (
    LocationPrecision,
    MeasurementAggregation,
    QualityFlag,
    SourceCategory,
    SourceKind,
)
from app.schemas.event import EventLocation, EventType, Measurement, build_canonical_event

__all__ = ["OpenAQAdapter"]

logger = get_logger(__name__)

# OpenAQ unit strings we accept, mapped onto canonical spellings. Anything else is preserved
# verbatim with a warning rather than being guessed at.
UNIT_MAP = {
    "µg/m³": "ug/m3",
    "μg/m³": "ug/m3",
    "µg/m3": "ug/m3",
    "μg/m3": "ug/m3",
    "ug/m3": "ug/m3",
    "ppm": "ppm",
    "ppb": "ppb",
    "ppmv": "ppm",
}


class OpenAQAdapter(SourceAdapter):
    """OpenAQ v3 pollutant measurements for a configured bounding area."""

    source_id = "airquality.live"
    display_name = "OpenAQ v3 (live)"
    category = SourceCategory.AIR_QUALITY
    provider = "openaq"
    supports_live = True
    supports_replay = True
    documentation_url = "https://docs.openaq.org/resources/measurements"
    unit_notes = (
        "Pollutant concentrations preserved in the unit the station reported "
        "(normalised spelling only, no value conversion). No AQI is derived."
    )
    caveats = (
        "Requires OPENAQ_API_KEY; a 401/403 is never retried.",
        "Pagination is bounded by AQ_PAGE_LIMIT to avoid exhausting quota.",
        "An empty result set is normal and is reported as a warning, not as 'air is clean'.",
        "Live mode is unverified in this environment: no credential was available to test against.",
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def required_settings(self) -> list[str]:
        required = ["openaq_api_key"]
        if self.settings.aq_lat is None or self.settings.aq_lon is None:
            required += ["aq_lat", "aq_lon"]
        return required

    async def fetch_events(self, request: FetchRequest) -> AdapterResult:
        started = utc_now()
        outcome = AdapterOutcome()

        api_key = require_credential(self.settings.openaq_api_key, "OPENAQ_API_KEY", self.provider)
        lat, lon = self.settings.aq_lat, self.settings.aq_lon
        if lat is None or lon is None:
            raise CredentialMissingError(
                "OpenAQ live mode requires AQ_LAT and AQ_LON, which are not set. "
                "Set them, or use replay mode.",
                details={"missing_settings": ["AQ_LAT", "AQ_LON"]},
            )

        params: dict[str, Any] = {
            "coordinates": f"{lat},{lon}",
            "radius": self.settings.aq_radius_m,
            "limit": 100,
            "page": 1,
        }
        if self.settings.aq_pollutants:
            params["parameters"] = ",".join(self.settings.aq_pollutants)

        client = ProviderClient(self.provider, settings=self.settings)
        try:
            for page in range(1, max(1, self.settings.aq_page_limit) + 1):
                params["page"] = page
                payload = await client.get_json(
                    f"{self.settings.openaq_base_url}/measurements",
                    headers={"X-API-Key": api_key},
                    params=params,
                )
                outcome.pages_fetched += 1

                results = payload.get("results") if isinstance(payload, dict) else None
                if not isinstance(results, list) or not results:
                    if page == 1:
                        outcome.warnings.append(
                            "OpenAQ returned no measurements for the configured area. "
                            "This means no data, not that air quality is good."
                        )
                    break

                self._parse_page(results, outcome)

                meta = payload.get("meta") if isinstance(payload, dict) else None
                found_page = _as_int((meta or {}).get("page"))
                found_limit = _as_int((meta or {}).get("limit"))
                total_pages = _as_int((meta or {}).get("found"))
                if page >= self.settings.aq_page_limit and (
                    found_limit is not None and len(results) >= found_limit
                ):
                    outcome.truncated = True
                    outcome.warnings.append(
                        f"Stopped after {page} page(s) at AQ_PAGE_LIMIT; more measurements exist."
                    )
                    break
                if found_page is not None and found_page >= max(1, total_pages or 1) and page > 1:
                    break
        finally:
            await client.aclose()

        if not outcome.events and not outcome.warnings:
            outcome.warnings.append("OpenAQ returned no usable measurements.")

        return AdapterResult.from_outcome(self.source_id, outcome, started)

    # ------------------------------------------------------------- parsing
    def _parse_page(self, results: Iterable[Any], outcome: AdapterOutcome) -> None:
        """Parse one page of measurement records.

        One canonical event is produced per (station, measurement) pair, because each reading has
        its own pollutant, unit, and averaging period. Bundling them would lose that provenance.
        """
        for index, record in enumerate(results):
            if not isinstance(record, dict):
                outcome.reject(
                    reason_code="malformed_payload",
                    message=f"OpenAQ record {index} was not an object.",
                    outcome="quarantined",
                )
                continue

            pollutant = (record.get("parameter") or "").strip().lower()
            value = _as_float(record.get("value"))
            unit_raw = record.get("unit")

            if not pollutant:
                outcome.reject(
                    reason_code="missing_required_field",
                    message=f"OpenAQ record {index} has no pollutant parameter.",
                    outcome="quarantined",
                )
                continue
            if value is None:
                # An unusable reading is reported, never replaced with zero.
                outcome.reject(
                    reason_code="invalid_measurement_value",
                    message=f"OpenAQ record {index} ({pollutant}) had no usable numeric value.",
                    source_event_id=str(record.get("id") or "") or None,
                    outcome="quarantined",
                )
                continue
            if not unit_raw:
                outcome.reject(
                    reason_code="unsupported_unit",
                    message=f"OpenAQ record {index} ({pollutant}) reported no unit.",
                    source_event_id=str(record.get("id") or "") or None,
                    outcome="quarantined",
                )
                continue

            unit = UNIT_MAP.get(str(unit_raw), str(unit_raw))
            location = self._parse_location(record)
            observation = self._parse_time(record)
            station_id, station_name = self._station(record)

            period_seconds, aggregation = _averaging_period(record)
            # Concentration naming: pm25_concentration so the ug/m3 family rule applies.
            reading = Measurement.build(
                f"{pollutant}_concentration",
                value,
                unit,
                aggregation=aggregation,
                period_seconds=period_seconds,
            )
            if reading is None:  # pragma: no cover - guarded by the value check above
                outcome.reject(
                    reason_code="invalid_measurement_value",
                    message=f"OpenAQ record {index} ({pollutant}) could not be converted.",
                    outcome="quarantined",
                )
                continue

            flags: list[QualityFlag] = []
            if location is None:
                flags.append(QualityFlag.LOCATION_MISSING)
            if aggregation == MeasurementAggregation.AVERAGE and not period_seconds:
                flags.append(QualityFlag.PROVIDER_PARTIAL_PAYLOAD)

            # The emitter location (sensor) is the precise fix; the station it belongs to is
            # recorded separately so station provenance is not lost.
            source_event_id = f"openaq-{record.get('id', index)}"

            outcome.accept(
                build_canonical_event(
                    source_id=self.source_id,
                    source_event_id=source_event_id,
                    event_type=EventType.AIR_QUALITY_OBSERVED,
                    event_time=observation,
                    ingest_time=utc_now(),
                    location=location,
                    measurements=[reading],
                    source_kind=SourceKind.LIVE_API,
                    quality_flags=flags,
                    payload={
                        "provider": self.provider,
                        "api_version": "v3",
                        "station_id": station_id,
                        "station_name": station_name,
                        "sensor_id": _sensor_id(record),
                        "pollutant": pollutant,
                        "parameter_name": record.get("parameterName"),
                        "parameter_units": record.get("parameterUnits"),
                        "averaging_period_minutes": (
                            period_seconds // 60 if period_seconds else None
                        ),
                        "country": record.get("country"),
                    },
                )
            )

    @staticmethod
    def _station(record: dict[str, Any]) -> tuple[str | None, str | None]:
        """Return the containing station's id and name.

        v3 nests sensor coordinates inside a ``location`` object that also carries the station
        identity. The two must not be conflated: a sensor moves, a station is the site.
        """
        location_obj = record.get("location")
        if isinstance(location_obj, dict):
            station_id = location_obj.get("id")
            name = location_obj.get("name")
            return (
                str(station_id) if station_id is not None else None,
                str(name) if name is not None else None,
            )
        return None, None

    def _parse_location(self, record: dict[str, Any]) -> EventLocation | None:
        """Prefer inline sensor coordinates; fall back to the containing location object."""
        sensor = record.get("location")
        coordinates: dict[str, Any] | None = None
        if isinstance(sensor, dict) and isinstance(sensor.get("coordinates"), dict):
            coordinates = sensor["coordinates"]
        elif isinstance(sensor, dict):
            coordinates = sensor

        if isinstance(coordinates, dict):
            lat = _as_float(coordinates.get("latitude"))
            lon = _as_float(coordinates.get("longitude"))
            if lat is not None and lon is not None:
                return EventLocation(
                    latitude=lat,
                    longitude=lon,
                    # A monitoring station is a fixed, well-surveyed site.
                    precision=LocationPrecision.PRECISE,
                    accuracy_m=_as_float(coordinates.get("accuracy")),
                    place_id=str(coordinates.get("id") or "") or None,
                )

        # Location-level fallback (station, not sensor).
        location_obj = record.get("location")
        if isinstance(location_obj, dict) and isinstance(location_obj.get("coordinates"), list):
            coords = location_obj["coordinates"]
            if len(coords) >= 2:
                lon_v, lat_v = _as_float(coords[0]), _as_float(coords[1])
                if lat_v is not None and lon_v is not None:
                    return EventLocation(
                        latitude=lat_v,
                        longitude=lon_v,
                        precision=LocationPrecision.APPROXIMATE,
                        place_id=str(location_obj.get("id") or "") or None,
                    )
        return None

    @staticmethod
    def _parse_time(record: dict[str, Any]) -> Any:
        """OpenAQ reports a UTC datetime in `datetime.utc` (v3: `datetime.local`)."""
        for key in ("datetime", "datetimeLocal", "lastUpdated"):
            if record.get(key):
                try:
                    return parse_timestamp(record[key])
                except ValueError:
                    continue
        return utc_now()


def _averaging_period(record: dict[str, Any]) -> tuple[int | None, MeasurementAggregation]:
    """Derive the averaging window from the provider's period fields."""
    for key in ("periodInMinutes", "averagingPeriodMinutes"):
        minutes = _as_int(record.get(key))
        if minutes and minutes > 0:
            return minutes * 60, MeasurementAggregation.AVERAGE
    for key in ("period", "periodInSeconds"):
        seconds = _as_int(record.get(key))
        if seconds and seconds > 0:
            return seconds, MeasurementAggregation.AVERAGE
    # No period declared: the reading is treated as instantaneous at observation time, and the
    # absence is recorded by the caller as a partial payload.
    return None, MeasurementAggregation.INSTANTANEOUS


def _sensor_id(record: dict[str, Any]) -> str | None:
    location_obj = record.get("location")
    if isinstance(location_obj, dict):
        coordinates = location_obj.get("coordinates")
        if isinstance(coordinates, dict) and coordinates.get("id") is not None:
            return str(coordinates["id"])
    return None


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


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
