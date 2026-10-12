"""Crowd density analysis endpoint.

Accepts video files or video references and executes ONNX-based head detection,
returning per-frame crowd counts, density timelines, rolling averages, and surge spike anomalies.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import RequestId
from app.api.envelope import success
from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.ingestion.crowd import DEFAULT_MODEL_PATH, DEFAULT_VIDEO_PATH, CrowdDensityAdapter, get_crowd_detector
from app.schemas.common import Envelope

__all__ = ["router"]

logger = get_logger(__name__)

router = APIRouter(prefix="/crowd", tags=["crowd"])


@router.get("/video", summary="Stream demo or annotated crowd video")
async def stream_crowd_video(annotated: bool = Query(default=True)) -> FileResponse:
    """Stream raw or AI-annotated crowd video with HTTP range support."""
    repo_root = DEFAULT_MODEL_PATH.parent
    path = repo_root / "data" / "crowd_output.mp4" if annotated else DEFAULT_VIDEO_PATH
    if not path.exists():
        path = DEFAULT_VIDEO_PATH
    if not path.exists():
        raise ValidationError(f"Video file not found at {path}")
    return FileResponse(str(path), media_type="video/mp4")


@router.get("/status", response_model=Envelope, summary="Check crowd model readiness")
async def crowd_status(request_id: RequestId) -> Envelope:
    """Return model status, default video availability, and runtime parameters."""
    detector = get_crowd_detector()
    model_exists = DEFAULT_MODEL_PATH.exists()
    video_exists = DEFAULT_VIDEO_PATH.exists()

    session_loaded = detector._session is not None
    return success(
        {
            "model_path": str(DEFAULT_MODEL_PATH),
            "model_ready": model_exists,
            "session_initialized": session_loaded,
            "demo_video_path": str(DEFAULT_VIDEO_PATH),
            "demo_video_ready": video_exists,
            "model_input_size": 832,
            "target_classes": ["head"],
        },
        request_id,
    )


@router.post("/analyze", response_model=Envelope, summary="Analyze video for crowd density")
async def analyze_crowd_video(
    request_id: RequestId,
    video: UploadFile | None = File(default=None),
    video_path: str | None = Form(default=None),
    sample_step: int = Form(default=10),
    conf_thr: float = Form(default=0.35),
    iou_thr: float = Form(default=0.45),
    camera_id: str = Form(default="CAM-CROWD-PROTEST"),
) -> Envelope:
    """Analyze a video file or bundled fixture to produce a crowd count timeline.

    If no video is uploaded, the bundled `protest.mp4` fixture is analyzed.
    Returns per-frame head counts, rolling average timeline, peak density, and
    surge anomalies (>2x rolling average).
    """
    adapter = CrowdDensityAdapter()
    temp_target: Path | None = None

    try:
        if video is not None and video.filename:
            # Handle uploaded video file
            suffix = Path(video.filename).suffix or ".mp4"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                temp_target = Path(tmp.name)
                shutil.copyfileobj(video.file, tmp)
            target_path = temp_target
        elif video_path:
            target_path = Path(video_path)
            if not target_path.exists():
                raise ValidationError(f"Specified video_path does not exist: {video_path}")
        else:
            # Default to the project's bundled demo video
            target_path = DEFAULT_VIDEO_PATH
            if not target_path.exists():
                raise ValidationError("No video uploaded and bundled protest.mp4 not found.")

        # Execute video analysis
        analysis = adapter.analyze_video(
            video_path=target_path,
            sample_step=max(1, min(sample_step, 60)),
            conf_thr=max(0.1, min(conf_thr, 0.9)),
            iou_thr=max(0.1, min(iou_thr, 0.9)),
            camera_id=camera_id,
        )

        return success(analysis, request_id)

    finally:
        # Clean up temporary uploaded file if created
        if temp_target and temp_target.exists():
            try:
                temp_target.unlink()
            except OSError:
                pass
