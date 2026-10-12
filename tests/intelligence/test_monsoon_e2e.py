from __future__ import annotations

import pytest

from urban_sentinel.demo.monsoon import run_demo
from urban_sentinel.domain.models import HypothesisStatus


@pytest.mark.asyncio
async def test_monsoon_end_to_end_scenario():
    result = await run_demo()
    claims = [h["claim"] for h in result["hypotheses"]]
    assert any("waterlogging" in claim.lower() for claim in claims)
    assert any("traffic" in claim.lower() for claim in claims)
    assert all(h["status"] in {s.value for s in HypothesisStatus} for h in result["hypotheses"])
    flood = next(h for h in result["hypotheses"] if "waterlogging" in h["claim"].lower())
    assert "evt-water-1" in flood["supporting_event_ids"] or "evt-rain-1" in flood["supporting_event_ids"]
    assert result["cascade_scenarios"]
    scenario = result["cascade_scenarios"][0]
    assert scenario["simulated"] is True
    assert "hospital-er" in scenario["affected_asset_ids"] or any(
        "hospital-er" in path["asset_ids"] for path in scenario["dependency_paths"]
    )
    actions = result["candidate_actions"]
    assert actions
    assert all(item["approval_required"] is True for item in actions)
    assert any("caveat" in " ".join(item["assumptions"]).lower() or item["approval_required"] for item in actions)
    summary = (result.get("operator_summary") or "").lower()
    assert "severity" in summary
    offline_gap = " ".join(result["evidence_gaps"]).lower()
    assert "offline" in offline_gap or "sensor" in offline_gap
