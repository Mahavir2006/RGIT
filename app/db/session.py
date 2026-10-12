"""Async SQLAlchemy engine and session management.

PostgreSQL is the preferred store (asyncpg). SQLite is supported so the application and the test
suite can run before a database has been provisioned.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

__all__ = ["get_engine", "get_session_factory", "session_scope", "get_db", "dispose_engine"]

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _engine_kwargs(settings: Settings) -> dict[str, Any]:
    """Build engine arguments appropriate to the configured dialect."""
    url = settings.async_database_url
    kwargs: dict[str, Any] = {"echo": settings.db_echo, "future": True}

    if url.startswith("sqlite"):
        # SQLite has no meaningful pool sizing; a NullPool plus StaticPool for memory DBs keeps
        # tests isolated from one another.
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs["poolclass"] = NullPool
            kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update({
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout,
            "pool_pre_ping": True,
        })
    return kwargs


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine, _session_factory
    if _engine is None:
        current = settings or get_settings()
        url = current.async_database_url
        logger.info(
            "database engine initialised",
            extra={"dialect": url.split(":", 1)[0], "using_default_url": current.database_url is None},
        )
        _engine = create_async_engine(url, **_engine_kwargs(current))
        _session_factory = async_sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a session with commit/rollback handled by the caller."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager committing on success and rolling back on error."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the engine. Called from application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("database engine disposed")
    _engine = None
    _session_factory = None
