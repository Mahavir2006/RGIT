"""Stage B — deduplication and idempotency.

Canonical-event deduplication already happens atomically at ingestion (unique constraints on
``(source_id, source_event_id)``, ``idempotency_key`` and ``fingerprint``, with duplicate
receipts). This stage does **not** re-implement those rules. It adds:

1. A *versioned, source-aware processing fingerprint* that is independent of JSON key order,
   numeric formatting, and metadata, so equivalent observations under different canonical ids are
   recognised (``EXACT_DUPLICATE``).
2. *Near-duplicate* detection (same source family, subject, type and values within a small
   time/space window) flagged ``POSSIBLE_DUPLICATE`` for review — never merged or deleted.

Either kind of duplicate is excluded from independent corroboration downstream.
Processing idempotency (same event + same processing_version -> one result) is enforced by a
database unique constraint in the processing tables, not here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from app.processing.config import DedupConfig
from app.processing.correlation import haversine_m, subject_of
from app.schemas.event import CanonicalEvent
from app.schemas.processing import DedupDecision, DedupResult

__all__ = ["processing_fingerprint", "detect_duplicate"]


def _category(event: CanonicalEvent) -> str:
    return event.source_id.split(".", 1)[0]


def _time_bucket(event: CanonicalEvent, cfg: DedupConfig) -> int:
    precision = cfg.time_precision_seconds.get(
        _category(event), cfg.time_precision_seconds.get("default", 60)
    )
    return int(event.event_time.timestamp()) // max(1, precision)


def processing_fingerprint(event: CanonicalEvent, cfg: DedupConfig) -> str:
    """Canonical content hash. Key order, float formatting and metadata do not affect it."""
    loc = event.location
    coords = None
    if loc is not None and loc.has_coordinates:
        coords = [round(loc.latitude, cfg.coordinate_decimals),  # type: ignore[arg-type]
                  round(loc.longitude, cfg.coordinate_decimals)]  # type: ignore[arg-type]
    measurements = sorted(
        [m.name, format(float(m.value), ".6g"), m.unit, m.period_seconds or 0]
        for m in event.measurements
    )
    doc = {
        "v": cfg.version,
        "src": _category(event),  # replay.* and live.* of one category compare equal
        "type": event.event_type.value,
        "t": _time_bucket(event, cfg),
        "subject": subject_of(event),
        "loc": coords,
        "m": measurements,
        "text": (event.text or "").strip().lower() or None,
    }
    blob = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    return f"pfp{cfg.version}_" + hashlib.sha256(blob.encode()).hexdigest()[:32]


def detect_duplicate(
    event: CanonicalEvent,
    neighbours: Iterable[CanonicalEvent],
    cfg: DedupConfig,
) -> DedupResult:
    """Compare ``event`` with earlier-persisted nearby events of the same type.

    ``neighbours`` must already be bounded (same type, small time window) by the caller. Only
    events persisted *before* this one (lower canonical identity order) are considered, so the
    first-seen event is always the canonical original and is never displaced.
    """
    fp = processing_fingerprint(event, cfg)
    near: CanonicalEvent | None = None
    for other in neighbours:
        if other.event_id == event.event_id:
            continue
        if processing_fingerprint(other, cfg) == fp:
            return DedupResult(
                decision=DedupDecision.EXACT_DUPLICATE, method="fingerprint", fingerprint=fp,
                fingerprint_version=cfg.version, duplicate_of=other.event_id,
                counts_as_corroboration=False,
                explanation=f"same observation as {other.event_id} (normalised content match: "
                            "type, subject, time bucket, location, measurements)",
            )
        if near is None and _is_near(event, other, cfg):
            near = other
    if near is not None:
        return DedupResult(
            decision=DedupDecision.POSSIBLE_DUPLICATE, method="near_match", fingerprint=fp,
            fingerprint_version=cfg.version, duplicate_of=near.event_id,
            counts_as_corroboration=False,
            explanation=f"similar to {near.event_id} within {cfg.near_window_seconds}s and "
                        f"{cfg.near_radius_m:.0f} m with identical readings; kept, flagged for "
                        "review, and not counted as independent corroboration",
        )
    return DedupResult(decision=DedupDecision.UNIQUE, method="none", fingerprint=fp,
                       fingerprint_version=cfg.version,
                       explanation="no equivalent or near-identical earlier event")


def _is_near(a: CanonicalEvent, b: CanonicalEvent, cfg: DedupConfig) -> bool:
    if a.event_type != b.event_type or _category(a) != _category(b):
        return False
    if abs((a.event_time - b.event_time).total_seconds()) > cfg.near_window_seconds:
        return False
    la, lb = a.location, b.location
    if la and lb and la.has_coordinates and lb.has_coordinates:
        if haversine_m(la.latitude, la.longitude, lb.latitude, lb.longitude) > cfg.near_radius_m:  # type: ignore[arg-type]
            return False
    elif subject_of(a) != subject_of(b):
        return False
    if a.text or b.text:
        # Two citizens describing the same thing are *independent* witnesses unless the text is
        # the same; different wording is never a duplicate.
        return (a.text or "").strip().lower() == (b.text or "").strip().lower()
    va = {(m.name, m.unit): m.value for m in a.measurements}
    vb = {(m.name, m.unit): m.value for m in b.measurements}
    return bool(va) and va == vb
