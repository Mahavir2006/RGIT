"""End-to-end: the demo journey, with no network and no credentials.

Covers the operator walkthrough the PRD describes, limited to what Milestone 1 actually builds.
"""

from __future__ import annotations

from app.core.timeutil import ensure_aware, parse_timestamp
from tests.conftest import TEST_WRITE_KEY

BASE = "/api/v1"


def test_full_demo_journey(client, write_headers):
    """Walk the Milestone 1 demo path end to end."""

    # 1. health
    health = client.get("/health").json()["data"]
    assert health["readiness"] == "ready"

    # 2. sources cover all five categories with explicit modes
    sources = client.get(f"{BASE}/sources").json()["data"]["sources"]
    categories = {s["category"] for s in sources}
    assert {"weather", "air_quality", "traffic", "water", "citizen"} <= categories

    # 3. ingest the monsoon scenario. Rebasing onto the current clock is the realistic demo path:
    #    the fixture timestamps are literal 2026-10-12 values, which would otherwise read as stale.
    run = client.post(f"{BASE}/ingest/replay.all",
                      json={"fixture": "monsoon_waterlogging", "rebase": True},
                      headers=write_headers).json()["data"]
    assert run["status"] in ("succeeded", "partial")
    assert run["records_accepted"] >= 10
    assert run["records_rejected"] == 0

    # 4. every event is labelled synthetic
    events = client.get(f"{BASE}/events?page_size=100").json()["data"]
    assert events
    assert all(e["source_kind"] == "synthetic" for e in events)
    assert all("synthetic_data" in e["quality_flags"] for e in events)

    # 5. event detail carries provenance and units
    sample = next(e for e in events if e["event_type"] == "rainfall_observed")
    detail = client.get(f"{BASE}/events/{sample['event_id']}").json()["data"]
    assert detail["schema_version"] == "1.0"
    assert detail["provenance"]["first_run_id"] == run["run_id"]
    rainfall = next(m for m in detail["measurements"] if m["name"].startswith("rainfall"))
    assert rainfall["aggregation"] == "accumulation"
    assert rainfall["period_seconds"] == 3600
    assert rainfall["original_unit"] is not None

    # 6. re-running yields duplicates, not new events
    before = client.get(f"{BASE}/events?page_size=1").json()["meta"]["pagination"]["total_items"]
    second = client.post(f"{BASE}/ingest/replay.all",
                         json={"fixture": "monsoon_waterlogging", "rebase": True},
                         headers=write_headers).json()["data"]
    after = client.get(f"{BASE}/events?page_size=1").json()["meta"]["pagination"]["total_items"]
    assert second["records_accepted"] == 0
    assert second["records_duplicate"] == run["records_accepted"]
    assert before == after

    # 7. a citizen report lands as an unverified observation
    report = client.post(
        f"{BASE}/reports",
        json={
            "report_category": "waterlogging",
            "text": "Water is rising near the drain. Ring 9876543210.",
            "reported_at": "2026-10-12T09:55:00+05:30",
            "location": {"latitude": 19.0760, "longitude": 72.8777, "accuracy_m": 30},
            "area_reference": "Andheri East",
        },
        headers=write_headers,
    ).json()["data"]
    assert report["status"] == "unverified"
    assert report["redacted"] is True

    # 8. source health reflects the run
    health_rows = client.get(f"{BASE}/sources/health").json()["data"]
    replay = next(s for s in health_rows["sources"] if s["source_id"] == "replay.all")
    assert replay["records_accepted"] > 0
    assert replay["last_success_at"] is not None
    assert replay["latest_event_time"] is not None
    assert replay["is_fresh"] is True

    # 9. run history is inspectable
    runs = client.get(f"{BASE}/ingestion/runs").json()["data"]
    assert len(runs) >= 2
    assert all("records_duplicate" in r for r in runs)


def test_non_rebased_replay_is_correctly_reported_as_stale(client, write_headers):
    """A fixture with literal timestamps must not be presented as fresh data."""
    client.post(f"{BASE}/ingest/replay.all", json={"fixture": "water", "rebase": False},
                headers=write_headers)
    rows = client.get(f"{BASE}/sources/health").json()["data"]["sources"]
    replay = next(s for s in rows if s["source_id"] == "replay.all")
    assert replay["records_accepted"] > 0
    # The newest observation is far older than the freshness window.
    assert replay["ingest_lag_seconds"] is not None
    assert replay["ingest_lag_seconds"] > replay["freshness_sla_seconds"]
    assert replay["is_fresh"] is False


