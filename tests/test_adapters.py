"""Adapter tests: parsing with mocked HTTP, missing credentials, and provider failure modes.

Every test uses ``pytest-httpx`` to mock the transport, so nothing here touches the network and
no credential is required.
"""

from __future__ import annotations

import re

import httpx
import pytest

from app.core.errors import (
    CredentialMissingError,
    RateLimitError,
    UpstreamAuthError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)
from app.ingestion.base import FetchRequest
from app.ingestion.openweather import OpenWeatherAdapter
from app.ingestion.openaq import OpenAQAdapter
from app.ingestion.traffic import TrafficAdapter
from tests.conftest import make_settings

OW_PAYLOAD = {
    "coord": {"lon": 72.8777, "lat": 19.0760},
    "weather": [{"description": "heavy intensity rain", "main": "Rain"}],
    "main": {"temp": 26.5, "humidity": 88, "pressure": 1004},
    "wind": {"speed": 9.2},
    "rain": {"1h": 28.4},
    "dt": 1797108072,
    "id": 1273294,
    "name": "Andheri East",
}


def _request(source_id: str = "t") -> FetchRequest:
    return FetchRequest(source_id=source_id, correlation_id="test")


# =============================================================== weather
async def test_weather_parses_current_conditions(httpx_mock, monkeypatch):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "test-key-placeholder")
    monkeypatch.setenv("WEATHER_LAT", "19.0760")
    monkeypatch.setenv("WEATHER_LON", "72.8777")
    adapter = OpenWeatherAdapter(make_settings(
        openweather_api_key="test-key-placeholder",
        weather_lat=19.0760, weather_lon=72.8777,
    ))
    httpx_mock.add_response(url=re.compile(r".*/data/2\.5/weather.*"), json=OW_PAYLOAD)

    result = await adapter.fetch_events(_request())
    assert len(result.events) == 1
    event = result.events[0]
    assert event.source_kind.value == "live_api"

    by_name = {m.name: m for m in event.measurements}
    assert by_name["rainfall_1h"].value == 28.4
    # Accumulation window preserved: a total is not an intensity.
    assert by_name["rainfall_1h"].aggregation.value == "accumulation"
    assert by_name["rainfall_1h"].period_seconds == 3600
    assert by_name["temperature"].value == 26.5
    assert event.location.latitude == pytest.approx(19.0760)


async def test_weather_identity_is_deterministic(httpx_mock, monkeypatch):
    settings = make_settings(
        openweather_api_key="test-key-placeholder",
        weather_lat=19.0760, weather_lon=72.8777,
    )
    adapter = OpenWeatherAdapter(settings)
    httpx_mock.add_response(url=re.compile(r".*/weather.*"), json=OW_PAYLOAD, is_reusable=True)
    first = await adapter.fetch_events(_request())
    second = await adapter.fetch_events(_request())
    assert first.events[0].event_id == second.events[0].event_id
    assert first.events[0].idempotency_key == second.events[0].idempotency_key


async def test_weather_missing_credential_names_variable_only(monkeypatch):
    adapter = OpenWeatherAdapter(make_settings(openweather_api_key=None,
                                              weather_lat=19.0, weather_lon=72.0))
    with pytest.raises(CredentialMissingError) as exc:
        await adapter.fetch_events(_request())
    assert "OPENWEATHER_API_KEY" in str(exc.value)
    assert "test-key" not in str(exc.value)
    # missing_settings reports names, never values.
    assert adapter.missing_settings() == ["openweather_api_key"]
    assert adapter.can_run_live() is False


async def test_weather_auth_failure_is_not_retried(httpx_mock, monkeypatch):
    adapter = OpenWeatherAdapter(make_settings(
        openweather_api_key="bad-key-placeholder",
        weather_lat=19.0, weather_lon=72.0,
    ))
    httpx_mock.add_response(status_code=401, json={"cod": 401, "message": "Invalid API key"})
    with pytest.raises(UpstreamAuthError) as exc:
        await adapter.fetch_events(_request())
    assert exc.value.retryable is False
    assert len(httpx_mock.get_requests()) == 1  # a bad key is not retried


