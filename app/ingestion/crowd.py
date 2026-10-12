"""Crowd-density vision adapter using the ONNX head-detection model (best_crowdd.onnx).

Provides:
- Ingestion provider: `CrowdDensityAdapter` (SourceAdapter) emitting `crowd_density_observed` events.
- On-demand video analysis helper with frame-by-frame head detection, density timeline, and spike tracking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

try:
    import onnxruntime as ort
except ImportError:
    ort = None  # type: ignore[assignment]

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.timeutil import utc_now
from app.ingestion.base import AdapterOutcome, AdapterResult, FetchRequest, SourceAdapter
from app.schemas.common import LocationPrecision, MeasurementAggregation, QualityFlag, SourceCategory, SourceKind
from app.schemas.event import EventLocation, EventType, Measurement, build_canonical_event

__all__ = ["CrowdDensityAdapter", "CrowdDetector", "get_crowd_detector"]

logger = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = REPO_ROOT / "best_crowdd.onnx"
DEFAULT_VIDEO_PATH = REPO_ROOT / "protest.mp4"


def letterbox(img: np.ndarray, new_shape: int = 832) -> tuple[np.ndarray, float, tuple[int, int]]:
    """Resize *img* with preserved aspect ratio and pad to new_shape x new_shape."""
    h, w = img.shape[:2]
    scale = new_shape / max(h, w)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    pad_w = (new_shape - new_w) // 2
    pad_h = (new_shape - new_h) // 2
    padded = cv2.copyMakeBorder(
        resized,
        pad_h,
        new_shape - new_h - pad_h,
        pad_w,
        new_shape - new_w - pad_w,
        cv2.BORDER_CONSTANT,
        value=(114, 114, 114),
    )
    return padded, scale, (pad_w, pad_h)


def xywh_to_xyxy(boxes: np.ndarray) -> np.ndarray:
    """Convert [cx, cy, w, h] to [x1, y1, x2, y2]."""
    out = np.empty_like(boxes)
    out[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
    out[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
    out[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
    out[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
    return out


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> np.ndarray:
    """Greedy Non-Maximum Suppression."""
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-7)
        inds = np.where(iou <= iou_thr)[0]
        order = order[inds + 1]
    return np.array(keep, dtype=np.int64)


class CrowdDetector:
    """Lazy-loaded ONNX runtime session for YOLOv8 head detection."""

    def __init__(self, model_path: str | Path | None = None) -> None:
        self.model_path = Path(model_path or DEFAULT_MODEL_PATH)
        self._session: ort.InferenceSession | None = None
        self._input_name: str | None = None

    @property
    def session(self) -> Any:
        if ort is None:
            raise RuntimeError("onnxruntime is required for crowd head detection.")
        if self._session is None:
            if not self.model_path.exists():
                raise FileNotFoundError(f"ONNX crowd model not found at {self.model_path}")
            opts = ort.SessionOptions()
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(
                str(self.model_path),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
            self._input_name = self._session.get_inputs()[0].name
        return self._session

    def detect(
        self,
        frame: np.ndarray,
        conf_thr: float = 0.35,
        iou_thr: float = 0.45,
        imgsz: int = 832,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Detect heads in a single BGR image.

        Returns:
            (boxes_xyxy, scores) scaled back to original image dimensions.
        """
        padded, scale, (pad_w, pad_h) = letterbox(frame, imgsz)
        blob = padded[:, :, ::-1].astype(np.float32) / 255.0
        blob = blob.transpose(2, 0, 1)[np.newaxis]

        sess = self.session
        input_name = self._input_name or sess.get_inputs()[0].name
        raw = sess.run(None, {input_name: blob})[0]  # shape: (1, 5, anchors)
        preds = raw[0].T  # shape: (anchors, 5)

        boxes_xywh = preds[:, :4]
        scores = preds[:, 4]

        mask = scores >= conf_thr
        if not np.any(mask):
            return np.empty((0, 4), dtype=np.float32), np.empty((0,), dtype=np.float32)

        boxes_xywh = boxes_xywh[mask]
        scores = scores[mask]
        boxes_xyxy = xywh_to_xyxy(boxes_xywh)

        keep = nms(boxes_xyxy, scores, iou_thr)
        if len(keep) == 0:
            return np.empty((0, 4), dtype=np.float32), np.empty((0,), dtype=np.float32)

        kept_boxes = boxes_xyxy[keep]
        kept_scores = scores[keep]

        # Rescale back to original image coordinates
        kept_boxes[:, [0, 2]] = (kept_boxes[:, [0, 2]] - pad_w) / scale
        kept_boxes[:, [1, 3]] = (kept_boxes[:, [1, 3]] - pad_h) / scale

        h, w = frame.shape[:2]
        kept_boxes[:, [0, 2]] = np.clip(kept_boxes[:, [0, 2]], 0, w)
        kept_boxes[:, [1, 3]] = np.clip(kept_boxes[:, [1, 3]], 0, h)

        return kept_boxes, kept_scores


