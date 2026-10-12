from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from urban_sentinel.api.main import create_app
from urban_sentinel.core.config import Settings
from urban_sentinel.demo.monsoon import monsoon_payload
from urban_sentinel.intelligence.llm import NullLLM, ScriptedLLM
from urban_sentinel.intelligence.service import IntelligenceService
from urban_sentinel.repositories.graph import InMemoryGraphRepository
from urban_sentinel.repositories.operational import OperationalRepository


@pytest.fixture
def settings() -> Settings:
    return Settings(
        urban_sentinel_review_token="test-token",
        urban_sentinel_llm_provider="none",
        urban_sentinel_llm_timeout_seconds=1.0,
        urban_sentinel_llm_max_retries=1,
    )


@pytest.fixture
def graph() -> InMemoryGraphRepository:
    return InMemoryGraphRepository()


@pytest.fixture
def operational() -> OperationalRepository:
    return OperationalRepository()


@pytest.fixture
def service(settings, graph, operational) -> IntelligenceService:
    return IntelligenceService(
        settings=settings,
        operational=operational,
        graph=graph,
        llm=NullLLM(),
    )


@pytest.fixture
def scripted_llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def client(service) -> TestClient:
    app = create_app(service)
    return TestClient(app)


@pytest.fixture
def payload():
    return monsoon_payload()
