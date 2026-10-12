from __future__ import annotations

from fastapi import FastAPI

from urban_sentinel import SCHEMA_VERSION, __version__
from urban_sentinel.api.incidents import router as incidents_router
from urban_sentinel.api.intelligence import router as intelligence_router
from urban_sentinel.core.config import get_settings
from urban_sentinel.core.logging import configure_logging
from urban_sentinel.intelligence.service import IntelligenceService


def create_app(service: IntelligenceService | None = None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Urban Sentinel Intelligence Layer",
        version=__version__,
        description="Bounded multi-agent incident fusion and cascading-risk analysis.",
    )
    app.state.intelligence = service or IntelligenceService(settings=settings)
    app.include_router(intelligence_router)
    app.include_router(incidents_router)

    @app.get("/health")
    async def health() -> dict:
        intel: IntelligenceService = app.state.intelligence
        return {
            "status": "ok",
            "schema_version": SCHEMA_VERSION,
            "llm": intel.llm.provider,
            "llm_available": intel.llm.available,
            "graph_available": getattr(intel.graph, "available", True),
        }

    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "urban_sentinel.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