_DETECTOR_SINGLETON: CrowdDetector | None = None


def get_crowd_detector() -> CrowdDetector:
    """Return the application-wide singleton CrowdDetector."""
    global _DETECTOR_SINGLETON
    if _DETECTOR_SINGLETON is None:
        _DETECTOR_SINGLETON = CrowdDetector()
    return _DETECTOR_SINGLETON


class CrowdDensityAdapter(SourceAdapter):
    """Computer vision crowd-density adapter.

    Emits ``CROWD_DENSITY_OBSERVED`` events with quantitative ``head_count`` measurements.
    """

    source_id = "crowd.live"
    display_name = "Crowd Density & Vision Intelligence"
    category = SourceCategory.CROWD
    provider = "onnx_head_counter"
    supports_live = True
    supports_replay = True
    unit_notes = "Head counts are integer quantities of detected persons per frame/time window."
    caveats = (
        "Head detection accuracy depends on camera angle, elevation, and lighting.",
        "Rapid surges (>2x rolling average) trigger crowd-spike anomalies and feed signal hypotheses.",
        "Single camera feeds represent local gathering density, not city-wide crowd totals.",
    )

    def __init__(self, settings: Settings | None = None, detector: CrowdDetector | None = None) -> None:
        self.settings = settings or get_settings()
        self.detector = detector or get_crowd_detector()

    def required_settings(self) -> list[str]:
        return []

    def build_event(
        self,
        head_count: int,
        *,
        observed_at: datetime | None = None,
        location: EventLocation | None = None,
        camera_id: str = "CAM-CROWD-01",
        frame_idx: int = 0,
        source_kind: SourceKind = SourceKind.LIVE_API,
        details: dict[str, Any] | None = None,
    ) -> Any:
        """Convert a detected head count into a CanonicalEvent."""
        now = utc_now()
        event_time = observed_at or now

        measurements = [
            Measurement(
                name="head_count",
                value=float(head_count),
                unit="count",
                period_seconds=1,
                aggregation=MeasurementAggregation.INSTANTANEOUS,
            )
        ]

        flags: list[QualityFlag] = []
        if location is None:
            flags.append(QualityFlag.LOCATION_MISSING)

        payload_data = {
            "camera_id": camera_id,
            "frame_idx": frame_idx,
            "provider": self.provider,
            "model": "best_crowdd.onnx",
            **(details or {}),
        }

        return build_canonical_event(
            source_id=self.source_id,
            source_event_id=f"{camera_id}-{event_time.strftime('%Y%m%d%H%M%S')}-{frame_idx}",
            event_type=EventType.CROWD_DENSITY_OBSERVED,
            event_time=event_time,
            ingest_time=now,
            location=location,
            measurements=measurements,
            source_kind=source_kind,
            quality_flags=flags,
            text=f"Vision detector counted {head_count} individuals at camera {camera_id}.",
            payload=payload_data,
        )

    def analyze_video(
        self,
        video_path: str | Path,
        *,
        sample_step: int = 10,
        conf_thr: float = 0.35,
        iou_thr: float = 0.45,
        camera_id: str = "CAM-CROWD-PROTEST",
        location: EventLocation | None = None,
    ) -> dict[str, Any]:
        """Analyze a video file and return timeline, summary statistics, and anomaly spikes."""
        path = Path(video_path)
        if not path.exists():
            raise NotFoundError(f"Video file not found at {path}")

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video {path}")

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        frames_analyzed = 0
        timeline: list[dict[str, Any]] = []
        counts: list[int] = []
        rolling_averages: list[float] = []
        spikes: list[dict[str, Any]] = []

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % sample_step == 0:
                boxes, scores = self.detector.detect(frame, conf_thr=conf_thr, iou_thr=iou_thr)
                count = len(boxes)
                counts.append(count)
                frames_analyzed += 1

                # Calculate rolling average of previous counts
                window = counts[-10:]
                rolling_avg = sum(window) / len(window)
                rolling_averages.append(round(rolling_avg, 2))

                timestamp_sec = round(frame_idx / fps, 2)
                is_spike = False

                # Spike detection: count > 2x rolling avg (if baseline >= 5)
                if len(counts) >= 4:
                    prev_window = counts[-11:-1]
                    prev_avg = sum(prev_window) / len(prev_window) if prev_window else 0
                    if prev_avg >= 5.0 and count >= 2.0 * prev_avg:
                        is_spike = True
                        spikes.append({
                            "frame_idx": frame_idx,
                            "timestamp_sec": timestamp_sec,
                            "count": count,
                            "rolling_average": round(prev_avg, 2),
                            "multiplier": round(count / prev_avg, 2),
                        })

                # Top boxes for sample serialization (limited to 50 for JSON efficiency)
                box_records = [
                    {
                        "x1": round(float(b[0]), 1),
                        "y1": round(float(b[1]), 1),
                        "x2": round(float(b[2]), 1),
                        "y2": round(float(b[3]), 1),
                        "score": round(float(s), 3),
                    }
                    for b, s in zip(boxes[:50], scores[:50])
                ]

                timeline.append({
                    "frame_idx": frame_idx,
                    "timestamp_sec": timestamp_sec,
                    "count": count,
                    "rolling_avg": round(rolling_avg, 2),
                    "is_spike": is_spike,
                    "boxes_sample": box_records[:15],
                })

            frame_idx += 1

        cap.release()

        peak_count = max(counts) if counts else 0
        min_count = min(counts) if counts else 0
        avg_count = round(sum(counts) / len(counts), 1) if counts else 0.0

        return {
            "video_metadata": {
                "file_name": path.name,
                "total_frames": total_frames,
                "fps": round(fps, 2),
                "resolution": f"{width}x{height}",
                "duration_sec": round(total_frames / fps, 2),
                "sample_step": sample_step,
                "frames_analyzed": frames_analyzed,
            },
            "summary": {
                "peak_count": peak_count,
                "min_count": min_count,
                "average_count": avg_count,
                "total_spikes_detected": len(spikes),
                "highest_density_timestamp_sec": timeline[counts.index(peak_count)]["timestamp_sec"] if counts else 0,
            },
            "spikes": spikes,
            "timeline": timeline,
        }

    async def fetch_events(self, request: FetchRequest) -> AdapterResult:
        """Process demo video frames into CanonicalEvents."""
        started = utc_now()
        outcome = AdapterOutcome()

        video_path = DEFAULT_VIDEO_PATH
        if not video_path.exists():
            return outcome.empty_result(self.source_id, started)

        analysis = self.analyze_video(video_path, sample_step=30)
        location = EventLocation(
            latitude=18.9220,
            longitude=72.8347,
            name="Gateway of India / Colaba Plaza",
            precision=LocationPrecision.POINT,
        )

        for entry in analysis.get("timeline", []):
            event = self.build_event(
                head_count=entry["count"],
                camera_id="CAM-CROWD-PROTEST",
                frame_idx=entry["frame_idx"],
                location=location,
                source_kind=SourceKind.REPLAY,
                details={
                    "timestamp_sec": entry["timestamp_sec"],
                    "is_spike": entry["is_spike"],
                },
            )
            outcome.accept(event)

        return outcome.complete(self.source_id, started)
