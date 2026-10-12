"""Integration: database-backed processing, retry safety, lifecycle, API, and hand-off."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.timeutil import utc_now
from app.db.processing_models import (
    AnomalyModel,
    AnomalyObservationModel,
    CandidateMatchModel,
    EventProcessingModel,
    IncidentModel,
)
from app.services.event_service import EventService
from app.services.processing_service import get_processing_service
from tests.conftest import TEST_WRITE_KEY
from tests.fixtures.processing.factory import T0, make_event, rain, report, traffic, water

BASE = "/api/v1"
W = {"X-API-Key": TEST_WRITE_KEY}
AS_OF = T0 + timedelta(hours=1)


async def persist(engine, *events):
    from app.db.session import get_session_factory

    async with get_session_factory()() as s:
        for e in events:
            s.add(EventService.to_model(e))
        await s.commit()


async def count(model, *where):
    from app.db.session import get_session_factory

    async with get_session_factory()() as s:
        stmt = select(func.count()).select_from(model)
        for w in where:
            stmt = stmt.where(w)
        return (await s.execute(stmt)).scalar_one()


async def one(model, *where):
    from app.db.session import get_session_factory

    async with get_session_factory()() as s:
        stmt = select(model)
        for w in where:
            stmt = stmt.where(w)
        return (await s.execute(stmt)).scalar_one()


def monsoon():
    return [
        rain("r1", 12.0, minutes=0), water("w1", 0.55, minutes=5), rain("r2", 31.0, minutes=20),
        water("w2", 0.92, minutes=25), water("w3", 1.25, minutes=45),
        report("c1", "knee-deep water near the metro station", minutes=50),
        traffic("t1", 0.22, minutes=55, lat=19.1146, place_id="seg-77"),
    ]


async def test_full_event_to_processing_workflow(engine):
    await persist(engine, *monsoon())
    res = await get_processing_service().process_events(
        [e.event_id for e in monsoon()], as_of=AS_OF)
    assert res["counts"]["PROCESSED"] == 7 and res["counts"]["FAILED"] == 0
    assert res["status"] in ("COMPLETED", "COMPLETED_WITH_WARNINGS")

    # Environmental anomalies on the water gauge: threshold + rapid rise.
    rules = {a.rule_id for a in [await one(AnomalyModel, AnomalyModel.rule_id == r)
                                 for r in ("water_level_high", "water_level_rapid_rise")]}
    assert rules == {"water_level_high", "water_level_rapid_rise"}

    # One hydro cluster gathers rain, gauge and report; normal readings are not forced in.
    inc = await one(IncidentModel, IncidentModel.families.isnot(None),
                    IncidentModel.seed_event_id == "r1")
    members = {m.event_id for m in [await one(CandidateMatchModel, CandidateMatchModel.event_id == e,
                                              CandidateMatchModel.incident_id == inc.incident_id)
                                    for e in ("r1", "r2", "w2", "w3", "c1", "t1")]}
    # The traffic slowdown 110 m away is compatible (k=0.6) and close: associated as evidence.
    assert members == {"r1", "r2", "w2", "w3", "c1", "t1"}
    assert await count(CandidateMatchModel, CandidateMatchModel.event_id == "w1") == 0
    assert inc.event_count == 6 and inc.peak_severity in ("HIGH", "CRITICAL")


async def test_retry_and_force_are_idempotent(engine):
    await persist(engine, *monsoon())
    ids = [e.event_id for e in monsoon()]
    svc = get_processing_service()
    await svc.process_events(ids, as_of=AS_OF)
    snapshot = [await count(m) for m in (AnomalyModel, AnomalyObservationModel,
                                         CandidateMatchModel, IncidentModel)]
    again = await svc.process_events(ids, as_of=AS_OF)
    assert again["counts"]["REUSED"] == 7
    forced = await svc.process_events(ids, as_of=AS_OF, force=True)
    assert forced["counts"]["PROCESSED"] == 7
    after = [await count(m) for m in (AnomalyModel, AnomalyObservationModel,
                                      CandidateMatchModel, IncidentModel)]
    assert after == snapshot
    row = await one(EventProcessingModel, EventProcessingModel.event_id == "w3")
    assert row.attempts == 2
    inc = await one(IncidentModel, IncidentModel.seed_event_id == "r1")
    assert inc.event_count == 6  # forcing never double-counts corroboration


async def test_concurrent_duplicate_processing_has_one_effect(tmp_path):
    """Two concurrent requests for one event, on real separate connections.

    The shared in-memory test database uses a single connection (StaticPool), which cannot model
    concurrency, so this test uses its own file-backed database.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.db.base import Base
    from app.processing.config import ProcessingConfig
    from app.services.processing_service import ProcessingService

    eng = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'c.db').as_posix()}",
                              poolclass=NullPool, connect_args={"timeout": 30})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        s.add(EventService.to_model(water("w1", 1.3)))
        await s.commit()
    cfg = ProcessingConfig()
    a_svc, b_svc = (ProcessingService(factory, cfg, sqlite=True) for _ in range(2))
    a, b = await asyncio.gather(a_svc.process_events(["w1"], as_of=AS_OF),
                                b_svc.process_events(["w1"], as_of=AS_OF))
    statuses = sorted([a["results"][0]["status"], b["results"][0]["status"]])
    # Exactly one request wins the atomic claim; the other reuses its result.
    assert statuses == ["PROCESSED", "REUSED"]
    async with factory() as s:
        for model, expected in ((EventProcessingModel, 1), (AnomalyModel, 1), (IncidentModel, 1)):
            assert (await s.execute(select(func.count()).select_from(model))).scalar_one() == expected
    await eng.dispose()


