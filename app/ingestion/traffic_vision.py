"""Traffic vision adapter using the ONNX vehicle detection model (improved_best.onnx).

Provides:
- Ingestion provider: `TrafficVisionAdapter` (SourceAdapter) emitting `traffic_flow_observed` events.
- On-demand video analysis helper with frame-by-frame vehicle detection, per-class counts,
  congestion timeline, and flow anomaly tracking.
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

__all__ = ["TrafficVisionAdapter", "TrafficDetector", "get_traffic_detector"]

logger = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = REPO_ROOT / "improved_best.onnx"
DEFAULT_VIDEO_PATH = REPO_ROOT / "traffic.mp4"

# Class names from ONNX metadata
CLASS_NAMES = {0: "auto", 1: "bus", 2: "car", 3: "lcv", 4: "motorcycle", 5: "multiaxle", 6: "tractor", 7: "truck"}
NUM_CLASSES = len(CLASS_NAMES)

# Congestion thresholds (total vehicle count per frame)
CONGESTION_THRESHOLDS = {"low": 0, "moderate": 10, "high": 20, "critical": 30}


def letterbox(img: "np.ndarray", new_shape: int = 640) -> tuple["np.ndarray", float, tuple[int, int]]:
    """Resize *img* with preserved aspect ratio and pad to new_shape x new_shape."""
    h, w = img.shape[:2]
    scale = new_shape / max(h, w)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    pad_w = (new_shape - new_w) // 2
    pad_h = (new_shape - new_h) // 2
    padded = cv2.copyMakeBorder(
        resized, pad_h, new_shape - new_h - pad_h,
        pad_w, new_shape - new_w - pad_w,
        cv2.BORDER_CONSTANT, value=(114, 114, 114),
    )
    return padded, scale, (pad_w, pad_h)


def preprocess(img: "np.ndarray", imgsz: int = 640) -> tuple["np.ndarray", float, tuple[int, int]]:
    """BGR frame → NCHW float32 tensor ready for the ONNX session."""
    padded, scale, (pw, ph) = letterbox(img, imgsz)
    blob = padded[:, :, ::-1].astype(np.float32) / 255.0
    blob = blob.transpose(2, 0, 1)[np.newaxis]
    return blob, scale, (pw, ph)


def xywh_to_xyxy(boxes: "np.ndarray") -> "np.ndarray":
    """Convert [cx, cy, w, h] → [x1, y1, x2, y2]."""
    out = np.empty_like(boxes)
    out[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
    out[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
    out[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
    out[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
    return out


def nms(boxes: "np.ndarray", scores: "np.ndarray", iou_thr: float) -> "np.ndarray":
    """Greedy NMS, returns kept indices."""
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
        order = order[1:][iou <= iou_thr]
    return np.array(keep, dtype=int)


def postprocess_traffic(
    output: "np.ndarray",
    scale: float,
    pad: tuple[int, int],
    conf_thr: float,
    iou_thr: float,
) -> tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
    """Parse YOLOv8 multi-class output → (boxes_xyxy, confidences, class_ids)."""
    preds = output[0].T  # [N, 4+num_classes]

    class_scores = preds[:, 4:]  # [N, num_classes]
    class_ids = class_scores.argmax(axis=1)
    max_scores = class_scores[np.arange(len(class_ids)), class_ids]

    mask = max_scores >= conf_thr
    preds, max_scores, class_ids = preds[mask], max_scores[mask], class_ids[mask]

    if len(preds) == 0:
        return (np.empty((0, 4), dtype=np.float32),
                np.empty((0,), dtype=np.float32),
                np.empty((0,), dtype=np.int32))

    boxes = xywh_to_xyxy(preds[:, :4])
    pw, ph = pad
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - pw) / scale
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - ph) / scale

    keep = nms(boxes, max_scores, iou_thr)
    return boxes[keep], max_scores[keep], class_ids[keep]


class TrafficDetector:
    """Singleton ONNX vehicle detection session for improved_best.onnx."""

    def __init__(self, model_path: Path | None = None, imgsz: int = 640) -> None:
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.imgsz = imgsz
        self._session: ort.InferenceSession | None = None
        self._input_name: str | None = None

    def _ensure_session(self) -> None:
        if self._session is not None:
            return
        if ort is None:
            raise RuntimeError("onnxruntime is required for traffic vehicle detection.")
        if not self.model_path.exists():
            raise FileNotFoundError(f"ONNX traffic model not found at {self.model_path}")
        self._session = ort.InferenceSession(
            str(self.model_path),
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        self._input_name = self._session.get_inputs()[0].name
        logger.info("traffic_detector_loaded", model=str(self.model_path), provider=self._session.get_providers()[0])

    def detect_frame(
        self, frame: "np.ndarray", conf_thr: float = 0.35, iou_thr: float = 0.45
    ) -> tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
        """Run detection on a single BGR frame → (boxes, scores, class_ids)."""
        self._ensure_session()
        blob, scale, pad = preprocess(frame, self.imgsz)
        output = self._session.run(None, {self._input_name: blob})[0]
        return postprocess_traffic(output, scale, pad, conf_thr, iou_thr)


_DETECTOR_SINGLETON: TrafficDetector | None = None


def get_traffic_detector() -> TrafficDetector:
    """Return the application-wide singleton TrafficDetector."""
    global _DETECTOR_SINGLETON
    if _DETECTOR_SINGLETON is None:
        _DETECTOR_SINGLETON = TrafficDetector()
    return _DETECTOR_SINGLETON


def _congestion_level(total_count: int) -> str:
    """Map total vehicle count to a congestion level string."""
    if total_count >= CONGESTION_THRESHOLDS["critical"]:
        return "critical"
    elif total_count >= CONGESTION_THRESHOLDS["high"]:
        return "high"
    elif total_count >= CONGESTION_THRESHOLDS["moderate"]:
        return "moderate"
    return "low"


class TrafficVisionAdapter(SourceAdapter):
    """Computer vision traffic flow adapter.

    Emits ``TRAFFIC_FLOW_OBSERVED`` events with quantitative vehicle count measurements
    per class and congestion-level assessments from CCTV or recorded video feeds.
    """

    source_id = "traffic_vision.live"
    display_name = "Traffic Flow & Vehicle Intelligence"
    category = SourceCategory.TRAFFIC
    kind = SourceKind.LIVE_API
    caveats = (
        "Vehicle detection uses the improved_best.onnx YOLOv8 model (8 classes: auto, bus, car, lcv, motorcycle, multiaxle, tractor, truck).",
        "Congestion is estimated from per-frame vehicle counts; actual flow speed requires calibrated tracking.",
        "Single camera feeds represent local intersection density, not corridor-wide traffic state.",
    )

    def __init__(self, settings: Settings | None = None, detector: TrafficDetector | None = None) -> None:
        self.settings = settings or get_settings()
        self.detector = detector or get_traffic_detector()

    def fetch(self, request: FetchRequest) -> Generator[AdapterResult, None, None]:
        """Yield a single traffic event from a video frame capture."""
        yield AdapterResult(outcome=AdapterOutcome.ACCEPTED, events=[], notes=["Traffic vision adapter — use analyze_video() for batch processing."])

    def analyze_video(
        self,
        video_path: Path | None = None,
        sample_step: int = 10,
        conf_thr: float = 0.35,
        iou_thr: float = 0.45,
        camera_id: str = "CAM-TRAFFIC-01",
    ) -> dict[str, Any]:
        """Analyze a video file frame-by-frame for vehicle detection.

        Returns a dictionary with video metadata, per-frame timeline with class breakdowns,
        congestion levels, peak counts, and anomaly spikes.
        """
        if cv2 is None or np is None:
            raise RuntimeError("opencv-python and numpy are required for video analysis.")

        target = video_path or DEFAULT_VIDEO_PATH
        if not target.exists():
            raise NotFoundError(f"Video file not found: {target}")

        cap = cv2.VideoCapture(str(target))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {target}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration_sec = round(total_frames / fps, 2) if fps > 0 else 0

        timeline: list[dict[str, Any]] = []
        all_counts: list[int] = []
        peak_count = 0
        peak_timestamp = 0.0
        cumulative_class: dict[int, int] = {i: 0 for i in range(NUM_CLASSES)}
        rolling_window: list[int] = []
        spikes: list[dict[str, Any]] = []
        congestion_timeline: list[str] = []

        frame_idx = 0
        frames_analyzed = 0

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame_idx += 1

            if (frame_idx - 1) % sample_step != 0:
                continue

            frames_analyzed += 1
            boxes, scores, class_ids = self.detector.detect_frame(frame, conf_thr, iou_thr)

            total = len(boxes)
            all_counts.append(total)
            timestamp_sec = round(frame_idx / fps, 2)

            # Per-class breakdown
            frame_classes: dict[str, int] = {}
            for cls_id in class_ids:
                name = CLASS_NAMES.get(int(cls_id), "unknown")
                frame_classes[name] = frame_classes.get(name, 0) + 1
                cumulative_class[int(cls_id)] = cumulative_class.get(int(cls_id), 0) + 1

            # Peak tracking
            if total > peak_count:
                peak_count = total
                peak_timestamp = timestamp_sec

            # Rolling average for spike detection
            rolling_window.append(total)
            if len(rolling_window) > 10:
                rolling_window.pop(0)
            rolling_avg = round(sum(rolling_window) / len(rolling_window), 1)

            # Congestion level
            congestion = _congestion_level(total)
            congestion_timeline.append(congestion)

            # Spike detection (>2x rolling average)
            is_spike = len(rolling_window) >= 3 and rolling_avg > 0 and total > 2 * rolling_avg

            if is_spike:
                spikes.append({
                    "frame_idx": frame_idx,
                    "timestamp_sec": timestamp_sec,
                    "count": total,
                    "rolling_average": rolling_avg,
                    "multiplier": round(total / rolling_avg, 2),
                    "congestion": congestion,
                })

            timeline.append({
                "frame_idx": frame_idx,
                "timestamp_sec": timestamp_sec,
                "total_count": total,
                "class_counts": frame_classes,
                "rolling_avg": rolling_avg,
                "congestion": congestion,
                "is_spike": is_spike,
            })

        cap.release()

        avg_count = round(sum(all_counts) / len(all_counts), 1) if all_counts else 0

        # Aggregate class summary
        class_summary = {CLASS_NAMES[k]: v for k, v in cumulative_class.items() if v > 0}

        # Dominant congestion level
        if congestion_timeline:
            from collections import Counter
            cong_counter = Counter(congestion_timeline)
            dominant_congestion = cong_counter.most_common(1)[0][0]
        else:
            dominant_congestion = "unknown"

        return {
            "video_metadata": {
                "file_name": target.name,
                "total_frames": total_frames,
                "fps": fps,
                "resolution": f"{vw}x{vh}",
                "duration_sec": duration_sec,
                "sample_step": sample_step,
                "frames_analyzed": frames_analyzed,
            },
            "summary": {
                "peak_vehicle_count": peak_count,
                "min_vehicle_count": min(all_counts) if all_counts else 0,
                "average_vehicle_count": avg_count,
                "total_spikes_detected": len(spikes),
                "highest_density_timestamp_sec": peak_timestamp,
                "dominant_congestion": dominant_congestion,
                "class_totals": class_summary,
            },
            "spikes": spikes,
            "timeline": timeline,
        }
