"""Weather adapter — OpenWeather current-conditions endpoint.

Important limitation
--------------------
This adapter calls ``/data/2.5/weather`` (current conditions) only. That endpoint reports the
**last observed** condition at one point in time. It does not provide history or forecast, and
this adapter deliberately does not fabricate either. Adding historical or forecast support means
adding an explicitly separate source id, because the provenance and event-time semantics differ.

Rainfall semantics
------------------
OpenWeather reports ``rain.1h`` / ``rain.3h`` as *accumulations over a period*. They are mapped to
measurements with ``aggregation=ACCUMULATION`` and an explicit ``period_seconds``, so a total is
never compared against an instantaneous intensity downstream.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings
from app.core.errors import CredentialMissingError
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
from app.schemas.event import (
    EventLocation,
    EventType,
    Measurement,
    build_canonical_event,
)

__all__ = ["OpenWeatherAdapter"]

logger = get_logger(__name__)

# OpenWeather `rain`/`snow` window keys mapped to seconds.
PRECIPITATION_WINDOWS = {"1h": 3600, "3h": 10800}


class OpenWeatherAdapter(SourceAdapter):
    """OpenWeather current-weather observations for one configured location."""

    source_id = "weather.live"
    display_name = "OpenWeather (live)"
    category = SourceCategory.WEATHER
    provider = "openweather"
    supports_live = True
    supports_replay = True
    documentation_url = "https://openweathermap.org/current"
    unit_notes = (
        "Temperature normalised to degrees Celsius; wind speed normalised to km/h; "
        "precipitation kept as an accumulation in millimetres over the stated window."
    )
    caveats = (
        "Current-conditions endpoint only: no historical observations and no forecast.",
        "A 401 from this provider is never retried; re-check OPENWEATHER_API_KEY.",
        "Live mode is unverified in this environment: no credential was available to test against.",
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def required_settings(self) -> list[str]:
        required = ["openweather_api_key"]
        if self.settings.weather_lat is None or self.settings.weather_lon is None:
            required += ["weather_lat", "weather_lon"]
        return required

    async def fetch_events(self, request: FetchRequest) -> AdapterResult:
        started = utc_now()
        outcome = AdapterOutcome()

        api_key = require_credential(
            self.settings.openweather_api_key, "OPENWEATHER_API_KEY", self.provider
        )
        lat = self.settings.weather_lat
        lon = self.settings.weather_lon
        if self.settings.weather_lat is None or self.settings.weather_lon is None:
            raise CredentialMissingError(
                "OpenWeather live mode requires WEATHER_LAT and WEATHER_LON, which are not set. "
                "Set them, or use replay mode.",
                details={"missing_settings": ["WEATHER_LAT", "WEATHER_LON"]},
            )

        client = ProviderClient(self.provider, settings=self.settings)
        try:
            payload = await client.get_json(
                f"{self.settings.openweather_base_url}/weather",
                params={
                    "lat": lat,
                    "lon": lon,
                    "appid": api_key,
                    "units": self.settings.openweather_units,
                },
            )
        finally:
            await client.aclose()

        outcome.pages_fetched = 1
        outcome.provider_meta = {
            "endpoint": "/data/2.5/weather",
            "units_requested": self.settings.openweather_units,
        }

        if not isinstance(payload, dict):
            raise UpstreamUnavailableError(
                "OpenWeather returned an unexpected payload shape (expected an object).",
                details={"provider": self.provider},
            )

        event = self._parse_current(payload)
        if event is None:
            outcome.warnings.append("OpenWeather payload contained no usable observation.")
        else:
            outcome.accept(event)

        return AdapterResult.from_outcome(self.source_id, outcome, started)

    # ------------------------------------------------------------- parsing
    def _parse_current(self, payload: dict[str, Any]) -> CanonicalEvent | None:
        """Map one current-conditions payload onto a canonical event."""
        if not isinstance(payload, dict):
            return None

        main = payload.get("main") or {}
        if not isinstance(main, dict):
            main = {}

        # --- timing: OpenWeather reports an offset-aware local time.
        raw_dt = payload.get("dt")
        if raw_dt is None:
            event_time = utc_now()
        else:
            try:
                event_time = parse_timestamp(raw_dt)
            except ValueError:
                event_time = utc_now()

        coord = payload.get("coord") or {}
        location = self._parse_location(coord)

        measurements: list[Measurement] = []
        flags: list[QualityFlag] = []

        temperature = _as_float(main.get("temp"))
        if temperature is not None:
            # With units=metric this is already Celsius; Measurement.build keeps the original.
            reading = Measurement.build(
                "temperature", temperature, "c", aggregation=MeasurementAggregation.INSTANTANEOUS
            )
            if reading:
                measurements.append(reading)

        humidity = _as_float(main.get("humidity"))
        if humidity is not None:
            reading = Measurement.build("humidity", humidity, "%")
            if reading:
                measurements.append(reading)

        pressure = _as_float(main.get("pressure"))
        if pressure is not None:
            # OpenWeather reports hPa.
            reading = Measurement.build("pressure", pressure, "hPa")
            if reading:
                measurements.append(reading)

        # --- precipitation: accumulation windows, never instantaneous intensity.
        for block, label in (("rain", "rainfall"), ("snow", "snowfall")):
            section = payload.get(block)
            if not isinstance(section, dict):
                continue
            for window_key, seconds in PRECIPITATION_WINDOWS.items():
                amount = _as_float(section.get(window_key))
                if amount is None:
                    continue
                reading = Measurement.build(
                    f"{label}_{window_key}",
                    amount,
                    "mm",
                    aggregation=MeasurementAggregation.ACCUMULATION,
                    period_seconds=seconds,
                )
                if reading:
                    measurements.append(reading)

        wind = payload.get("wind") or {}
        if isinstance(wind, dict):
            speed = _as_float(wind.get("speed"))
            if speed is not None:
                # With units=metric this is m/s; the measurement layer converts to km/h and
                # retains the original.
                reading = Measurement.build("wind_speed", speed, "m/s")
                if reading:
                    measurements.append(reading)

        condition = None
        weather_list = payload.get("weather")
        if isinstance(weather_list, list) and weather_list:
            first = weather_list[0]
            if isinstance(first, dict):
                condition = first.get("description") or first.get("main")

        if not measurements and not condition:
            return None

        # Precipitation absent is normal, not an error; note it so a later reader knows the
        # absence was observed rather than the provider omitting the field.
        if not any(m.name.startswith(("rainfall", "snowfall")) for m in measurements):
            flags.append(QualityFlag.OPTIONAL_MEASUREMENT_ABSENT)

        # An explicitly absent precipitation block is a meaningful observation, so add a zero
        # *accumulation* measurement only when the provider states the value is 0. We never
        # synthesise zero from a missing key.
        event_type = (
            EventType.RAINFALL_OBSERVED
            if any(m.name.startswith("rainfall") for m in measurements)
            else (
                EventType.WEATHER_CONDITION_OBSERVED
                if not any(
                    m.name.startswith(("temperature", "humidity", "pressure", "wind"))
                    for m in measurements
                )
                else EventType.TEMPERATURE_OBSERVED
            )
        )

        provider_id = payload.get("id")
        source_event_id = f"ow-current-{provider_id}-{int(event_time.timestamp())}"

        payload_summary = {
            "provider": self.provider,
            "city_id": provider_id,
            "city_name": payload.get("name"),
            "condition": condition,
            "observed_endpoint": "current",
            "units_requested": self.settings.openweather_units,
        }
        # The full provider payload is intentionally reduced to this summary for lineage: the
        # endpoint returns the same handful of fields, and retaining the raw body verbatim would
        # only duplicate it without adding traceability.
        return build_canonical_event(
            source_id=self.source_id,
            source_event_id=source_event_id,
            event_type=event_type,
            event_time=event_time,
            ingest_time=utc_now(),
            location=location,
            measurements=measurements,
            source_kind=SourceKind.LIVE_API,
            quality_flags=flags,
            payload=payload_summary,
        )

    def _parse_location(self, coord: Any) -> EventLocation | None:
        if not isinstance(coord, dict):
            return None
        lat = _as_float(coord.get("lat"))
        lon = _as_float(coord.get("lon"))
        if lat is None or lon is None:
            return None
        return EventLocation(
            latitude=lat,
            longitude=lon,
            # A city centroid, not a point measurement: say so rather than implying precision.
            precision=LocationPrecision.APPROXIMATE,
            accuracy_m=5000.0,
        )


def _as_float(value: Any) -> float | None:
    """Coerce a provider number to float, returning None for anything unusable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    # Guard NaN/inf, which would otherwise poison downstream statistics.
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result
