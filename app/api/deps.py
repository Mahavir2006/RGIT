"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.common import PageParams

__all__ = ["DbSession", "PageQuery", "RequestId", "get_request_id_header", "PageParams"]

DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_request_id_header(
    request: Request,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> str | None:
    """Return the request's correlation id.

    Prefers the id the correlation middleware bound to ``request.state`` (generated when the
    client sent none), so ``meta.request_id`` always matches the ``X-Request-ID`` response header.

    ``Header`` must be used as a parameter default: calling it inside the body would return the
    ``Header`` object itself rather than the request's header value.
    """
    return getattr(request.state, "correlation_id", None) or request_id


#: Optional inbound correlation id, used to bind the request's logging context.
RequestId = Annotated[str | None, Depends(get_request_id_header)]

PageQuery = Annotated[PageParams, Depends()]


def pagination(
    page: int = Query(1, ge=1, description="1-indexed page number."),
    page_size: int = Query(50, ge=1, le=200, description="Items per page (max 200)."),
) -> PageParams:
    """Build pagination parameters, bounded to 200 items per page."""
    return PageParams(page=page, page_size=page_size)
