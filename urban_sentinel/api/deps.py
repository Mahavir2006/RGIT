from __future__ import annotations

from fastapi import Header, HTTPException, Request, status

from urban_sentinel.intelligence.service import IntelligenceService


def get_service(request: Request) -> IntelligenceService:
    service = getattr(request.app.state, "intelligence", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Intelligence service is not configured")
    return service


def require_reviewer(request: Request, authorization: str | None = Header(default=None)) -> str:
    settings = request.app.state.intelligence.settings
    expected = f"Bearer {settings.review_token}"
    if not authorization or authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Review endpoint requires a valid bearer token",
        )
    return "reviewer"