async def test_weather_rate_limit_is_classified(httpx_mock, monkeypatch):
    adapter = OpenWeatherAdapter(make_settings(
        openweather_api_key="k-placeholder", weather_lat=19.0, weather_lon=72.0,
        http_max_retries=0,
    ))
    httpx_mock.add_response(status_code=429, headers={"Retry-After": "1"})
    with pytest.raises(RateLimitError):
        await adapter.fetch_events(_request())


async def test_weather_timeout_is_classified(httpx_mock, monkeypatch):
    adapter = OpenWeatherAdapter(make_settings(
        openweather_api_key="k-placeholder", weather_lat=19.0, weather_lon=72.0,
        http_max_retries=0,
    ))
    httpx_mock.add_exception(httpx.ReadTimeout("too slow"))
    with pytest.raises(UpstreamTimeoutError):
        await adapter.fetch_events(_request())


async def test_weather_malformed_json_is_handled(httpx_mock, monkeypatch):
    adapter = OpenWeatherAdapter(make_settings(
        openweather_api_key="k-placeholder", weather_lat=19.0, weather_lon=72.0,
    ))
    httpx_mock.add_response(text="<html>not json</html>")
    with pytest.raises(UpstreamUnavailableError):
        await adapter.fetch_events(_request())


# =============================================================== air quality
AQI_PAYLOAD = {
    "meta": {"page": 1, "limit": 100, "found": 1},
    "results": [
        {
            "id": 555,
            "parameter": "pm25",
            "parameterName": "PM2.5",
            "value": 58.0,
            "unit": "µg/m³",
            "periodInMinutes": 60,
            "datetime": "2026-10-12T03:15:00Z",
            "location": {
                "id": 2178,
                "name": "Andheri",
                "coordinates": {"latitude": 19.1136, "longitude": 72.8697, "id": 3920},
            },
            "country": "IN",
        },
        # No value: must be quarantined, never zero-filled.
        {
            "id": 556, "parameter": "pm10", "value": None, "unit": "µg/m³",
            "datetime": "2026-10-12T03:15:00Z",
            "location": {"coordinates": {"latitude": 19.1, "longitude": 72.8}},
        },
    ],
}


async def test_openaq_parses_measurements_and_quarantines_bad_rows(httpx_mock):
    adapter = OpenAQAdapter(make_settings(openaq_api_key="k-placeholder",
                                         aq_lat=19.1, aq_lon=72.8, aq_page_limit=1))
    httpx_mock.add_response(url=re.compile(r".*/measurements.*"), json=AQI_PAYLOAD)

    result = await adapter.fetch_events(_request())
    assert len(result.events) == 1
    event = result.events[0]
    assert event.measurements[0].value == 58.0
    assert event.measurements[0].unit == "ug/m3"
    # Averaging period preserved.
    assert event.measurements[0].period_seconds == 3600
    # The sensor is the precise emitter; the station is recorded separately, not overwritten.
    assert event.location.place_id == "3920"
    assert event.payload["station_id"] == "2178"
    assert event.payload["station_name"] == "Andheri"
    assert event.payload["sensor_id"] == "3920"

    # The row with no value is quarantined rather than stored as zero.
    quarantined = [o for o in result.outcomes if o.outcome.value == "quarantined"]
    assert len(quarantined) == 1
    assert quarantined[0].reason_code == "invalid_measurement_value"


async def test_openaq_never_derives_an_aqi(httpx_mock):
    adapter = OpenAQAdapter(make_settings(openaq_api_key="k-placeholder",
                                         aq_lat=19.1, aq_lon=72.8, aq_page_limit=1))
    httpx_mock.add_response(url=re.compile(r".*/measurements.*"), json=AQI_PAYLOAD)
    result = await adapter.fetch_events(_request())
    names = {m.name for m in result.events[0].measurements}
    assert names == {"pm25_concentration"}
    # No synthesised index.
    assert "aqi" not in names and "aqi_concentration" not in names


