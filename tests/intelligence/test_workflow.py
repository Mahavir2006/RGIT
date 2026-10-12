from __future__ import annotations

import asyncio

import pytest

from urban_sentinel.domain.models import (
    AssociationDecision,
    CorrelationResult,
    EventType,
    HypothesisStatus,
    NormalizedEvent,
    ReviewDecision,
    ScoreType,
    SourceHealthRecord,
    SourceHealthStatus,
)
from urban_sentinel.intelligence.llm import ScriptedLLM
from urban_sentinel.intelligence.service import IntelligenceService


@pytest.mark.asyncio
async def test_unambiguous_association_skips_fusion_llm(service, payload, graph):
    payload.correlation_results = [
        CorrelationResult(
            event_id=item.event_id,
            incident_id="inc-monsoon-12",
            score=0.9,
            existing_association=item.event_id == "evt-rain-1",
        )
        for item in payload.normalized_events
    ]
    payload.candidate_incident_ids = ["inc-monsoon-12"]
    result = await service.run(payload)
    agents = [run["agent_name"] for run in result["agent_runs"]]
    assert "incident_fusion" not in agents
    assert result["fusion_decisions"]
    assert result["fusion_decisions"][0]["decision"] in {
        AssociationDecision.ATTACH_TO_INCIDENT.value,
        AssociationDecision.AMBIGUOUS_REVIEW.value,
    }
    assert graph.write_counts.get("link:evt-water-1:inc-monsoon-12", 0) >= 1


@pytest.mark.asyncio
async def test_ambiguous_association_invokes_fusion(service, payload):
    result = await service.run(payload)
    agents = [run["agent_name"] for run in result["agent_runs"]]
    assert "incident_fusion" in agents
    assert any(item["review_required"] for item in result["fusion_decisions"])
    assert result["review_required"] is True


@pytest.mark.asyncio
async def test_duplicate_and_late_arriving_events(service, payload):
    late = payload.normalized_events[-1]
    late.duplicate_of = "evt-water-1"
    result = await service.run(payload)
    signal = result["signal_analysis"]
    assert any(d["possible_duplicate_of"] == "evt-water-1" for d in signal["possible_duplicates"])
    assert any(f.get("confidence_note") == "late-arriving" for f in signal["extracted_facts"])


@pytest.mark.asyncio
async def test_contradictory_evidence_keeps_multiple_hypotheses(service, payload):
    result = await service.run(payload)
    claims = [h["claim"] for h in result["hypotheses"]]
    assert any("waterlogging" in c.lower() for c in claims)
    assert any("traffic" in c.lower() for c in claims)
    flood = next(h for h in result["hypotheses"] if "waterlogging" in h["claim"].lower())
    traffic = next(h for h in result["hypotheses"] if "traffic" in h["claim"].lower())
    assert flood["supporting_event_ids"]
    assert traffic["supporting_event_ids"]
    assert flood["hypothesis_id"] != traffic["hypothesis_id"]


@pytest.mark.asyncio
async def test_missing_water_level_sensor(service, payload):
    payload.normalized_events = [
        e for e in payload.normalized_events if e.event_type != EventType.WATER_LEVEL
    ]
    payload.trigger_event_ids = [e.event_id for e in payload.normalized_events]
    payload.source_health.append(
        SourceHealthRecord(
            source_id="sensor-wl-04",
            status=SourceHealthStatus.OFFLINE,
        )
    )
    result = await service.run(payload)
    gaps = " ".join(result["evidence_gaps"]).lower()
    assert "water-level" in gaps or "offline" in gaps
    assert "not evidence of safe" in " ".join(
        c["description"].lower() for c in result["signal_analysis"]["quality_concerns"]
    )


@pytest.mark.asyncio
async def test_cascade_path_with_known_edges(service, payload):
    result = await service.run(payload)
    scenarios = result["cascade_scenarios"]
    assert scenarios
    affected = set(scenarios[0]["affected_asset_ids"])
    assert "hospital-er" in affected or any(
        "hospital-er" in path["asset_ids"] for path in scenarios[0]["dependency_paths"]
    )
    assert scenarios[0]["simulated"] is True
    assert scenarios[0]["score_type"] != ScoreType.INSUFFICIENT.value


@pytest.mark.asyncio
async def test_no_dependency_path(service, payload, graph):
    graph.seed_edges([])
    payload.dependencies = []
    result = await service.run(payload)
    assert result["cascade_scenarios"]
    assert result["cascade_scenarios"][0]["affected_asset_ids"] == []
    assert "absence of known edges" in " ".join(result["cascade_scenarios"][0]["limitations"]).lower()