async def test_batch_with_invalid_and_unknown_events_continues(engine):
    bad = make_event("bad", measurements=[{"name": "water_level", "value": 2, "unit": "furlongs"}])
    await persist(engine, water("ok", 0.4), bad)
    res = await get_processing_service().process_events(["ok", "bad", "missing"], as_of=AS_OF)
    by_id = {r["event_id"]: r["status"] for r in res["results"] if r["event_id"]}
    assert by_id == {"ok": "PROCESSED", "bad": "QUARANTINED", "missing": "NOT_FOUND"}
    assert res["status"] == "PARTIALLY_FAILED"
    row = await one(EventProcessingModel, EventProcessingModel.event_id == "bad")
    assert row.validation_verdict == "QUARANTINED"
    assert any(i["code"] == "UNKNOWN_UNIT" for i in row.validation_issues)


async def test_stage_failure_is_isolated(engine, monkeypatch):
    import app.services.processing_service as ps

    real = ps.evaluate_event

    def boom(event, *a, **kw):
        if event.event_id == "w2":
            raise RuntimeError("synthetic stage failure")
        return real(event, *a, **kw)

    monkeypatch.setattr(ps, "evaluate_event", boom)
    await persist(engine, water("w1", 0.4), water("w2", 0.5, minutes=10),
                  water("w3", 0.45, minutes=20))
    res = await get_processing_service().process_events(["w1", "w2", "w3"], as_of=AS_OF)
    assert res["status"] == "PARTIALLY_FAILED" and res["counts"]["FAILED"] == 1
    failed = await one(EventProcessingModel, EventProcessingModel.event_id == "w2")
    assert failed.status == "FAILED" and "RuntimeError" in failed.error
    monkeypatch.setattr(ps, "evaluate_event", real)
    retry = await get_processing_service().process_events(["w2"], as_of=AS_OF)
    assert retry["counts"]["PROCESSED"] == 1  # FAILED results are retried, not reused


