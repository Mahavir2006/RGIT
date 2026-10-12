"""Tests for computer vision edge adapters and API endpoints (Crowd and Traffic).

Verifies:
- CrowdDensityAdapter initialization, metadata, and status checks.
- TrafficVisionAdapter initialization, metadata, vehicle class handling, and status checks.
- API endpoints: /api/crowd/status and /api/traffic-vision/status.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.ingestion.base import FetchRequest
from app.ingestion.crowd import CrowdDensityAdapter
from app.ingestion.traffic_vision import TrafficVisionAdapter, VEHICLE_CLASSES
from app.main import app
from tests.conftest import make_settings


def _request(source_id: str = "test") -> FetchRequest:
    return FetchRequest(source_id=source_id, correlation_id="test-vision")


@pytest.mark.asyncio
async def test_crowd_adapter_initialization_and_metadata():
    settings = make_settings()
    adapter = CrowdDensityAdapter(settings)
    assert adapter.source_id == "video.crowd_density"
    assert adapter.source_metadata.source_id == "video.crowd_density"
    assert adapter.source_metadata.display_name == "Edge Video Crowd Density"


@pytest.mark.asyncio
async def test_traffic_adapter_initialization_and_classes():
    settings = make_settings()
    adapter = TrafficVisionAdapter(settings)
    assert adapter.source_id == "video.traffic_flow"
    assert adapter.source_metadata.source_id == "video.traffic_flow"
    assert adapter.source_metadata.display_name == "Edge Video Traffic Vision"
    assert len(VEHICLE_CLASSES) == 8
    assert "car" in VEHICLE_CLASSES
    assert "bus" in VEHICLE_CLASSES
    assert "truck" in VEHICLE_CLASSES


@pytest.mark.asyncio
async def test_crowd_status_api_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/crowd/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        assert "detector" in data.get("data", {})
        detector_info = data["data"]["detector"]
        assert "model_path" in detector_info
        assert "model_available" in detector_info


@pytest.mark.asyncio
async def test_traffic_status_api_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/traffic-vision/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        assert "detector" in data.get("data", {})
        detector_info = data["data"]["detector"]
        assert "model_path" in detector_info
        assert "classes" in detector_info
        assert "car" in detector_info["classes"]