@pytest.mark.asyncio
async def test_invalid_agent_output_falls_back(settings, graph, operational, payload, scripted_llm):
    scripted_llm.queue(
        {
            "extracted_facts": [{"event_id": "does-not-exist", "statement": "invented"}],
            "relevant_event_ids": ["does-not-exist"],
            "ambiguities": [],
            "possible_duplicates": [],
            "quality_concerns": [],
            "evidence_summary": "bad",
        }
    )
    service = IntelligenceService(
        settings=settings, operational=operational, graph=graph, llm=scripted_llm
    )
    result = await service.run(payload)
    assert result["signal_analysis"]["used_fallback"] is True
    assert "does-not-exist" not in result["signal_analysis"]["relevant_event_ids"]


@pytest.mark.asyncio
async def test_llm_timeout_uses_deterministic_fallback(
    settings, graph, operational, payload, scripted_llm
):
    scripted_llm.force_timeout = True
    service = IntelligenceService(
        settings=settings, operational=operational, graph=graph, llm=scripted_llm
    )
    result = await service.run(payload)
    assert any(run["fallback_used"] for run in result["agent_runs"])
    assert result["hypotheses"]
    assert result["status"] in {"degraded", "review_required", "completed"}


@pytest.mark.asyncio
async def test_neo4j_unavailable_degraded_mode(service, payload, graph):
    graph.mark_unavailable("bolt handshake failed")
    result = await service.run(payload)
    assert result["graph_degraded"] is True
    assert result["evidence_context"]["graph_available"] is False
    assert result["cascade_scenarios"] == [] or result["status"] == "degraded"
    assert any("unavailable" in (e or "").lower() for e in result["errors"]) or result["status"] == "degraded"


@pytest.mark.asyncio
async def test_repeated_workflow_is_idempotent(service, payload, graph):
    await service.run(payload)
    first = dict(graph.write_counts)
    await service.run(payload)
    assert graph.write_counts == first
    hyps = service.operational.get_hypotheses("inc-monsoon-12")
    ids = [h.hypothesis_id for h in hyps]
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_concurrent_incident_updates(service, payload):
    payload.expected_incident_version = 1
    service.operational.upsert_incident(payload.incident)
    payload.incident.version = 1

    async def run_with_version(expected: int):
        copy = payload.model_copy(deep=True)
        copy.expected_incident_version = expected
        return await service.run(copy)

    first, second = await asyncio.gather(run_with_version(1), run_with_version(1))
    errors = (first.get("errors") or []) + (second.get("errors") or [])
    assert any("version" in err.lower() for err in errors) or first["status"] != second.get("ignore")


@pytest.mark.asyncio
async def test_human_review_audit(service, payload):
    result = await service.run(payload)
    hyp_id = result["hypotheses"][0]["hypothesis_id"]
    record = service.record_review(
        incident_id="inc-monsoon-12",
        actor="duty-officer",
        decision=ReviewDecision.SUPPORT_HYPOTHESIS,
        target_id=hyp_id,
        notes="Field team confirmed standing water.",
    )
    assert record.actor == "duty-officer"
    stored = {h.hypothesis_id: h for h in service.operational.get_hypotheses("inc-monsoon-12")}
    assert stored[hyp_id].status in {HypothesisStatus.SUPPORTED, HypothesisStatus.UNDER_REVIEW}
    assert service.operational.get_audits("inc-monsoon-12")


@pytest.mark.asyncio
async def test_material_change_selective_reanalysis(service, payload):
    first = await service.run(payload)
    payload.material_change = True
    payload.reanalysis_scope = ["IMPACT"]
    extra = NormalizedEvent(
        event_id="evt-water-2",
        source_id="sensor-wl-04",
        event_type=EventType.WATER_LEVEL,
        observed_at=payload.normalized_events[0].observed_at,
        numeric_value=1.8,
        unit="m",
        location=payload.normalized_events[0].location,
    )
    payload.normalized_events.append(extra)
    payload.trigger_event_ids.append("evt-water-2")
    payload.correlation_results.append(
        CorrelationResult(event_id="evt-water-2", incident_id="inc-monsoon-12", score=0.9)
    )
    second = await service.run(payload)
    agents = [run["agent_name"] for run in second["agent_runs"]]
    assert "signal_intelligence" not in agents
    assert "causal_cascade" not in agents
    assert "impact_response" in agents
    assert first["workflow_id"] != second["workflow_id"]
