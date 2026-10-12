"""Image authenticity triage endpoint for the Verification console page."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.security import require_read_key
from app.services.image_verification import MAX_IMAGE_BYTES, analyze_image

router = APIRouter(prefix="/verification", tags=["verification"])


@router.post("/image", summary="Triage an uploaded image with XproAI and C2PA")
async def verify_image(
    image: UploadFile = File(...),
    _api_key: str | None = Depends(require_read_key),
) -> dict:
    if not (image.content_type or "").lower().startswith("image/"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Upload an image file.")
    raw = await image.read(MAX_IMAGE_BYTES + 1)
    await image.close()
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image exceeds the 15 MB upload limit.")
    settings = get_settings()
    if not settings.xproai_checkpoint:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="XproAI checkpoint is not configured.")
    try:
        return await run_in_threadpool(analyze_image, raw, image.content_type, settings.xproai_checkpoint, settings.c2pa_settings_file)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