async def test_openaq_empty_result_warns_and_does_not_claim_clean_air(httpx_mock):
    adapter = OpenAQAdapter(make_settings(openaq_api_key="k-placeholder",
                                         aq_lat=19.1, aq_lon=72.8, aq_page_limit=1))
    httpx_mock.add_response(url=re.compile(r".*/measurements.*"), json={"meta": {}, "results": []})
    result = await adapter.fetch_events(_request())
    assert result.events == []
    assert any("no data, not that air quality is good" in w for w in result.warnings)


async def test_openaq_missing_credential():
    adapter = OpenAQAdapter(make_settings(openaq_api_key=None, aq_lat=19.1, aq_lon=72.8))
    with pytest.raises(CredentialMissingError) as exc:
        await adapter.fetch_events(_request())
    assert "OPENAQ_API_KEY" in str(exc.value)


# ==================================================================== traffic
TOMTOM_PAYLOAD = {
    "segments": [
        {"segmentId": "seg-1", "currentSpeed": 14.5, "freeFlowSpeed": 60, "confidence": "high"},
        # No free-flow speed: the ratio must NOT be computed.
        {"segmentId": "seg-2", "currentSpeed": 30, "confidence": "low"},
    ]
}


async def test_traffic_computes_ratio_only_when_denominator_exists(httpx_mock):
    adapter = TrafficAdapter(make_settings(tomtom_api_key="k-placeholder",
                                          traffic_segment_ids=["seg-1", "seg-2"]))
    httpx_mock.add_response(url=re.compile(r".*/flow/segment.*"), json=TOMTOM_PAYLOAD)

    result = await adapter.fetch_events(_request())
    assert len(result.events) == 2
    # One request covers every configured segment (comma-separated segmentId).
    assert len(httpx_mock.get_requests()) == 1

    with_ratio = next(e for e in result.events
                      if e.measurements and any(m.name == "speed_ratio" for m in e.measurements))
    names = {m.name for m in with_ratio.measurements}
    assert "speed_ratio" in names
    assert with_ratio.event_type.value == "traffic_congestion_observed"

    without = next(e for e in result.events
                   if not any(m.name == "speed_ratio" for m in e.measurements))
    assert "free_flow_speed" not in {m.name for m in without.measurements}
    assert without.payload["ratio_computed"] is False
    # The gap is recorded, not filled with a default.
    assert "provider_partial_payload" in [f.value for f in without.quality_flags]


async def test_traffic_refuses_to_fabricate_without_credentials():
    adapter = TrafficAdapter(make_settings(tomtom_api_key=None, traffic_segment_ids=["seg-1"]))
    with pytest.raises(CredentialMissingError) as exc:
        await adapter.fetch_events(_request())
    assert "TOMTOM_API_KEY" in str(exc.value)


async def test_traffic_requires_a_segment_id():
    adapter = TrafficAdapter(make_settings(tomtom_api_key="k-placeholder",
                                          traffic_segment_ids=[]))
    with pytest.raises(CredentialMissingError) as exc:
        await adapter.fetch_events(_request())
    assert "TRAFFIC_SEGMENT_ID" in str(exc.value)


async def test_traffic_rejects_negative_speed(httpx_mock):
    adapter = TrafficAdapter(make_settings(tomtom_api_key="k-placeholder",
                                          traffic_segment_ids=["seg-1"]))
    httpx_mock.add_response(
        url=re.compile(r".*/flow/segment.*"),
        json={"segments": [{"segmentId": "seg-1", "currentSpeed": -5}]},
    )
    result = await adapter.fetch_events(_request())
    assert result.events == []
    assert result.outcomes[0].reason_code == "invalid_measurement_value"


# ================================================================= provider 5xx
@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
async def test_server_errors_are_retried_then_reported(httpx_mock, status_code):
    adapter = OpenWeatherAdapter(make_settings(
        openweather_api_key="k-placeholder", weather_lat=19.0, weather_lon=72.0,
        http_max_retries=1,
    ))
    httpx_mock.add_response(status_code=status_code)
    httpx_mock.add_response(status_code=status_code)
    with pytest.raises(UpstreamUnavailableError):
        await adapter.fetch_events(_request())
    assert len(httpx_mock.get_requests()) == 2  # bounded retries
