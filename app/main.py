"""FastAPI application factory and lifespan.

Startup sequence
----------------
1. Configure structured logging (this also registers credentials with the redactor, so no secret
   can reach a log line even if a provider echoes one back).
2. Register the source adapters.
3. Verify database connectivity and create health rows.
4. Optionally start the background poller.

Nothing here performs a live provider call, so starting the application can never consume paid
quota.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import anomalies as anomalies_api
from app.api import crowd as crowd_api
from app.api import traffic_vision as traffic_vision_api
from app.api import events as events_api
from app.api import health as health_api
from app.api import incidents as incidents_api
from app.api import verification as verification_api
from app.api import processing as processing_api
from app.api import reports as reports_api
from app.api import sources as sources_api
from app.api.deps import get_request_id_header
from app.api.envelope import failure
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorDetail
from app.core.logging import configure_logging, get_logger, new_correlation_id, request_context
from app.core.security import redact, redactor
from app.db.session import dispose_engine, get_session_factory
from app.ingestion.providers import registry
from app.schemas.common import Envelope

__all__ = ["create_app", "app"]

logger = get_logger(__name__)

#: HTTP status -> stable error code, so clients can branch without parsing prose.
_HTTP_CODE_NAMES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_failed",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


def _http_code_name(status_code: int) -> str:
    return _HTTP_CODE_NAMES.get(status_code, f"http_{status_code}")

_DESCRIPTION = """
Urban Sentinel — urban incident fusion and causal intelligence.

**Milestone 1: ingestion and canonicalisation.**

Every source (weather, air quality, traffic, water level, citizen report, replay fixture) is
normalised into one versioned canonical event schema with full provenance:

* `event_time` and `ingest_time` are always stored separately, so late and out-of-order arrivals
  remain correct.
* Duplicate deliveries are prevented by database unique constraints and recorded as duplicate
  receipts — never as a second canonical event, and never as extra corroboration.
* A missing reading is never coerced to zero, and a stale or silent feed is never reported as
  safe.
* Replayed and synthetic data is always labelled as such.

