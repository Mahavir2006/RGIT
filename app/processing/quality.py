"""Data-quality score in [0, 1], derived only from validation issues and provenance.

This is a transparent penalty table, not a learned reliability model.
"""

from __future__ import annotations

from app.schemas.processing import ReasonCode, ValidationIssue

__all__ = ["quality_score", "PENALTIES"]

PENALTIES: dict[ReasonCode, float] = {
    ReasonCode.STALE_OBSERVATION: 0.15,
    ReasonCode.LATE_ARRIVAL: 0.05,
    ReasonCode.LOCATION_MISSING: 0.20,
    ReasonCode.LOCATION_APPROXIMATE: 0.05,
    ReasonCode.UPSTREAM_SUSPECT: 0.25,
    ReasonCode.MISSING_MEASUREMENT: 0.30,
    ReasonCode.UNKNOWN_UNIT: 0.25,
    ReasonCode.MISSING_PERIOD: 0.10,
    ReasonCode.FUTURE_TIMESTAMP: 0.30,
}


def quality_score(issues: list[ValidationIssue], *, source_reliability: float = 1.0) -> float:
    score = 1.0
    for issue in issues:
        if issue.severity in ("quarantine", "reject"):
            return 0.0
        score -= PENALTIES.get(issue.code, 0.0)
    return round(max(0.0, min(1.0, score)) * max(0.0, min(1.0, source_reliability)), 4)
