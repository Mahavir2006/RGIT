"""Shared pytest fixtures.

Hard rules for this suite:

* **No network access.** HTTP is mocked at the ``httpx`` transport layer by ``pytest-httpx``.
* **No provider credentials.** Settings come from a controlled environment with test-only values;
  a developer's local secrets can never influence a run and no test can emit them.
* **No PostgreSQL.** Tests run against an isolated in-memory SQLite database, created per test.

Fixture ordering matters: ``test_environment`` sets the environment *before* ``engine`` builds the
engine, so the application and the test fixtures share one cached engine (and therefore one
in-memory database). Two engines would mean two empty databases.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "data" / "samples"

#: Write key used only by the test-suite. Never a real credential.
TEST_WRITE_KEY = "test-write-key-do-not-use-in-production"

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

_ENV_KEYS = (
    "DATABASE_URL", "API_WRITE_KEY", "AUTH_ENABLED", "REPLAY_FIXTURES_DIR",
    "REPLAY_REBASE_TO_NOW", "LOG_LEVEL", "LOG_FORMAT", "SCHEDULER_ENABLED",
    "OPENWEATHER_API_KEY", "OPENAQ_API_KEY", "TOMTOM_API_KEY", "WATER_API_KEY",
    "WEATHER_LAT", "WEATHER_LON", "AQ_LAT", "AQ_LON", "TRAFFIC_SEGMENT_IDS",
    "HTTP_MAX_RETRIES", "HTTP_TIMEOUT_SECONDS",
)


def make_settings(**overrides) -> "Settings":
    """Build isolated settings directly, for unit-level tests that bypass the app."""
    from app.core.config import Settings

    base: dict[str, object] = {
        "app_env": "test",
        "debug": False,
        "database_url": TEST_DATABASE_URL,
        "auth_enabled": True,
        "api_write_key": TEST_WRITE_KEY,
        "api_read_key": None,
        "replay_fixtures_dir": str(SAMPLES_DIR),
        "replay_rebase_to_now": False,
        "log_format": "console",
        "log_level": "CRITICAL",
        "http_max_retries": 1,
        "http_timeout_seconds": 1.0,
        "http_backoff_base_seconds": 0.001,
        "http_backoff_max_seconds": 0.01,
        "scheduler_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


def reset_engines() -> None:
    """Drop the cached engine so the next call rebuilds it."""
    import app.db.session as session_module

    session_module._engine = None  # noqa: SLF001
    session_module._session_factory = None  # noqa: SLF001


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _isolate_environment():
    """Prevent cached settings, engines, or registered secrets leaking between tests."""
    from app.core.config import get_settings
    from app.core.security import redactor

    get_settings.cache_clear()
    reset_engines()
    redactor._values.clear()  # noqa: SLF001
    yield
    get_settings.cache_clear()
    reset_engines()
    redactor._values.clear()  # noqa: SLF001


@pytest.fixture
def test_environment(monkeypatch):
    """Install a controlled environment with test-only values."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("API_WRITE_KEY", TEST_WRITE_KEY)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("REPLAY_FIXTURES_DIR", str(SAMPLES_DIR))
    monkeypatch.setenv("REPLAY_REBASE_TO_NOW", "false")
    monkeypatch.setenv("LOG_LEVEL", "CRITICAL")
    monkeypatch.setenv("LOG_FORMAT", "console")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    from app.core.config import get_settings
    from app.core.security import redactor

    get_settings.cache_clear()
    redactor.register_from_settings(get_settings())
    yield get_settings()


@pytest.fixture
def settings() -> "Settings":
    """Isolated settings for a single unit test."""
    return make_settings()


@pytest.fixture
def write_headers() -> dict[str, str]:
    return {"X-API-Key": TEST_WRITE_KEY}


@pytest.fixture
def samples_dir() -> Path:
    return SAMPLES_DIR


@pytest_asyncio.fixture
async def engine(test_environment):
    """A fresh in-memory database with the schema created, per test."""
    from app.db.base import Base
    from app.db.session import get_engine

    eng = get_engine(test_environment)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator:
    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as s:
        yield s


@pytest.fixture
def client(engine) -> Iterator:
    """TestClient sharing the same engine (and therefore database) as the ``engine`` fixture."""
    from fastapi.testclient import TestClient

    from app.ingestion.providers import register_defaults, registry
    from app.main import create_app

    register_defaults(registry)
    application = create_app()
    with TestClient(application) as test_client:
        yield test_client