async def test_persistent_anomaly_updated_then_resolved_then_reopened(engine):
    seq = [water("a", 0.9, minutes=0), water("b", 0.95, minutes=30), water("c", 0.4, minutes=60),
           water("d", 1.0, minutes=90)]
    await persist(engine, *seq)
    svc = get_processing_service()
    await svc.process_events(["a", "b"], as_of=AS_OF)
    a = await one(AnomalyModel, AnomalyModel.rule_id == "water_level_high")
    assert a.status == "ACTIVE" and a.occurrence_count == 2
    assert await count(AnomalyModel, AnomalyModel.rule_id == "water_level_high") == 1

    await svc.process_events(["c"], as_of=AS_OF)
    a = await one(AnomalyModel, AnomalyModel.rule_id == "water_level_high")
    assert a.status == "RESOLVED" and a.resolved_by_event_id == "c"

    await svc.process_events(["d"], as_of=AS_OF + timedelta(hours=1))
    a = await one(AnomalyModel, AnomalyModel.rule_id == "water_level_high")
    assert a.status == "ACTIVE" and a.reopen_count == 1
    actions = [o.action for o in [await one(AnomalyObservationModel,
                                            AnomalyObservationModel.anomaly_id == a.anomaly_id,
                                            AnomalyObservationModel.event_id == e) for e in "abcd"]]
    assert actions == ["created", "updated", "resolved", "reopened"]


async def test_late_normal_reading_does_not_clear_newer_anomaly(engine):
    await persist(engine, water("new", 1.1, minutes=30), water("old", 0.3, minutes=0))
    svc = get_processing_service()
    await svc.process_events(["new"], as_of=AS_OF)
    await svc.process_events(["old"], as_of=AS_OF)  # arrives later, observed earlier
    a = await one(AnomalyModel, AnomalyModel.rule_id == "water_level_high")
    assert a.status == "ACTIVE"


async def test_late_event_is_reconciled_into_existing_incident(engine):
    await persist(engine, water("w1", 1.2, minutes=30))
    await get_processing_service().process_events(["w1"], as_of=AS_OF)
    late = report("late", "water rising since morning", minutes=10, ingest_delay_s=3000)
    await persist(engine, late)
    res = await get_processing_service().process_events(["late"], as_of=AS_OF)
    assert res["results"][0]["candidate_outcome"] == "MATCH_CANDIDATE"
    inc = await one(IncidentModel, IncidentModel.seed_event_id == "w1")
    assert inc.first_event_time.replace(tzinfo=None) == (T0 + timedelta(minutes=10)).replace(tzinfo=None)
    row = await one(EventProcessingModel, EventProcessingModel.event_id == "late")
    assert row.is_late


async def test_duplicate_is_not_independent_corroboration(engine):
    await persist(engine, water("w1", 1.2), water("w1dup", 1.2, minutes=2))
    await get_processing_service().process_events(["w1", "w1dup"], as_of=AS_OF)
    dup = await one(EventProcessingModel, EventProcessingModel.event_id == "w1dup")
    assert dup.dedup_decision == "POSSIBLE_DUPLICATE" and not dup.counts_as_corroboration
    inc = await one(IncidentModel, IncidentModel.seed_event_id == "w1")
    assert inc.event_count == 1


# ---------------------------------------------------------------------- API
def _seed_recent(client) -> list[str]:
    """Submit events relative to now through the real ingestion endpoint."""
    now = utc_now() - timedelta(minutes=30)
    ids = []
    for e in (water("x", 0.5, base=now), water("y", 1.3, base=now, minutes=20)):
        body = {"source_id": e.source_id, "event_type": e.event_type.value,
                "event_time": e.event_time.isoformat(),
                "location": e.location.model_dump(mode="json"),
                "measurements": [m.model_dump(mode="json") for m in e.measurements],
                "source_kind": "live_api"}
        r = client.post(f"{BASE}/events", json=body, headers=W)
        assert r.status_code in (200, 201), r.text
        data = r.json()["data"]
        ids.append(data["accepted_event_ids"][0])
    return ids


