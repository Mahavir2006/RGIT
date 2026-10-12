"""HTTP API: envelopes, authorisation, pagination, restricted fields, and source health."""

from __future__ import annotations

import pytest

from tests.conftest import TEST_WRITE_KEY

BASE = "/api/v1"


# --------------------------------------------------------------------- health
def test_health_reports_readiness_and_what_is_not_implemented(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["liveness"] == "up"
    assert data["readiness"] == "ready"
    assert data["database"]["status"] == "ready"
    assert data["canonical_schema"]["version"] == "1.0"
    implemented = data["implemented"]
    assert implemented["ingestion"] is True
    assert implemented["anomaly_detection"] is True
    assert implemented["candidate_matching"] is True
    # Agent capabilities are reported only as far as the mounted layer provides them, and the
    # evidence graph is never claimed without Neo4j.
    mounted = data["intelligence_layer"]["mounted"]
    for capability in ("incident_fusion", "causal_inference", "cascade_simulation", "ai_agents"):
        assert implemented[capability] is mounted
    assert implemented["evidence_graph"] is False


def test_openapi_and_docs_available(client):
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_request_id_is_echoed(client):
    response = client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers["X-Request-ID"] == "trace-abc-123"
    assert response.json()["meta"]["request_id"] == "trace-abc-123"


def test_generated_request_id_matches_envelope_meta(client):
    """Without an inbound id, the generated one must appear in both header and body."""
    response = client.get(f"{BASE}/events")
    generated = response.headers["X-Request-ID"]
    assert generated
    assert response.json()["meta"]["request_id"] == generated


# ---------------------------------------------------------------- source alias
@pytest.mark.parametrize(
    ("alias", "source_id"),
    [
        ("replay", "replay.all"),
        ("weather", "weather.live"),
        ("air_quality", "airquality.live"),
        ("airquality", "airquality.live"),
        ("traffic", "traffic.live"),
        ("water", "water.dataset"),
        ("citizen", "citizen.manual"),
        ("weather.live", "weather.live"),
    ],
)
def test_ingest_accepts_category_alias(client, write_headers, alias, source_id):
    response = client.post(f"{BASE}/ingest/{alias}", json={"fixture": "weather"},
                           headers=write_headers)
    assert response.status_code == 200
    # The run is always recorded under the canonical source id, never the alias.
    assert response.json()["data"]["source_id"] == source_id


def test_ingest_unknown_source_is_404_with_available_ids(client, write_headers):
    response = client.post(f"{BASE}/ingest/nonsense", json={}, headers=write_headers)
    assert response.status_code == 404
    assert "replay.all" in response.json()["error"]["details"]["available"]


def test_ambiguous_alias_is_rejected_not_guessed():
    from app.core.errors import NotFoundError
    from app.ingestion.openweather import OpenWeatherAdapter
    from app.ingestion.registry import SourceRegistry

    class SecondWeather(OpenWeatherAdapter):
        source_id = "weather.backup"

    reg = SourceRegistry()
    reg.register(OpenWeatherAdapter())
    reg.register(SecondWeather())
    with pytest.raises(NotFoundError) as info:
        reg.resolve("weather")
    assert info.value.details["candidates"] == ["weather.backup", "weather.live"]


# -------------------------------------------------------------------- sources
def test_list_sources_covers_all_five_categories(client):
    response = client.get(f"{BASE}/sources")
    assert response.status_code == 200
    sources = response.json()["data"]["sources"]
    categories = {s["category"] for s in sources}
    assert {"weather", "air_quality", "traffic", "water", "citizen", "replay"} <= categories


def test_list_sources_never_exposes_credential_values(client):
    body = client.get(f"{BASE}/sources").text
    assert TEST_WRITE_KEY not in body
    for source in client.get(f"{BASE}/sources").json()["data"]["sources"]:
        for credential in source["credentials"]:
            # State only: a configured flag and a variable name.
            assert set(credential) == {"variable", "configured", "placeholder"}


def test_source_health_is_available_before_any_ingestion(client):
    response = client.get(f"{BASE}/sources/health")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] >= 6
    # A source that has never run must be unknown, not healthy.
    for source in data["sources"]:
        if source["last_success_at"] is None:
            assert source["status"] != "healthy"


