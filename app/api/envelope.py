"""Shared response-envelope helpers.

Every endpoint returns the same envelope shape so clients can parse uniformly, and every error —
including unhandled ones — is redacted before it leaves the process.
"""

from __future__ import annotations

import math
from typing import Any

from app.core.errors import AppError
from app.core.security import redact
from app.core.timeutil import utc_now
from app.schemas.common import Envelope, ErrorBody, PaginationMeta, ResponseMeta

__all__ = ["success", "failure", "paginated", "error_body"]


def success(
    data: Any, request_id: str | None = None, *, meta_extra: dict[str, Any] | None = None
) -> Envelope:
    """Wrap a successful payload."""
    meta = ResponseMeta(request_id=request_id, generated_at=utc_now())
    if meta_extra:
        for key, value in meta_extra.items():
            setattr(meta, key, value)
    return Envelope.ok(data=data, meta=meta)


def failure(
    error: AppError, request_id: str | None = None, *, status_code: int | None = None
) -> Envelope:
    """Wrap an application error, redacting any embedded detail."""
    return Envelope(
        data=None,
        meta=ResponseMeta(request_id=request_id, generated_at=utc_now()),
        error=error_body(error),
    )


def error_body(error: AppError) -> ErrorBody:
    """Build a redacted error body from an application error."""
    return ErrorBody(
        code=error.code,
        # The message is scrubbed because an adapter may have interpolated provider text.
        message=redact(error.message),
        field_errors=redact(error.field_errors),
        details=redact(error.details),
        retryable=error.retryable,
    )


def paginated(
    items: list[Any],
    total: int,
    page: int,
    page_size: int,
    request_id: str | None = None,
) -> Envelope:
    """Wrap a page of results with pagination metadata."""
    total_pages = max(1, math.ceil(total / page_size)) if page_size else 1
    return success(
        items,
        request_id,
        meta_extra={
            "pagination": PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_previous=page > 1,
            )
        },
    )
