from __future__ import annotations

import pytest

from urban_sentinel.domain.models import ReviewDecision


@pytest.mark.asyncio
async def test_analyze_and_workflow_endpoints(client, service, payload):
    response = client.post(
        "/api/v1/intelligence/analyze/inc-monsoon-12",
        json={"payload": payload.model_dump(mode="json"), "wait": True},
    )
    assert response.status_code == 200, response.text
    workflow_id = response.json()["workflow_id"]
    fetched = client.get(f"/api/v1/intelligence/workflows/{workflow_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["workflow_id"] == workflow_id
    assert "errors" in body


@pytest.mark.asyncio
async def test_incident_read_and_review_auth(client, service, payload):
    await service.run(payload)
    hyps = client.get("/api/v1/incidents/inc-monsoon-12/hypotheses")
    assert hyps.status_code == 200
    assert hyps.json()["hypotheses"]
    cascade = client.get("/api/v1/incidents/inc-monsoon-12/cascade")
    assert cascade.status_code == 200
    recs = client.get("/api/v1/incidents/inc-monsoon-12/recommendations")
    assert recs.status_code == 200
    denied = client.post(
        "/api/v1/incidents/inc-monsoon-12/review",
        json={"decision": ReviewDecision.REQUEST_MORE_EVIDENCE.value},
    )
    assert denied.status_code == 401
    hyp_id = hyps.json()["hypotheses"][0]["hypothesis_id"]
    allowed = client.post(
        "/api/v1/incidents/inc-monsoon-12/review",
        json={
            "decision": ReviewDecision.SUPPORT_HYPOTHESIS.value,
            "target_id": hyp_id,
            "actor": "chief",
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["audit"]["actor"] == "reviewer"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