def test_source_health_states_missing_data_is_not_safety(client):
    body = client.get(f"{BASE}/sources/health").json()["data"]
    assert "not evidence that a location is safe" in body["data_mode_note"]


def test_unknown_source_is_404(client):
    response = client.get(f"{BASE}/sources/does.not.exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# ------------------------------------------------------------------ ingestion
def test_replay_ingestion_requires_write_key(client):
    response = client.post(f"{BASE}/ingest/replay.all", json={})
    assert response.status_code in (401, 403)
    assert response.json()["error"] is not None


def test_replay_ingestion_succeeds_with_write_key(client, write_headers):
    response = client.post(
        f"{BASE}/ingest/replay.all",
        json={"fixture": "monsoon_waterlogging"},
        headers=write_headers,
    )
    assert response.status_code == 200
    run = response.json()["data"]
    assert run["status"] in ("succeeded", "partial")
    assert run["records_accepted"] > 0
    assert run["records_rejected"] == 0
    assert run["duration_ms"] >= 0


def test_replay_events_are_labelled_synthetic(client, write_headers):
    client.post(f"{BASE}/ingest/replay.all", json={"fixture": "monsoon_waterlogging"},
                headers=write_headers)
    events = client.get(f"{BASE}/events?page_size=100").json()["data"]
    assert events
    assert all(e["source_kind"] == "synthetic" for e in events)
    assert all("synthetic_data" in e["quality_flags"] for e in events)


def test_rerunning_replay_produces_duplicates_not_new_events(client, write_headers):
    first = client.post(f"{BASE}/ingest/replay.all", json={"fixture": "weather"},
                        headers=write_headers).json()["data"]
    count_after_first = client.get(f"{BASE}/events?page_size=1").json()["meta"]["pagination"][
        "total_items"]

    second = client.post(f"{BASE}/ingest/replay.all", json={"fixture": "weather"},
                         headers=write_headers).json()["data"]

    count_after_second = client.get(f"{BASE}/events?page_size=1").json()["meta"]["pagination"][
        "total_items"]

    assert first["records_accepted"] > 0
    assert second["records_accepted"] == 0
    assert second["records_duplicate"] == first["records_accepted"]
    # Event count is unchanged: duplicates never become second canonical events.
    assert count_after_first == count_after_second


def test_ingestion_runs_are_listed(client, write_headers):
    client.post(f"{BASE}/ingest/replay.all", json={"fixture": "water"}, headers=write_headers)
    response = client.get(f"{BASE}/ingestion/runs")
    assert response.status_code == 200
    runs = response.json()["data"]
    assert runs
    assert {"run_id", "source_id", "status", "records_accepted"} <= set(runs[0])


def test_failing_source_does_not_break_other_sources(client, write_headers):
    """A source with no credentials fails on its own; replay still succeeds."""
    failed = client.post(f"{BASE}/ingest/weather.live", json={}, headers=write_headers)
    assert failed.status_code == 200
    run = failed.json()["data"]
    assert run["status"] == "failed"
    assert run["error_category"] == "credential_missing"
    # The error names the variable, never a value.
    assert "OPENWEATHER_API_KEY" in str(run["errors"])
    assert TEST_WRITE_KEY not in str(run["errors"])

    healthy = client.post(f"{BASE}/ingest/replay.all", json={"fixture": "weather"},
                          headers=write_headers).json()["data"]
    assert healthy["records_accepted"] > 0


# --------------------------------------------------------------------- events
def _event_payload(**overrides):
    payload = {
        "source_id": "weather.manual",
        "source_event_id": "manual-1",
        "event_type": "rainfall_observed",
        "event_time": "2026-10-12T08:30:00Z",
        "location": {"latitude": 19.0760, "longitude": 72.8777, "accuracy_m": 50},
        "measurements": [
            {"name": "rainfall_1h", "value": 12.5, "unit": "mm",
             "aggregation": "accumulation", "period_seconds": 3600}
        ],
        "source_kind": "manual",
    }
    payload.update(overrides)
    return payload


def _distinct_event(index: int):
    """A genuinely distinct reading: a different observation time and a different value.

    Varying only ``source_event_id`` would still produce an identical content fingerprint, and an
    identical reading in the same bucket *is* a duplicate by design.
    """
    minute = f"08:{30 + index:02d}"
    return _event_payload(
        source_event_id=f"p-{index}",
        event_time=f"2026-10-12T{minute}:00Z",
        measurements=[{"name": "rainfall_1h", "value": 10.0 + index, "unit": "mm",
                       "aggregation": "accumulation", "period_seconds": 3600}],
    )


def test_submit_event_requires_write_key(client):
    response = client.post(f"{BASE}/events", json=_event_payload())
    assert response.status_code in (401, 403)


def test_submit_event_succeeds(client, write_headers):
    response = client.post(f"{BASE}/events", json=_event_payload(), headers=write_headers)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["accepted"] == 1
    assert data["accepted_event_ids"]


def test_submit_batch(client, write_headers):
    payload = [_distinct_event(i) for i in range(3)]
    response = client.post(f"{BASE}/events", json=payload, headers=write_headers)
    assert response.status_code == 201
    assert response.json()["data"]["accepted"] == 3


def test_submit_duplicate_reports_duplicate_not_second_event(client, write_headers):
    first = client.post(f"{BASE}/events", json=_event_payload(), headers=write_headers)
    assert first.status_code == 201
    second = client.post(f"{BASE}/events", json=_event_payload(), headers=write_headers)
    assert second.status_code == 200  # accepted request, no new event
    data = second.json()["data"]
    assert data["accepted"] == 0
    assert data["duplicate"] == 1
    assert data["duplicates"][0]["event_id"] in first.json()["data"]["accepted_event_ids"]


def test_invalid_coordinates_are_rejected_with_field_errors(client, write_headers):
    response = client.post(
        f"{BASE}/events",
        json=_event_payload(location={"latitude": 120.0, "longitude": 0.0}),
        headers=write_headers,
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["field_errors"]


def test_invalid_timestamp_is_rejected(client, write_headers):
    response = client.post(
        f"{BASE}/events", json=_event_payload(event_time="the day before yesterday"),
        headers=write_headers,
    )
    assert response.status_code == 422


def test_accumulation_without_period_is_rejected(client, write_headers):
    response = client.post(
        f"{BASE}/events",
        json=_event_payload(measurements=[{"name": "rainfall_1h", "value": 12.5, "unit": "mm",
                                           "aggregation": "accumulation"}]),
        headers=write_headers,
    )
    assert response.status_code == 422


def test_event_listing_and_pagination(client, write_headers):
    for index in range(7):
        client.post(f"{BASE}/events", json=_distinct_event(index), headers=write_headers)

    page1 = client.get(f"{BASE}/events?page=1&page_size=3").json()
    page2 = client.get(f"{BASE}/events?page=2&page_size=3").json()
    meta = page1["meta"]["pagination"]

    assert meta["page"] == 1 and meta["page_size"] == 3
    assert meta["total_items"] == 7
    assert meta["total_pages"] == 3
    assert meta["has_next"] is True and meta["has_previous"] is False
    assert len(page1["data"]) == 3
    assert page2["meta"]["pagination"]["has_previous"] is True


def test_pagination_is_bounded(client):
    assert client.get(f"{BASE}/events?page_size=500").status_code == 422
    assert client.get(f"{BASE}/events?page=0").status_code == 422


def test_event_filters(client, write_headers):
    client.post(f"{BASE}/ingest/replay.all", json={"fixture": "monsoon_waterlogging"},
                headers=write_headers)
    water = client.get(f"{BASE}/events?source_category=water").json()
    assert water["meta"]["pagination"]["total_items"] > 0
    assert all(
        e["source_id"].startswith("water.") for e in water["data"]
    )


def test_event_detail_and_provenance(client, write_headers):
    created = client.post(f"{BASE}/events", json=_event_payload(),
                          headers=write_headers).json()["data"]
    event_id = created["accepted_event_ids"][0]

    detail = client.get(f"{BASE}/events/{event_id}").json()["data"]
    assert detail["event_id"] == event_id
    assert detail["provenance"]["duplicate_receipt_count"] == 0
    assert detail["schema_version"] == "1.0"


def test_event_detail_reports_duplicate_receipts(client, write_headers):
    created = client.post(f"{BASE}/events", json=_event_payload(),
                          headers=write_headers).json()["data"]
    client.post(f"{BASE}/events", json=_event_payload(), headers=write_headers)

    detail = client.get(f"{BASE}/events/{created['accepted_event_ids'][0]}").json()["data"]
    assert detail["provenance"]["duplicate_receipt_count"] == 1
    receipt = detail["provenance"]["duplicate_receipts"][0]
    assert receipt["decision"] in ("idempotency_key", "fingerprint")


def test_missing_event_is_404(client):
    response = client.get(f"{BASE}/events/evt_does_not_exist")
    assert response.status_code == 404


# -------------------------------------------------------------------- reports
def test_submit_citizen_report(client, write_headers):
    response = client.post(
        f"{BASE}/reports",
        json={
            "report_category": "waterlogging",
            "text": "Knee-deep water near the metro station.",
            "reported_at": "2026-10-12T09:12:00+05:30",
            "location": {"latitude": 19.0760, "longitude": 72.8777, "accuracy_m": 30},
            "area_reference": "Andheri East",
        },
        headers=write_headers,
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "unverified"
    assert data["event_type"] == "waterlogging_reported"


def test_citizen_report_requires_write_key(client):
    response = client.post(f"{BASE}/reports", json={"report_category": "waterlogging"})
    assert response.status_code in (401, 403)


def test_citizen_report_text_is_restricted_in_read_endpoints(client, write_headers):
    created = client.post(
        f"{BASE}/reports",
        json={"report_category": "waterlogging", "text": "Deep water at the junction."},
        headers=write_headers,
    ).json()["data"]

    # Default listing withholds report text.
    listing = client.get(f"{BASE}/events?page_size=50").text
    assert "Deep water at the junction" not in listing

    # Detail also withholds it by default.
    detail = client.get(f"{BASE}/events/{created['event_id']}").text
    assert "Deep water at the junction" not in detail


def test_citizen_report_rejects_phone_number_as_reporter_id(client, write_headers):
    response = client.post(
        f"{BASE}/reports",
        json={"report_category": "waterlogging", "reporter_id": "+91 9876543210"},
        headers=write_headers,
    )
    assert response.status_code == 422


def test_citizen_report_redacts_pii(client, write_headers):
    response = client.post(
        f"{BASE}/reports",
        json={
            "report_category": "road_blockage",
            "text": "Blocked. Ring me on 9876543210 please.",
        },
        headers=write_headers,
    )
    assert response.status_code == 201
    assert response.json()["data"]["redacted"] is True


# ------------------------------------------------------------------- envelope
def test_all_responses_use_the_same_envelope(client):
    for path in ("/health", f"{BASE}/sources", f"{BASE}/events", f"{BASE}/sources/health"):
        body = client.get(path).json()
        assert set(body) == {"data", "meta", "error"}
        assert body["error"] is None
        assert "request_id" in body["meta"]


def test_errors_use_the_same_envelope(client):
    body = client.get(f"{BASE}/events/nope").json()
    assert set(body) == {"data", "meta", "error"}
    assert body["data"] is None
    assert {"code", "message", "field_errors", "details", "retryable"} == set(body["error"])
