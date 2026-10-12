"""Event submission and retrieval endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import Depends, APIRouter, Header, Query, Response, status
from pydantic import ValidationError as PydanticValidationError

from app.api.deps import DbSession, RequestId
from app.api.envelope import failure, paginated, success
from app.core.errors import AppError, ErrorDetail, PayloadTooLargeError, ValidationError
from app.core.logging import request_context
from app.core.security import require_write_key
from app.core.timeutil import parse_timestamp
from app.db.repositories.duplicate_repository import DuplicateRepository
from app.db.repositories.event_repository import EventFilter, EventRepository
from app.ingestion.citizen import CitizenReportAdapter
from app.schemas.common import (
    DuplicateDecision,
    Envelope,
    PageParams,
    QualityStatus,
    SourceKind,
    ValidationOutcome,
)
from app.schemas.event import CanonicalEvent, CanonicalEventCreate
from app.schemas.ingestion import RecordOutcome
from app.services.event_service import EventService

__all__ = ["router"]

router = APIRouter(prefix="/events", tags=["events"])


@router.post(
    "",
    response_model=Envelope,
    status_code=status.HTTP_201_CREATED,
    summary="Submit one or more canonical events",
    dependencies=[Depends(require_write_key)],
)
async def submit_events(
    response: Response,
    session: DbSession,
    request_id: RequestId,
    events: list[CanonicalEventCreate] | CanonicalEventCreate,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Envelope:
    """Accept a single canonical event or a batch.

    Requires the write API key. Identity (``event_id``, ``idempotency_key``, ``fingerprint``) is
    derived server-side, so a caller cannot spoof another source's event. Re-submitting the same
    event returns ``duplicate`` and does not create a second canonical event.
    """
    require_write_key(x_api_key)

    settings = _settings()
    batches = events if isinstance(events, list) else [events]
    if not batches:
        raise ValidationError("At least one event is required.")

    # Payload size is enforced before any parsing work is done.
    _enforce_payload_size(batches, settings.max_payload_bytes)

    service = EventService(session)
    accepted: list[str] = []
    duplicates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []

    with request_context(request_id, prefix="evt"):
        for item in batches:
            try:
                canonical = item.to_canonical()
            except (PydanticValidationError, ValidationError, ValueError) as exc:
                rejected.append(_describe_rejection(exc, item))
                continue

            outcome = await service.persist_event(canonical)
            _classify(outcome, accepted, duplicates, rejected, quarantined)

        await session.commit()

    # 201 when at least one new event was created; 200 when the request succeeded but produced
    # only duplicates or rejections (no new canonical event).
    response.status_code = status.HTTP_201_CREATED if accepted else status.HTTP_200_OK
    payload = {
        "submitted": len(batches),
        "accepted": len(accepted),
        "duplicate": len(duplicates),
        "rejected": len(rejected),
        "quarantined": len(quarantined),
        "accepted_event_ids": accepted,
        "duplicates": duplicates,
        "rejections": rejected,
        "quarantined_records": quarantined,
    }
    from app.services.processing_service import auto_process

    processing = await auto_process(list(accepted), trigger="api:events")
    if processing is not None:
        payload["processing"] = processing
    return success(payload, request_id)


@router.get("", response_model=Envelope, summary="Query events with filters and pagination")
async def list_events(
    session: DbSession,
    request_id: RequestId,
    source_id: str | None = Query(default=None),
    source_category: str | None = Query(
        default=None, description="weather | air_quality | traffic | water | citizen | replay"
    ),
    event_type: str | None = Query(default=None),
    source_kind: SourceKind | None = Query(default=None),
    quality_status: QualityStatus | None = Query(default=None),
    is_late: bool | None = Query(default=None, description="Filter late/out-of-order arrivals."),
    event_time_from: datetime | None = Query(default=None),
    event_time_to: datetime | None = Query(default=None),
    latitude_min: float | None = Query(default=None, ge=-90, le=90),
    latitude_max: float | None = Query(default=None, ge=-90, le=90),
    longitude_min: float | None = Query(default=None, ge=-180, le=180),
    longitude_max: float | None = Query(default=None, ge=-180, le=180),
    include_text: bool = Query(
        default=False,
        description="Include citizen report text. Restricted field.",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    order_by: str = Query(default="event_time"),
    descending: bool = Query(default=True),
) -> Envelope:
    """Return a bounded, filtered page of canonical events.

    ``include_text`` defaults to false because citizen report text may contain personal data even
    after PII scrubbing.
    """
    repository = EventRepository(session)
    flt = EventFilter(
        source_id=source_id,
        source_category=source_category,
        event_type=event_type,
        source_kind=source_kind.value if source_kind else None,
        quality_status=quality_status.value if quality_status else None,
        is_late=is_late,
        event_time_from=event_time_from,
        event_time_to=event_time_to,
        latitude_min=latitude_min,
        latitude_max=latitude_max,
        longitude_min=longitude_min,
        longitude_max=longitude_max,
    )
    rows, total = await repository.query(
        flt, limit=page_size, offset=(page - 1) * page_size,
        order_by=order_by, descending=descending,
    )

    service = EventService(session)
    items = [
        service.to_canonical(row).to_response_dict(include_text=include_text) for row in rows
    ]
    return paginated(items, total, page, page_size, request_id)


@router.get("/{event_id}", response_model=Envelope, summary="Retrieve one event and its provenance")
async def get_event(
    event_id: str,
    session: DbSession,
    request_id: RequestId,
    include_text: bool = Query(default=False, description="Include citizen report text."),
) -> Envelope:
    """Return a single canonical event with its lineage.

    Duplicate receipts are included so that a user can see that the event arrived more than once
    without those deliveries being counted as corroboration.
    """
    from app.core.errors import NotFoundError

    repository = EventRepository(session)
    row = await repository.get_by_event_id(event_id)
    if row is None:
        raise NotFoundError(
            f"No event with id '{event_id}'.", details={"event_id": event_id}
        )

    service = EventService(session)
    event = service.to_canonical(row)

    duplicates = DuplicateRepository(session)
    receipts = await duplicates.list_for_event(event_id)

    payload = event.to_response_dict(include_text=include_text)
    payload["provenance"] = {
        "first_run_id": row.first_run_id,
        "first_received_at": row.first_received_at,
        "duplicate_receipt_count": len(receipts),
        "duplicate_receipts": [
            {
                "received_at": r.received_at,
                "decision": r.decision,
                "rule": r.rule,
                "run_id": r.run_id,
                "payload_hash": r.payload_hash,
            }
            for r in receipts
        ],
    }
    payload["late"] = {
        "is_late": row.is_late,
        "note": (
            "This event was received after newer events; its original observation time is "
            "preserved unchanged."
        )
        if row.is_late
        else None,
    }
    return success(payload, request_id)


# --------------------------------------------------------------------- helpers
def _settings():
    from app.core.config import get_settings

    return get_settings()


def _enforce_payload_size(batches: list[CanonicalEventCreate], max_bytes: int) -> None:
    """Reject an oversized submission before doing any further work."""
    total = 0
    for item in batches:
        try:
            total += len(item.model_dump_json().encode("utf-8"))
        except (TypeError, ValueError):
            continue
        if total > max_bytes:
            raise PayloadTooLargeError(
                f"Submitted payload exceeds the {max_bytes}-byte limit. "
                f"Split the batch into smaller requests.",
                details={"limit_bytes": max_bytes},
            )


def _describe_rejection(exc: Exception, item: CanonicalEventCreate) -> dict[str, Any]:
    """Turn an exception into a safe rejection record."""
    if isinstance(exc, AppError):
        return {
            "source_id": item.source_id,
            "source_event_id": item.source_event_id,
            "reason_code": exc.code,
            "message": exc.message,
            "field_errors": exc.field_errors,
        }
    if isinstance(exc, PydanticValidationError):
        return {
            "source_id": item.source_id,
            "source_event_id": item.source_event_id,
            "reason_code": ErrorDetail.MISSING_REQUIRED_FIELD,
            "message": "The event failed schema validation.",
            "field_errors": [
                {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
                for err in exc.errors()
            ],
        }
    return {
        "source_id": item.source_id,
        "source_event_id": item.source_event_id,
        "reason_code": "invalid_payload",
        "message": str(exc)[:300],
        "field_errors": [],
    }


def _classify(
    outcome: RecordOutcome,
    accepted: list[str],
    duplicates: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    quarantined: list[dict[str, Any]],
) -> None:
    """Bucket a persistence outcome into the response lists."""
    if outcome.outcome == ValidationOutcome.ACCEPTED:
        if outcome.event_id:
            accepted.append(outcome.event_id)
    elif outcome.outcome == ValidationOutcome.DUPLICATE:
        duplicates.append(
            {
                "event_id": outcome.event_id,
                "reason_code": outcome.reason_code,
                "message": outcome.message,
                "decision": outcome.duplicate.decision if outcome.duplicate else None,
                "rule": outcome.duplicate.rule if outcome.duplicate else None,
            }
        )
    elif outcome.outcome == ValidationOutcome.QUARANTINED:
        quarantined.append(
            {
                "source_event_id": outcome.source_event_id,
                "reason_code": outcome.reason_code,
                "message": outcome.message,
            }
        )
    else:
        rejected.append(
            {
                "source_event_id": outcome.source_event_id,
                "reason_code": outcome.reason_code,
                "message": outcome.message,
            }
        )