def test_missing_credentials_do_not_block_replay(client, write_headers):
    """No provider credentials: live sources fail clearly, replay still works."""
    live = client.post(f"{BASE}/ingest/traffic.live", json={}, headers=write_headers).json()["data"]
    assert live["status"] == "failed"
    assert live["error_category"] == "credential_missing"
    assert live["records_accepted"] == 0

    replay = client.post(f"{BASE}/ingest/replay.all", json={"fixture": "traffic"},
                         headers=write_headers).json()["data"]
    assert replay["records_accepted"] == 4


def test_one_failing_source_does_not_stop_another(client, write_headers):
    """Per-source failure isolation, observed through the API."""
    for source in ("weather.live", "airquality.live", "traffic.live"):
        client.post(f"{BASE}/ingest/{source}", json={}, headers=write_headers)

    runs = client.get(f"{BASE}/ingestion/runs?page_size=50").json()["data"]
    failed = [r for r in runs if r["source_id"].endswith(".live")]
    assert len(failed) == 3
    assert all(r["status"] == "failed" for r in failed)

    # Unrelated ingestion still succeeds afterwards.
    ok = client.post(f"{BASE}/ingest/replay.all", json={"fixture": "weather"},
                     headers=write_headers).json()["data"]
    assert ok["records_accepted"] > 0


def test_out_of_order_replay_is_reproducible(client, write_headers):
    """A seeded shuffle yields the same set of events, delivered in a different order."""
    first = client.post(f"{BASE}/ingest/replay.all",
                        json={"fixture": "monsoon_waterlogging", "shuffle": True,
                              "shuffle_seed": 4242},
                        headers=write_headers).json()["data"]
    assert first["records_accepted"] > 0

    # The same fixture shuffled the same way again: everything is now a duplicate, and the
    # canonical set is unchanged.
    total = client.get(f"{BASE}/events?page_size=1").json()["meta"]["pagination"]["total_items"]
    second = client.post(f"{BASE}/ingest/replay.all",
                         json={"fixture": "monsoon_waterlogging", "shuffle": True,
                               "shuffle_seed": 4242},
                         headers=write_headers).json()["data"]
    assert second["records_accepted"] == 0
    assert client.get(f"{BASE}/events?page_size=1").json()["meta"]["pagination"][
        "total_items"] == total


def test_late_arriving_event_keeps_its_observation_time(client, write_headers):
    """Submit a back-dated event and confirm the stored event_time is unchanged."""
    response = client.post(
        f"{BASE}/events",
        json={
            "source_id": "water.manual",
            "source_event_id": "late-001",
            "event_type": "water_level_observed",
            "event_time": "2026-10-12T08:05:00Z",
            "location": {"latitude": 19.0760, "longitude": 72.8777, "accuracy_m": 20},
            "measurements": [{"name": "water_level", "value": 0.61, "unit": "m"}],
            "source_kind": "manual",
        },
        headers=write_headers,
    )
    event_id = response.json()["data"]["accepted_event_ids"][0]
    detail = client.get(f"{BASE}/events/{event_id}").json()["data"]

    # Event time preserved; ingest time reflects receipt.
    assert ensure_aware(parse_timestamp(detail["event_time"])) == parse_timestamp(
        "2026-10-12T08:05:00Z"
    )
    assert detail["late"]["is_late"] is True


def test_no_secret_appears_anywhere_in_the_api_surface(client, write_headers):
    """Sweep every read endpoint for credential material."""
    client.post(f"{BASE}/ingest/replay.all", json={"fixture": "all"}, headers=write_headers)
    client.post(f"{BASE}/reports", json={"report_category": "waterlogging",
                                         "text": "Deep water."},
                headers=write_headers)
    client.post(f"{BASE}/ingest/weather.live", json={}, headers=write_headers)

    for path in ("/health", f"{BASE}/sources", f"{BASE}/sources/health",
                 f"{BASE}/events?page_size=100", f"{BASE}/ingestion/runs"):
        body = client.get(path).text
        assert TEST_WRITE_KEY not in body
        assert "appid=" not in body


def test_event_explorer_shows_ingest_lag_and_provenance(client, write_headers):
    client.post(f"{BASE}/ingest/replay.all", json={"fixture": "water"}, headers=write_headers)
    events = client.get(f"{BASE}/events?page_size=50").json()["data"]
    for event in events:
        assert "event_time" in event and "ingest_time" in event
        assert event["idempotency_key"] and event["fingerprint"]
        assert event["schema_version"] == "1.0"
        assert event["quality_status"] in ("valid", "suspect", "stale", "imputed", "invalid")
