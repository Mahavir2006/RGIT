"""Optional XproAI v3 image triage plus C2PA manifest validation.

The supplied checkpoint is the retired XproAI-Net CNN. Its score is exposed as
a review signal only; neither a model score nor missing C2PA data establishes
that an image is genuine.
"""

from __future__ import annotations

import io
import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
DECISION_THRESHOLD = 0.5
_INFERENCE_LOCK = threading.Lock()
_C2PA_SETTINGS_LOCK = threading.Lock()
_C2PA_SETTINGS_LOADED: str | None = None


def _model_classes():
    try:
        import torch
        import torch.nn as nn
    except ImportError as exc:
        raise RuntimeError("Image verification dependencies are missing; install urban-sentinel[image-verification].") from exc

    class ConvBlock(nn.Module):
        def __init__(self, in_ch: int, out_ch: int):
            super().__init__()
            self.block = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False), nn.BatchNorm2d(out_ch), nn.ReLU(inplace=True),
                nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False), nn.BatchNorm2d(out_ch), nn.ReLU(inplace=True),
                nn.MaxPool2d(2, 2),
            )

        def forward(self, x):
            return self.block(x)

    class XproAINet(nn.Module):
        def __init__(self):
            super().__init__()
            self.block1 = ConvBlock(3, 32)
            self.block2 = ConvBlock(32, 64)
            self.block3 = ConvBlock(64, 128)
            self.block4 = ConvBlock(128, 256)
            self.gap = nn.AdaptiveAvgPool2d(1)
            self.classifier = nn.Sequential(nn.Flatten(), nn.Linear(256, 128), nn.ReLU(inplace=True), nn.Dropout(0.25), nn.Linear(128, 1))

        def forward(self, x):
            return self.classifier(self.gap(self.block4(self.block3(self.block2(self.block1(x))))))

    return torch, XproAINet


@lru_cache(maxsize=2)
def _load_model(checkpoint_path: str, modified_ns: int):
    torch, model_class = _model_classes()
    from torchvision import transforms

    path = Path(checkpoint_path)
    if not path.is_file():
        raise RuntimeError(f"XproAI checkpoint was not found: {path}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    checkpoint = torch.load(path, map_location=device, weights_only=True)
    state = checkpoint.get("model_state") if isinstance(checkpoint, dict) else None
    if not isinstance(state, dict):
        raise RuntimeError("Checkpoint is not the expected XproAI v3 model_state format.")
    model = model_class().to(device)
    model.load_state_dict(state, strict=True)
    model.eval()
    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
    ])
    threshold = float(checkpoint.get("decision_threshold", DECISION_THRESHOLD))
    return torch, model, transform, device, threshold, checkpoint


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def inspect_c2pa(raw: bytes, mime_type: str, settings_file: str | None = None) -> dict[str, Any]:
    """Validate the embedded C2PA manifest using the C2PA SDK when available."""
    try:
        import c2pa
    except ImportError:
        return {"status": "unavailable", "manifest_present": None, "validation_state": None,
                "ai_origin_claim": None, "message": "Install the image-verification extra to validate C2PA manifests."}

    try:
        global _C2PA_SETTINGS_LOADED
        settings_path = settings_file
        if settings_path and _C2PA_SETTINGS_LOADED != settings_path:
            with _C2PA_SETTINGS_LOCK:
                if _C2PA_SETTINGS_LOADED != settings_path:
                    settings = json.loads(Path(settings_path).read_text(encoding="utf-8"))
                    c2pa.load_settings(settings)
                    _C2PA_SETTINGS_LOADED = settings_path
        stream = io.BytesIO(raw)
        with c2pa.Reader(mime_type, stream) as reader:
            present = bool(reader.is_embedded())
            state = reader.get_validation_state()
            if not present:
                return {"status": "not_found", "manifest_present": False, "validation_state": state,
                        "ai_origin_claim": None, "message": "No embedded C2PA manifest found; absence is not evidence of authenticity."}
            active = reader.get_active_manifest()
            if isinstance(active, str):
                active = json.loads(active)
            actions = [node for node in _walk(active) if node.get("label") in {"c2pa.actions", "c2pa.actions.v2"}]
            source_types = [str(action.get("digitalSourceType", "")) for node in actions
                            for action in (node.get("data", {}).get("actions", []) if isinstance(node.get("data"), dict) else [])
                            if isinstance(action, dict)]
            ai_claim = any("trainedAlgorithmicMedia" in item or "compositeWithTrainedAlgorithmicMedia" in item for item in source_types)
            verified = str(state or "").lower() == "valid"
            return {
                "status": "validated" if verified else ("validation_failed" if state else "validation_unavailable"),
                "manifest_present": True,
                "validation_state": state,
                "ai_origin_claim": bool(ai_claim) if verified else None,
                "declared_ai_origin": bool(ai_claim),
                "message": ("C2PA signature and trust validation passed." if verified else
                            "Manifest found, but the SDK did not report a valid trusted signature; its claims are unverified."),
            }
    except Exception as exc:  # malformed or unsupported containers are a provenance gap, not an app failure
        # The SDK raises instead of returning a Reader when a valid ordinary image has no
        # JUMBF/C2PA block. Treat that as "not found", never as a failed signature.
        if type(exc).__name__ == "C2paError" and any(
            marker in str(exc).lower() for marker in ("manifestnotfound", "no jumbf data")
        ):
            return {"status": "not_found", "manifest_present": False, "validation_state": None,
                    "ai_origin_claim": None, "message": "No embedded C2PA manifest found; absence is not evidence of authenticity."}
        return {"status": "unavailable", "manifest_present": None, "validation_state": None,
                "ai_origin_claim": None, "message": f"C2PA validation could not be completed ({type(exc).__name__})."}


