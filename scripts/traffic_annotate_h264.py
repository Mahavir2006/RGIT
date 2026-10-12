"""Annotate traffic.mp4 with vehicle detection bounding boxes using improved_best.onnx.

Outputs a browser-compatible H.264 MP4 with per-class coloured bounding boxes,
vehicle counts by class, congestion metrics, and a live overlay.

Usage (from repo root):
    python scripts/traffic_annotate_h264.py
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "improved_best.onnx"
VIDEO = ROOT / "traffic.mp4"
OUTPUT = ROOT / "data" / "traffic_output.mp4"

CONF_THR = 0.35
IOU_THR = 0.45
IMGSZ = 640

# Class names from model metadata
CLASS_NAMES = {0: "auto", 1: "bus", 2: "car", 3: "lcv", 4: "motorcycle", 5: "multiaxle", 6: "tractor", 7: "truck"}
NUM_CLASSES = len(CLASS_NAMES)

# Per-class colours (BGR)
CLASS_COLORS = {
    0: (0, 200, 255),    # auto — amber
    1: (0, 120, 255),    # bus — orange
    2: (255, 180, 0),    # car — cyan
    3: (180, 255, 0),    # lcv — lime
    4: (255, 0, 180),    # motorcycle — magenta
    5: (0, 0, 255),      # multiaxle — red
    6: (80, 200, 120),   # tractor — green
    7: (255, 100, 100),  # truck — blue-ish
}


# ── Pre-processing ───────────────────────────────────────────────────────────

def letterbox(img, new_shape=640):
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


def preprocess(img, imgsz):
    padded, scale, (pw, ph) = letterbox(img, imgsz)
    blob = padded[:, :, ::-1].astype(np.float32) / 255.0
    blob = blob.transpose(2, 0, 1)[np.newaxis]
    return blob, scale, (pw, ph)


# ── Post-processing ─────────────────────────────────────────────────────────

def xywh_to_xyxy(boxes):
    out = np.empty_like(boxes)
    out[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
    out[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
    out[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
    out[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
    return out


def nms(boxes, scores, iou_thr):
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
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


def postprocess(output, scale, pad, conf_thr, iou_thr):
    """Parse YOLOv8 multi-class output: [1, 4+num_classes, N] → boxes, scores, class_ids."""
    preds = output[0].T  # [N, 4+num_classes]

    # Per-class scores are columns 4 onwards
    class_scores = preds[:, 4:]  # [N, num_classes]
    class_ids = class_scores.argmax(axis=1)
    max_scores = class_scores[np.arange(len(class_ids)), class_ids]

    mask = max_scores >= conf_thr
    preds = preds[mask]
    max_scores = max_scores[mask]
    class_ids = class_ids[mask]

    if len(preds) == 0:
        return (np.empty((0, 4), dtype=np.float32),
                np.empty((0,), dtype=np.float32),
                np.empty((0,), dtype=np.int32))

    boxes = xywh_to_xyxy(preds[:, :4])
    pw, ph = pad
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - pw) / scale
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - ph) / scale

    # Class-aware NMS
    keep = nms(boxes, max_scores, iou_thr)
    return boxes[keep], max_scores[keep], class_ids[keep]


# ── Drawing ──────────────────────────────────────────────────────────────────

def draw_results(frame, boxes, scores, class_ids, frame_idx, fps_val, class_counts):
    h, w = frame.shape[:2]
    total = len(boxes)

    for (x1, y1, x2, y2), conf, cls_id in zip(boxes.astype(int), scores, class_ids):
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        color = CLASS_COLORS.get(int(cls_id), (200, 200, 200))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"{CLASS_NAMES.get(int(cls_id), '?')} {conf:.0%}"
        (tw, th_), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        cv2.rectangle(frame, (x1, y1 - th_ - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(frame, label, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1, cv2.LINE_AA)

    # Top-left overlay panel
    panel_h = 30 + 18 * min(NUM_CLASSES, 4)
    cv2.rectangle(frame, (8, 8), (300, panel_h), (20, 20, 20), -1)
    cv2.putText(frame, f"Vehicles: {total}   Frame: {frame_idx}   FPS: {fps_val:.1f}",
                (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)

    # Per-class mini breakdown
    y_off = 46
    for cls_id in sorted(class_counts.keys()):
        if class_counts[cls_id] > 0:
            color = CLASS_COLORS.get(cls_id, (200, 200, 200))
            text = f"{CLASS_NAMES.get(cls_id, '?')}: {class_counts[cls_id]}"
            cv2.putText(frame, text, (20, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
            y_off += 16

    # Congestion indicator (top-right)
    congestion = "LOW"
    cong_color = (0, 255, 0)
    if total > 30:
        congestion = "CRITICAL"
        cong_color = (0, 0, 255)
    elif total > 20:
        congestion = "HIGH"
        cong_color = (0, 100, 255)
    elif total > 10:
        congestion = "MODERATE"
        cong_color = (0, 200, 255)

    cv2.rectangle(frame, (w - 180, 8), (w - 8, 40), (20, 20, 20), -1)
    cv2.putText(frame, f"Congestion: {congestion}", (w - 172, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, cong_color, 1, cv2.LINE_AA)

    return frame


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not MODEL.exists():
        sys.exit(f"Model not found: {MODEL}")
    if not VIDEO.exists():
        sys.exit(f"Video not found: {VIDEO}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading ONNX model: {MODEL.name} (8 classes: {', '.join(CLASS_NAMES.values())})")
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    sess = ort.InferenceSession(str(MODEL), providers=providers)
    input_name = sess.get_inputs()[0].name
    print(f"  Provider: {sess.get_providers()[0]}")

    cap = cv2.VideoCapture(str(VIDEO))
    if not cap.isOpened():
        sys.exit(f"Cannot open video: {VIDEO}")

    orig_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"  Video: {vw}x{vh} @ {orig_fps:.0f} FPS, {total_frames} frames")

    # Try browser-compatible codecs
    codecs_to_try = [
        ("avc1", "H.264 (avc1)"),
        ("H264", "H.264"),
        ("X264", "x264"),
        ("mp4v", "MPEG-4 Part 2 (WARNING: may not play in browsers)"),
    ]

    writer = None
    codec_used = ""
    for fourcc_str, desc in codecs_to_try:
        fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
        test_writer = cv2.VideoWriter(str(OUTPUT), fourcc, orig_fps, (vw, vh))
        if test_writer.isOpened():
            writer = test_writer
            codec_used = desc
            print(f"  Codec: {desc} ({fourcc_str})")
            break
        test_writer.release()

    if writer is None:
        sys.exit("Cannot create output video with any supported codec")

    frame_idx = 0
    total_vehicles = 0
    peak_vehicles = 0
    cumulative_class_counts = {i: 0 for i in range(NUM_CLASSES)}
    timeline_data = []
    t0 = time.perf_counter()

    print(f"\nProcessing (conf>={CONF_THR}, IoU<={IOU_THR}, size={IMGSZ})...")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1

        blob, scale, pad = preprocess(frame, IMGSZ)
        output = sess.run(None, {input_name: blob})[0]
        boxes, scores, class_ids = postprocess(output, scale, pad, CONF_THR, IOU_THR)

        count = len(boxes)
        total_vehicles += count
        peak_vehicles = max(peak_vehicles, count)

        # Per-class counts for this frame
        frame_class_counts = {i: 0 for i in range(NUM_CLASSES)}
        for cls_id in class_ids:
            frame_class_counts[int(cls_id)] += 1
            cumulative_class_counts[int(cls_id)] += 1

        # Record timeline every 10 frames
        if frame_idx % 10 == 1 or frame_idx == total_frames:
            timestamp_sec = round(frame_idx / orig_fps, 2)
            timeline_data.append({
                "frame_idx": frame_idx,
                "timestamp_sec": timestamp_sec,
                "total_count": count,
                "class_counts": dict(frame_class_counts),
            })

        elapsed = time.perf_counter() - t0
        fps_val = frame_idx / elapsed if elapsed > 0 else 0

        annotated = draw_results(frame, boxes, scores, class_ids, frame_idx, fps_val, frame_class_counts)
        writer.write(annotated)

        if frame_idx % 30 == 0 or frame_idx == total_frames:
            pct = frame_idx / total_frames * 100
            top_classes = ", ".join(
                f"{CLASS_NAMES[k]}={v}" for k, v in sorted(frame_class_counts.items()) if v > 0
            )
            print(f"  [{frame_idx:>4}/{total_frames}] {pct:5.1f}%  "
                  f"vehicles={count:>3}  peak={peak_vehicles:>3}  "
                  f"fps={fps_val:.1f}  [{top_classes}]")

    cap.release()
    writer.release()
    elapsed = time.perf_counter() - t0

    print(f"\n{'='*60}")
    print(f"  Done in {elapsed:.1f}s ({frame_idx / elapsed:.1f} FPS)")
    print(f"  Peak vehicle count : {peak_vehicles}")
    print(f"  Average per frame  : {total_vehicles / frame_idx:.1f}")
    print(f"  Output saved to    : {OUTPUT}")
    print(f"\n  Class breakdown (cumulative across all frames):")
    for cls_id, name in CLASS_NAMES.items():
        if cumulative_class_counts[cls_id] > 0:
            print(f"    {name:>12}: {cumulative_class_counts[cls_id]}")

    # Copy to public serving directories
    destinations = [
        ROOT / "public" / "assets" / "traffic" / "traffic_output.mp4",
        ROOT / "src" / "console" / "public" / "assets" / "traffic" / "traffic_output.mp4",
    ]
    for dest in destinations:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(OUTPUT, dest)
        print(f"  Copied to: {dest.relative_to(ROOT)}")

    # Also copy the raw video for the "Raw Feed" toggle
    raw_destinations = [
        ROOT / "public" / "assets" / "traffic" / "traffic.mp4",
        ROOT / "src" / "console" / "public" / "assets" / "traffic" / "traffic.mp4",
    ]
    for dest in raw_destinations:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(VIDEO, dest)

    print(f"{'='*60}")


if __name__ == "__main__":
    main()
