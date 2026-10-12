"""Anomaly finding schema produced by the deterministic rule engine."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

__all__ = ["AnomalyType", "AnomalyKind", "AnomalySeverity", "AnomalyStatus", "AnomalyFinding",
           "SEVERITY_ORDINAL"]


class AnomalyKind(str, Enum):
    #: Something unusual in the measured environment (may or may not be an emergency).
    ENVIRONMENTAL = "environmental"
    #: A data-observability problem. Never evidence of a physical emergency.
    SENSOR_HEALTH = "sensor_health"


class AnomalyType(str, Enum):
    THRESHOLD_EXCEEDED = "THRESHOLD_EXCEEDED"
    BASELINE_DEVIATION = "BASELINE_DEVIATION"
    RAPID_CHANGE = "RAPID_CHANGE"
    FLATLINE = "FLATLINE"
    IMPLAUSIBLE_JUMP = "IMPLAUSIBLE_JUMP"
    STALE_SOURCE = "STALE_SOURCE"
    SENSOR_CONFLICT = "SENSOR_CONFLICT"
    REPEATED_MALFORMED = "REPEATED_MALFORMED"
    TIMESTAMP_ANOMALY = "TIMESTAMP_ANOMALY"
    CROWD_SPIKE = "CROWD_SPIKE"


class AnomalySeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


#: Ordinal position of each band, for ordering and for the intelligence layer's ``severity``
#: field. These are ranks, not probabilities.
SEVERITY_ORDINAL: dict[str, float] = {
    "INFO": 0.1, "LOW": 0.3, "MEDIUM": 0.5, "HIGH": 0.75, "CRITICAL": 0.95,
}


class AnomalyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class AnomalyFinding(BaseModel):
    """One rule firing on one event (or one source). Persisted as an anomaly observation."""

    anomaly_type: AnomalyType
    kind: AnomalyKind
    severity: AnomalySeverity
    rule_id: str
    rule_version: str
    source_id: str
    event_id: str | None = None
    subject: str = Field(description="Stable sensor/station/segment reference used for grouping")
    measurement: str | None = None
    observed_value: float | None = None
    unit: str | None = None
    threshold: float | None = None
    expected_range: dict[str, Any] | None = None
    score: float | None = None
    method: str
    baseline_window_hours: int | None = None
    sample_count: int | None = None
    explanation: str
    details: dict[str, Any] = Field(default_factory=dict)

    def fingerprint(self) -> str:
        """Groups repeated firings of the same condition on the same subject."""
        import hashlib

        key = "|".join([self.rule_id, self.source_id.split(".")[0], self.subject,
                        self.measurement or "-"])
        return hashlib.sha256(key.encode()).hexdigest()[:32]