def analyze_image(raw: bytes, mime_type: str, checkpoint_path: str, c2pa_settings_file: str | None = None) -> dict[str, Any]:
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB upload limit.")
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Image verification dependencies are missing; install urban-sentinel[image-verification].") from exc
    try:
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        with Image.open(io.BytesIO(raw)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("Decoded image exceeds the 30 megapixel limit.")
            source.verify()
        with Image.open(io.BytesIO(raw)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("Decoded image exceeds the 30 megapixel limit.")
            source.load()
            image_format = source.format
            image = source.convert("RGB")
    except Exception as exc:
        if isinstance(exc, ValueError) and "30 megapixel" in str(exc):
            raise
        raise ValueError("Upload is not a supported, decodable image.") from exc

    actual_mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "TIFF": "image/tiff", "BMP": "image/bmp"}.get(image_format, mime_type)
    c2pa = inspect_c2pa(raw, actual_mime, c2pa_settings_file)
    path = Path(checkpoint_path)
    model_result: dict[str, Any]
    try:
        if not path.is_file():
            raise RuntimeError(f"XproAI checkpoint was not found: {path}")
        torch, model, transform, device, threshold, checkpoint = _load_model(str(path), path.stat().st_mtime_ns)
        with _INFERENCE_LOCK, torch.inference_mode():
            probability = float(torch.sigmoid(model(transform(image).unsqueeze(0).to(device))).item())
        model_result = {
            "status": "scored",
            "model_score_fake": round(probability, 6),
            "model_threshold": threshold,
            "model_indicator": "possible_ai_or_manipulation" if probability >= threshold else "no_strong_model_signal",
            "model_epoch": checkpoint.get("epoch"),
            "model_validation_accuracy": checkpoint.get("val_acc"),
            "model_validation_balanced_accuracy": checkpoint.get("val_balanced_acc"),
        }
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        model_result = {"status": "unavailable", "model_error": str(exc)}
    return {
        "verification_status": "human_review_required",
        "model": "XproAI-Net v3 (legacy checkpoint)",
        **model_result,
        "limitations": ["This retired model performed poorly on the XproAI project's reported real-world benchmark.",
                        "The score is a triage indicator, not a probability that the complaint is false.",
                        "A missing C2PA manifest does not establish that the image is authentic."],
        "c2pa": c2pa,
    }