Anomaly detection, incident clustering, causal inference, cascade simulation, the evidence graph,
and AI agents are **not implemented** in this milestone.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: logging, adapters, database check, optional scheduler."""
    settings = get_settings()
    configure_logging(settings)
    redactor.register_from_settings(settings)

    from app.ingestion.providers import register_defaults

    register_defaults(registry)
    logger.info(
        "adapters registered",
        extra={"source_ids": registry.ids(), "count": len(registry.all())},
    )

    # --- database readiness -------------------------------------------------
    database_ready = False
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        database_ready = True
        logger.info("database reachable", extra={"dialect": settings.async_database_url.split(":")[0]})
    except Exception as exc:  # noqa: BLE001 - the app must still start and report unready
        logger.error(
            "database unreachable at startup",
            extra={"error_type": type(exc).__name__},
        )

    # --- seed source-health rows so /api/v1/sources/health is useful immediately
    if database_ready:
        try:
            factory = get_session_factory()
            from app.services.source_health import SourceHealthService

            async with factory() as session:
                await SourceHealthService(session).ensure_rows(registry.all())
                await session.commit()
        except Exception:  # noqa: BLE001 - non-fatal
            logger.exception("failed to seed source health rows")

    app.state.database_ready = database_ready
    app.state.settings = settings

    scheduler_task: asyncio.Task | None = None
    if settings.scheduler_enabled:
        scheduler_task = asyncio.create_task(_scheduler_loop(settings))
        logger.info(
            "scheduler started",
            extra={"interval_seconds": settings.scheduler_interval_seconds,
                   "sources": settings.scheduler_sources},
        )
    else:
        logger.info(
            "scheduler disabled",
            extra={"note": "set SCHEDULER_ENABLED=true to enable periodic polling"},
        )

    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
        await dispose_engine()
        logger.info("shutdown complete")


async def _scheduler_loop(settings: Settings) -> None:
    """Periodically poll the configured sources.

    Disabled by default so that a local run can never silently consume a paid quota. Overlapping
    runs of the same source are prevented by the runner.
    """
    from app.services.ingestion_runner import IngestionRunner

    runner = IngestionRunner(get_session_factory(), settings=settings, registry=registry)
    while True:
        try:
            await asyncio.sleep(settings.scheduler_interval_seconds)
            with request_context(new_correlation_id("sched"), prefix="sched"):
                await runner.run_many(settings.scheduler_sources, trigger="schedule")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must survive one bad cycle
            logger.exception("scheduler cycle failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application."""
    current = settings or get_settings()

    application = FastAPI(
        title="Urban Sentinel API",
        version="0.1.0",
        description=_DESCRIPTION,
        lifespan=lifespan,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        contact={"name": "Urban Sentinel"},
    )

    if current.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=current.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )

    # --- correlation-id middleware -----------------------------------------
    @application.middleware("http")
    async def correlation_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        inbound = request.headers.get("X-Request-ID")
        correlation_id = inbound or new_correlation_id("req")
        request.state.correlation_id = correlation_id
        with request_context(correlation_id):
            response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        return response

    # --- error handlers -----------------------------------------------------
    @application.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):  # type: ignore[no-untyped-def]
        request_id = getattr(request.state, "correlation_id", None)
        logger.warning(
            "application error",
            extra={"error_code": exc.code, "status_code": exc.status_code, "path": request.url.path},
        )
        return JSONResponse(
            status_code=exc.status_code, content=failure(exc, request_id).model_dump(mode="json")
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException  # type: ignore[no-untyped-def]
    ):
        """Render FastAPI/Starlette HTTP errors (404, 405, 401) in the standard envelope.

        Without this, an authorisation failure would return FastAPI's default ``{"detail": ...}``
        shape while every other error used the envelope — an inconsistency a client would trip on.
        """
        request_id = getattr(request.state, "correlation_id", None)
        detail = exc.detail

        if isinstance(detail, dict) and "code" in detail:
            error = AppError(
                message=detail.get("message", "Request failed."),
                code=detail.get("code", "http_error"),
                status_code=exc.status_code,
                details=detail.get("details", {}),
                field_errors=detail.get("field_errors", []),
            )
        else:
            error = AppError(
                message=str(detail),
                code=_http_code_name(exc.status_code),
                status_code=exc.status_code,
            )

        logger.info(
            "http error",
            extra={"error_code": error.code, "status_code": exc.status_code,
                   "path": request.url.path},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=failure(error, request_id).model_dump(mode="json"),
            headers=getattr(exc, "headers", None),
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError  # type: ignore[no-untyped-def]
    ):
        request_id = getattr(request.state, "correlation_id", None)
        field_errors = [
            {"field": ".".join(str(p) for p in err.get("loc", [])), "message": err.get("msg", "")}
            for err in exc.errors()
        ]
        error = AppError(
            message="Request validation failed.",
            code="validation_failed",
            status_code=422,
            field_errors=redact(field_errors),
        )
        return JSONResponse(
            status_code=422, content=failure(error, request_id).model_dump(mode="json")
        )

    @application.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
        """Catch-all: never leak a stack trace or a credential to a client."""
        request_id = getattr(request.state, "correlation_id", None)
        logger.exception("unhandled exception", extra={"path": request.url.path})
        error = AppError(
            message="An unexpected internal error occurred.",
            code="internal_error",
            status_code=500,
            retryable=True,
        )
        return JSONResponse(
            status_code=500, content=failure(error, request_id).model_dump(mode="json")
        )

    # --- routers ------------------------------------------------------------
    prefix = current.api_v1_prefix
    application.include_router(health_api.router)
    application.include_router(events_api.router, prefix=prefix)
    application.include_router(reports_api.router, prefix=prefix)
    application.include_router(sources_api.ingest_router, prefix=prefix)
    application.include_router(sources_api.ingestion_router, prefix=prefix)
    application.include_router(sources_api.router, prefix=prefix)
    application.include_router(processing_api.router, prefix=prefix)
    application.include_router(anomalies_api.router, prefix=prefix)
    # Registered before the intelligence layer's /incidents routes; the paths do not overlap.
    application.include_router(incidents_api.router, prefix=prefix)
    application.include_router(verification_api.router, prefix=prefix)
    application.include_router(crowd_api.router, prefix=prefix)
    application.include_router(crowd_api.router, prefix="/api")
    application.include_router(traffic_vision_api.router, prefix=prefix)
    application.include_router(traffic_vision_api.router, prefix="/api")

    _mount_intelligence(application, current)
    return application


def _mount_intelligence(application: FastAPI, settings: Settings) -> None:
    """Mount the multi-agent layer (urban_sentinel/) in-process, if enabled and importable.

    Its routes keep their own absolute paths (``/api/v1/intelligence/*`` and
    ``/api/v1/incidents/{id}/hypotheses|cascade|recommendations|review``). A failure to load it
    never prevents ingestion or deterministic processing from serving.
    """
    from app.integration.intelligence_bridge import set_intelligence_service

    application.state.intelligence = None
    set_intelligence_service(None)
    if not settings.intelligence_enabled:
        logger.info("intelligence layer disabled", extra={"setting": "INTELLIGENCE_ENABLED"})
        return
    try:
        from urban_sentinel.api.incidents import router as intel_incidents_router
        from urban_sentinel.api.intelligence import router as intel_router
        from urban_sentinel.intelligence.service import IntelligenceService

        service = IntelligenceService()
    except Exception as exc:  # noqa: BLE001 - optional layer
        logger.error("intelligence layer failed to load", extra={"error_type": type(exc).__name__})
        return
    application.state.intelligence = service
    set_intelligence_service(service)
    application.include_router(intel_router)
    application.include_router(intel_incidents_router)
    logger.info("intelligence layer mounted",
                extra={"llm_provider": service.llm.provider, "graph": type(service.graph).__name__})


app = create_app()
