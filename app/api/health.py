"""Liveness and readiness.

``/health`` reports two distinct things, because conflating them hides outages:

* **liveness** — the process is up and serving.
* **readiness** — dependencies (the database) are reachable.

A source being stale or offline does *not* make the API unready: degraded data must remain
queryable, and blanking the dashboard during a provider outage would be exactly the wrong
behaviour.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.api.envelope import success
from app.api.deps import RequestId
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.ingestion.providers import registry
from app.schemas.common import Envelope
from app.schemas.event import SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS

__all__ = ["router", "health_payload"]

router = APIRouter(tags=["health"])

_VERSION = "0.1.0"
_MILESTONE = "1 - ingestion and canonicalisation"


@router.get(
    "/health",
    response_model=Envelope,
    summary="Liveness and dependency readiness",
)
async def health(request: Request, request_id: RequestId) -> Envelope:
    """Return liveness, database readiness, and connector configuration status."""
    return success(await health_payload(), request_id)


async def health_payload() -> dict[str, Any]:
    """Assemble the health document. Separated so the scheduler can reuse it."""
    settings = get_settings()

    database: dict[str, Any] = {"status": "unknown", "dialect": None, "error": None}
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        database["status"] = "ready"
    except Exception as exc:  # noqa: BLE001 - report, never crash the health endpoint
        database["status"] = "unavailable"
        # Type name only: a connection string or driver message could embed credentials.
        database["error"] = type(exc).__name__

    adapters = registry.all()
    connectors = [
        {
            "source_id": adapter.source_id,
            "category": adapter.category.value,
            "provider": adapter.provider,
            "mode": adapter.effective_mode(),
            "runnable": adapter.can_run_live() or adapter.supports_replay,
            "missing_settings": adapter.missing_settings(),
        }
        for adapter in adapters
    ]

    live_configured = [c["source_id"] for c in connectors if c["mode"] == "live"]
    missing = sorted({
        name for adapter in adapters for name in adapter.missing_settings()
    })

    from app.integration.intelligence_bridge import get_intelligence_service

    intel = get_intelligence_service()
    return {
        "service": settings.app_name,
        "version": _VERSION,
        "milestone": _MILESTONE,
        "environment": settings.app_env,
        "status": "ok" if database["status"] == "ready" else "degraded",
        "liveness": "up",
        "readiness": "ready" if database["status"] == "ready" else "not_ready",
        "database": database,
        "canonical_schema": {
            "version": SCHEMA_VERSION,
            "supported_versions": sorted(SUPPORTED_SCHEMA_VERSIONS),
        },
        "connectors": {
            "total": len(connectors),
            "live_configured": live_configured,
            "replay_only": [
                c["source_id"] for c in connectors if c["mode"] != "live"
            ],
            "missing_settings": missing,
        },
        "implemented": {
            "ingestion": True,
            "canonical_schema": True,
            "idempotency": True,
            "source_health": True,
            "deterministic_processing": True,
            "anomaly_detection": True,
            "candidate_matching": True,
            # Provided by the multi-agent layer (urban_sentinel/) only when it is mounted.
            "incident_fusion": intel is not None,
            "causal_inference": intel is not None,
            "cascade_simulation": intel is not None,
            "ai_agents": intel is not None,
            # Neo4j is optional; without it the intelligence layer uses an in-memory graph.
            "evidence_graph": bool(intel is not None and type(intel.graph).__name__.startswith("Neo4j")),
        },
        "intelligence_layer": {
            "mounted": intel is not None,
            "llm_provider": getattr(getattr(intel, "llm", None), "provider", None),
            "llm_available": bool(getattr(getattr(intel, "llm", None), "available", False)),
            "graph_backend": type(intel.graph).__name__ if intel is not None else None,
            "note": "hypothesis scores are heuristics; LLM optional with deterministic fallback",
        },
    }
