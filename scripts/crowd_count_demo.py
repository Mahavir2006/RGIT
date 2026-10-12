"""Crowd-counting demo — run best_crowdd.onnx on protest.mp4.

Outputs an annotated MP4 with bounding boxes around every detected head and a
live head-count overlay in the top-left corner.

Usage (from the repo root):
    python scripts/crowd_count_demo.py

Optional flags:
    --model   path to the ONNX file  (default: best_crowdd.onnx)
    --video   path to the input video (default: protest.mp4)
    --output  path for the annotated video (default: data/crowd_output.mp4)
    --conf    confidence threshold     (default: 0.35)
    --iou     IoU threshold for NMS    (default: 0.45)
    --imgsz   inference size           (default: 832)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

# ── CLI ──────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Crowd-count demo (ONNX + OpenCV)")
    ap.add_argument("--model", default=str(ROOT / "best_crowdd.onnx"))
    ap.add_argument("--video", default=str(ROOT / "protest.mp4"))
    ap.add_argument("--output", default=str(ROOT / "data" / "crowd_output.mp4"))
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--iou", type=float, default=0.45)
    ap.add_argument("--imgsz", type=int, default=832)
    return ap.parse_args()


# ── Pre-processing ───────────────────────────────────────────────────────────


def letterbox(
    img: np.ndarray, new_shape: int = 832
) -> tuple[np.ndarray, float, tuple[int, int]]:
    """Resize *img* with preserved aspect ratio, pad to *new_shape* × *new_shape*.

    Returns (padded_image, scale_factor, (pad_w, pad_h)).
    """
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


def preprocess(img: np.ndarray, imgsz: int) -> tuple[np.ndarray, float, tuple[int, int]]:
    """BGR frame → NCHW float32 tensor ready for the ONNX session."""
    padded, scale, (pw, ph) = letterbox(img, imgsz)
    blob = padded[:, :, ::-1].astype(np.float32) / 255.0  # BGR→RGB, 0-1
    blob = blob.transpose(2, 0, 1)[np.newaxis]  # HWC→NCHW
    return blob, scale, (pw, ph)


# ── Post-processing ─────────────────────────────────────────────────────────


def xywh_to_xyxy(boxes: np.ndarray) -> np.ndarray:
    """Convert [cx, cy, w, h] → [x1, y1, x2, y2]."""
    out = np.empty_like(boxes)
    out[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
    out[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
    out[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
    out[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
    return out


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> np.ndarray:
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


def postprocess(
    output: np.ndarray,
    scale: float,
    pad: tuple[int, int],
    conf_thr: float,
    iou_thr: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Parse raw ONNX output → (boxes_xyxy, confidences) in original-frame coords.

    YOLOv8 ONNX output shape: [1, 5, N]  (4 box coords + 1 class score per anchor).
    """
    preds = output[0]  # remove batch dim → [5, N]
    preds = preds.T  # → [N, 5]

    # Columns: cx, cy, w, h, score_class0
    scores = preds[:, 4]
    mask = scores >= conf_thr
    preds = preds[mask]
    scores = scores[mask]

    if len(preds) == 0:
        return np.empty((0, 4), dtype=np.float32), np.empty((0,), dtype=np.float32)

    boxes = xywh_to_xyxy(preds[:, :4])

    # Undo letterbox transform → original frame coordinates
    pw, ph = pad
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - pw) / scale
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - ph) / scale

    # NMS
    keep = nms(boxes, scores, iou_thr)
    return boxes[keep], scores[keep]


# ── Drawing ──────────────────────────────────────────────────────────────────

BOX_COLOR = (0, 255, 120)  # bright green
TEXT_BG = (20, 20, 20)
TEXT_FG = (0, 255, 255)


def draw_results(
    frame: np.ndarray,
    boxes: np.ndarray,
    scores: np.ndarray,
    frame_idx: int,
    fps_val: float,
) -> np.ndarray:
    """Annotate *frame* in-place: bounding boxes + head-count overlay."""
    count = len(boxes)
    h, w = frame.shape[:2]

    # Draw each detection
    for (x1, y1, x2, y2), conf in zip(boxes.astype(int), scores):
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        cv2.rectangle(frame, (x1, y1), (x2, y2), BOX_COLOR, 2)
        label = f"{conf:.0%}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), BOX_COLOR, -1)
        cv2.putText(
            frame, label, (x1 + 2, y1 - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1, cv2.LINE_AA,
        )

    # Overlay panel
    panel_text = f"Heads: {count}   Frame: {frame_idx}   FPS: {fps_val:.1f}"
    (tw, th), _ = cv2.getTextSize(panel_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
    cv2.rectangle(frame, (8, 8), (tw + 24, th + 24), TEXT_BG, -1)
    cv2.putText(
        frame, panel_text, (16, th + 16),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, TEXT_FG, 2, cv2.LINE_AA,
    )
    return frame


# ── Main loop ────────────────────────────────────────────────────────────────


def main() -> None:
    args = parse_args()

    # Validate paths
    if not os.path.isfile(args.model):
        sys.exit(f"Model not found: {args.model}")
    if not os.path.isfile(args.video):
        sys.exit(f"Video not found: {args.video}")

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    # Load ONNX session
    print(f"Loading model: {args.model}")
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    sess = ort.InferenceSession(args.model, providers=providers)
    input_name = sess.get_inputs()[0].name
    actual_provider = sess.get_providers()[0]
    print(f"  Provider: {actual_provider}")

    # Open video
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.exit(f"Cannot open video: {args.video}")
    orig_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"  Video: {vw}×{vh} @ {orig_fps:.0f} FPS, {total_frames} frames")

    # Writer
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(args.output, fourcc, orig_fps, (vw, vh))
    if not writer.isOpened():
        sys.exit(f"Cannot create output video: {args.output}")

    frame_idx = 0
    total_heads = 0
    peak_heads = 0
    t0 = time.perf_counter()

    print(f"\nProcessing (conf>={args.conf}, IoU<={args.iou}, size={args.imgsz})...")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1

        # Inference
        blob, scale, pad = preprocess(frame, args.imgsz)
        output = sess.run(None, {input_name: blob})[0]
        boxes, scores = postprocess(output, scale, pad, args.conf, args.iou)

        count = len(boxes)
        total_heads += count
        peak_heads = max(peak_heads, count)

        elapsed = time.perf_counter() - t0
        fps_val = frame_idx / elapsed if elapsed > 0 else 0

        # Draw and write
        annotated = draw_results(frame, boxes, scores, frame_idx, fps_val)
        writer.write(annotated)

        # Progress
        if frame_idx % 30 == 0 or frame_idx == total_frames:
            pct = frame_idx / total_frames * 100
            print(
                f"  [{frame_idx:>4}/{total_frames}] {pct:5.1f}%  "
                f"heads={count:>3}  peak={peak_heads:>3}  "
                f"avg={total_heads / frame_idx:.1f}  fps={fps_val:.1f}"
            )

    cap.release()
    writer.release()

    elapsed = time.perf_counter() - t0
    avg_heads = total_heads / frame_idx if frame_idx else 0
    print(f"\n{'=' * 56}")
    print(f"  Done in {elapsed:.1f}s ({frame_idx / elapsed:.1f} FPS)")
    print(f"  Frames processed : {frame_idx}")
    print(f"  Peak head count  : {peak_heads}")
    print(f"  Average head count: {avg_heads:.1f}")
    print(f"  Output saved to  : {args.output}")
    print(f"{'=' * 56}")


if __name__ == "__main__":
    main()