@pytest.mark.usefixtures("engine")
def test_api_processing_endpoints_filters_and_pagination(client):
    ids = _seed_recent(client)
    assert client.post(f"{BASE}/processing/events/{ids[1]}").status_code == 401

    r = client.post(f"{BASE}/processing/batches", json={"event_ids": ids}, headers=W)
    assert r.status_code == 200
    run_id = r.json()["data"]["run_id"]

    runs = client.get(f"{BASE}/processing/runs?page_size=1").json()
    assert runs["meta"]["pagination"]["page_size"] == 1 and runs["data"]
    detail = client.get(f"{BASE}/processing/runs/{run_id}").json()["data"]
    assert detail["config_snapshot"]["candidates"]["weights"]["T"] == 0.3

    ev = client.get(f"{BASE}/processing/events/{ids[1]}").json()["data"]
    assert ev["processing"][0]["validation"]["verdict"].startswith("VALID")
    assert ev["anomalies"] and ev["candidates"]

    active = client.get(f"{BASE}/anomalies?status=ACTIVE&kind=environmental&page_size=1").json()
    assert active["meta"]["pagination"]["total_items"] >= 1 and len(active["data"]) == 1
    aid = active["data"][0]["anomaly_id"]
    detail = client.get(f"{BASE}/anomalies/{aid}").json()["data"]
    assert detail["history"] and detail["explanation"]

    cands = client.get(f"{BASE}/incidents/candidates?outcome=PROVISIONAL_SEED").json()["data"]
    assert cands
    c = client.get(f"{BASE}/incidents/candidates/{cands[0]['candidate_id']}").json()["data"]
    assert "not a probability" in c["score_type"]
    assert client.get(f"{BASE}/anomalies/nope").status_code == 404

    # Re-sending the same batch reuses results.
    again = client.post(f"{BASE}/processing/batches", json={"event_ids": ids}, headers=W).json()
    assert again["data"]["counts"]["REUSED"] == 2


@pytest.mark.usefixtures("engine")
def test_ingestion_triggers_processing_and_stays_functional(client):
    r = client.post(f"{BASE}/ingest/replay", json={"fixture": "monsoon_waterlogging"}, headers=W)
    assert r.status_code == 200
    run = r.json()["data"]
    assert run["records_accepted"] > 0
    proc = run["notes"]["processing"]
    assert proc["run_ids"] and proc["incident_ids"]
    assert client.get(f"{BASE}/events?page_size=5").status_code == 200
    incidents = client.get(f"{BASE}/incidents").json()["data"]
    assert incidents and all(i["status"] == "provisional" for i in incidents)


@pytest.mark.usefixtures("engine")
def test_processed_incident_flows_into_intelligence_layer(client):
    client.post(f"{BASE}/ingest/replay", json={"fixture": "monsoon_waterlogging"}, headers=W)
    incidents = client.get(f"{BASE}/incidents").json()["data"]
    target = max(incidents, key=lambda i: i["independent_event_count"])
    iid = target["incident_id"]

    wi = client.get(f"{BASE}/incidents/{iid}/workflow-input").json()["data"]
    assert wi["incident_id"] == iid and wi["normalized_events"] and wi["anomaly_records"]
    assert set(wi["trigger_event_ids"]) <= {e["event_id"] for e in wi["normalized_events"]}
    assert all(e["provenance"]["source_kind"] == "synthetic" for e in wi["normalized_events"])

    assert client.post(f"{BASE}/incidents/{iid}/analyze", json={"wait": True}).status_code == 401
    res = client.post(f"{BASE}/incidents/{iid}/analyze", json={"wait": True}, headers=W)
    assert res.status_code == 200, res.text
    out = res.json()["data"]
    assert out["status"] in ("completed", "degraded", "review_required")
    hyps = client.get(f"{BASE}/incidents/{iid}/hypotheses")
    assert hyps.status_code == 200 and hyps.json()["hypotheses"]
    wf = client.get(f"{BASE}/intelligence/workflows/{out['workflow_id']}")
    assert wf.status_code == 200
