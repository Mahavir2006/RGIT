"""Re-annotate protest.mp4 with browser-compatible H.264 output.

The original crowd_count_demo.py used the `mp4v` (MPEG-4 Part 2) codec which
browsers cannot decode in <video> tags. This script uses the `avc1` fourcc
(H.264) so the output plays natively in all modern browsers.

Usage (from repo root):
    python scripts/crowd_annotate_h264.py
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
MODEL = ROOT / "best_crowdd.onnx"
VIDEO = ROOT / "protest.mp4"
OUTPUT = ROOT / "data" / "crowd_output.mp4"

CONF_THR = 0.35
IOU_THR = 0.45
IMGSZ = 832

# ── Pre-processing ───────────────────────────────────────────────────────────

def letterbox(img, new_shape=832):
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
    preds = output[0].T
    scores = preds[:, 4]
    mask = scores >= conf_thr
    preds, scores = preds[mask], scores[mask]
    if len(preds) == 0:
        return np.empty((0, 4), dtype=np.float32), np.empty((0,), dtype=np.float32)
    boxes = xywh_to_xyxy(preds[:, :4])
    pw, ph = pad
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - pw) / scale
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - ph) / scale
    keep = nms(boxes, scores, iou_thr)
    return boxes[keep], scores[keep]


# ── Drawing ──────────────────────────────────────────────────────────────────

BOX_COLOR = (0, 255, 120)
TEXT_BG = (20, 20, 20)
TEXT_FG = (0, 255, 255)

def draw_results(frame, boxes, scores, frame_idx, fps_val):
    count = len(boxes)
    h, w = frame.shape[:2]
    for (x1, y1, x2, y2), conf in zip(boxes.astype(int), scores):
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        cv2.rectangle(frame, (x1, y1), (x2, y2), BOX_COLOR, 2)
        label = f"{conf:.0%}"
        (tw, th_), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        cv2.rectangle(frame, (x1, y1 - th_ - 6), (x1 + tw + 4, y1), BOX_COLOR, -1)
        cv2.putText(frame, label, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1, cv2.LINE_AA)
    panel_text = f"Heads: {count}   Frame: {frame_idx}   FPS: {fps_val:.1f}"
    (tw, th_), _ = cv2.getTextSize(panel_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
    cv2.rectangle(frame, (8, 8), (tw + 24, th_ + 24), TEXT_BG, -1)
    cv2.putText(frame, panel_text, (16, th_ + 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, TEXT_FG, 2, cv2.LINE_AA)
    return frame


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not MODEL.exists():
        sys.exit(f"Model not found: {MODEL}")
    if not VIDEO.exists():
        sys.exit(f"Video not found: {VIDEO}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading ONNX model: {MODEL.name}")
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

    # Try H.264 codecs that browsers can play, fall back to mp4v + transcode note
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
    total_heads = 0
    peak_heads = 0
    t0 = time.perf_counter()
    print(f"\nProcessing (conf>={CONF_THR}, IoU<={IOU_THR}, size={IMGSZ})...")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        blob, scale, pad = preprocess(frame, IMGSZ)
        output = sess.run(None, {input_name: blob})[0]
        boxes, scores = postprocess(output, scale, pad, CONF_THR, IOU_THR)
        count = len(boxes)
        total_heads += count
        peak_heads = max(peak_heads, count)
        elapsed = time.perf_counter() - t0
        fps_val = frame_idx / elapsed if elapsed > 0 else 0
        annotated = draw_results(frame, boxes, scores, frame_idx, fps_val)
        writer.write(annotated)
        if frame_idx % 30 == 0 or frame_idx == total_frames:
            pct = frame_idx / total_frames * 100
            print(f"  [{frame_idx:>4}/{total_frames}] {pct:5.1f}%  "
                  f"heads={count:>3}  peak={peak_heads:>3}  "
                  f"avg={total_heads / frame_idx:.1f}  fps={fps_val:.1f}")

    cap.release()
    writer.release()
    elapsed = time.perf_counter() - t0
    print(f"\n{'='*56}")
    print(f"  Done in {elapsed:.1f}s ({frame_idx / elapsed:.1f} FPS)")
    print(f"  Peak head count  : {peak_heads}")
    print(f"  Output saved to  : {OUTPUT}")

    # Copy to public serving directories
    destinations = [
        ROOT / "public" / "assets" / "crowd" / "crowd_output.mp4",
        ROOT / "src" / "console" / "public" / "assets" / "crowd" / "crowd_output.mp4",
    ]
    for dest in destinations:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(OUTPUT, dest)
        print(f"  Copied to: {dest.relative_to(ROOT)}")

    print(f"{'='*56}")

    if "MPEG-4 Part 2" in codec_used:
        print("\n⚠  The video was written with mp4v codec which browsers may not play.")
        print("   Install ffmpeg and run:")
        print(f'   ffmpeg -i "{OUTPUT}" -c:v libx264 -preset fast -crf 23 -c:a copy "{OUTPUT.with_stem("crowd_output_h264")}"')


if __name__ == "__main__":
    main()
