"""Citizen report submission.

Privacy rules enforced here
---------------------------
* ``reporter_id`` must be an opaque pseudonymous key — the schema rejects emails and phone
  numbers outright.
* Report text is PII-scrubbed before storage and the response tells the submitter whether
  anything was removed.
* Report text is never returned by read-only endpoints (see ``GET /api/v1/events``).
"""

from __future__ import annotations

from fastapi import Depends, APIRouter, Header, Response, status
from pydantic import ValidationError as PydanticValidationError

from app.api.deps import DbSession, RequestId
from app.api.envelope import success
from app.core.errors import ValidationError
from app.core.logging import request_context
from app.core.security import require_write_key
from app.core.timeutil import utc_now
from app.ingestion.citizen import CitizenReportAdapter
from app.schemas.common import Envelope
from app.schemas.report import CitizenReportAccepted, CitizenReportCreate

__all__ = ["router"]

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post(
    "",
    response_model=Envelope,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a citizen report (unverified observation)",
    dependencies=[Depends(require_write_key)],
)
async def submit_report(
    response: Response,
    session: DbSession,
    request_id: RequestId,
    report: CitizenReportCreate,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Envelope:
    """Accept a citizen report as an unverified canonical event.

    Requires the write API key. The report's observation time is preserved as ``event_time`` and
    the receipt time as ``ingest_time``; the two are never conflated.
    """
    require_write_key(x_api_key)

    adapter = CitizenReportAdapter()
    submitted_at = utc_now()

    with request_context(request_id, source_id=adapter.source_id, prefix="rpt"):
        try:
            event, redacted = adapter.build_event(report, submitted_at=submitted_at)
        except PydanticValidationError as exc:
            raise ValidationError(
                "The report failed validation.",
                field_errors=[
                    {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
                    for err in exc.errors()
                ],
            ) from exc

        from app.services.event_service import EventService

        service = EventService(session)
        outcome = await service.persist_event(event)
        await session.commit()

    from app.schemas.common import ValidationOutcome

    if outcome.outcome == ValidationOutcome.ACCEPTED:
        accepted = CitizenReportAccepted(
            event_id=event.event_id,
            report_category=report.report_category,
            event_type=event.event_type,
            reported_at=event.event_time,
            submitted_at=event.ingest_time,
            redacted=redacted,
        )
        from app.services.processing_service import auto_process

        data = accepted.model_dump(mode="json")
        processing = await auto_process([event.event_id], trigger="api:reports")
        if processing is not None:
            data["processing"] = processing
        return success(data, request_id)

    # A duplicate report is reported as such rather than silently accepted twice: two submissions
    # are not two independent observations.
    response.status_code = status.HTTP_200_OK
    return success(
        {
            "event_id": outcome.event_id,
            "duplicate": True,
            "message": outcome.message,
            "reason_code": outcome.reason_code,
            "report_status": "unverified",
            "redacted": redacted,
        },
        request_id,
    )
