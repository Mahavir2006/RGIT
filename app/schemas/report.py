"""Citizen report schemas.

Privacy posture
---------------
A citizen report is an *unverified observation*. Two rules are enforced by the schema:

* ``reporter_id`` is an opaque, pseudonymous key. No name, phone number, or address is accepted,
  because none is needed to act on a report.
* ``text`` is length-limited and treated as untrusted input. It is never interpreted as an
  instruction and is redacted from read-only API responses and from logs.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.timeutil import parse_timestamp
from app.schemas.event import EventLocation, EventType

__all__ = [
    "ReportCategory",
    "ReportStatus",
    "CitizenReportCreate",
    "CitizenReportAccepted",
]

# Free-text patterns that commonly carry personally identifying information. Matched
# occurrences are redacted in `text` before storage, and the report is flagged.
_PII_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[email]"),
    (re.compile(r"\b(?:\+?\d[\d\s-]{7,}\d)\b"), "[phone]"),
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[card]"),
    (re.compile(r"\b(?:flat|house|room)\s*(?:no\.?)?\s*\d+[a-z]?\b", re.IGNORECASE), "[address]"),
    (re.compile(r"\b[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.IGNORECASE), "[email]"),
)


def redact_pii(text: str) -> tuple[str, bool]:
    """Redact obvious PII from report text.

    Returns:
        (redacted_text, was_redacted)
    """
    result = text
    was_redacted = False
    for pattern, placeholder in _PII_PATTERNS:
        result, count = pattern.subn(placeholder, result)
        if count:
            was_redacted = True
    return result, was_redacted


class ReportCategory(str, Enum):
    """Citizen-facing report categories, mapped onto canonical event types."""

    WATERLOGGING = "waterlogging"
    FLOODING = "flooding"
    ROAD_BLOCKAGE = "road_blockage"
    POWER_OUTAGE = "power_outage"
    AIR_QUALITY = "air_quality"
    PUBLIC_HEALTH = "public_health"
    OTHER = "other"

    def to_event_type(self) -> EventType:
        return {
            ReportCategory.WATERLOGGING: EventType.WATERLOGGING_REPORTED,
            ReportCategory.FLOODING: EventType.FODDLING_REPORTED,
            ReportCategory.ROAD_BLOCKAGE: EventType.ROAD_BLOCKAGE_REPORTED,
            ReportCategory.POWER_OUTAGE: EventType.POWER_OUTAGE_REPORTED,
            ReportCategory.AIR_QUALITY: EventType.AIR_QUALITY_COMPLAINT,
            ReportCategory.PUBLIC_HEALTH: EventType.PUBLIC_HEALTH_REPORTED,
            ReportCategory.OTHER: EventType.OTHER_REPORT,
        }[self]


class ReportStatus(str, Enum):
    """Verification state of a report. Reports start unverified; humans may later promote them."""

    UNVERIFIED = "unverified"
    CORROBORATED = "corroborated"
    DISPUTED = "disputed"
    INVALID = "invalid"


class CitizenReportCreate(BaseModel):
    """Inbound citizen report for ``POST /api/v1/reports``."""

    model_config = ConfigDict(extra="forbid")

    report_category: ReportCategory
    text: str | None = Field(default=None, max_length=2000)
    reported_at: datetime | str | int | float | None = Field(
        default=None,
        description="When the reporter observed the condition. Defaults to receipt time.",
    )
    location: EventLocation | None = None
    area_reference: str | None = Field(default=None, max_length=255)
    attachment_ref: str | None = Field(
        default=None,
        max_length=512,
        description="Reference to an already-uploaded attachment. Binary upload is not part of "
                    "this milestone, so this is a reference only.",
    )
    reporter_id: str | None = Field(
        default=None,
        max_length=128,
        description="Opaque pseudonymous reporter key. Never a name, phone, or email.",
    )

    @field_validator("text")
    @classmethod
    def _clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if len(cleaned) > 2000:
            raise ValueError("report text must not exceed 2000 characters")
        # Collapse control characters that would corrupt log lines and stored records.
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", cleaned)

    @field_validator("reporter_id")
    @classmethod
    def _validate_reporter(cls, value: str | None) -> str | None:
        """Reject anything that looks like a direct personal identifier."""
        if value is None:
            return None
        candidate = value.strip()
        if not candidate:
            return None
        lowered = candidate.lower()
        if "@" in candidate:
            raise ValueError("reporter_id must be a pseudonymous key, not an email address")
        if re.fullmatch(r"\+?[\d\s-]{7,}\d", candidate):
            raise ValueError("reporter_id must be a pseudonymous key, not a phone number")
        if any(token in lowered for token in ("name", "phone", "email", "address")):
            raise ValueError("reporter_id must not encode personal details")
        return candidate

    @field_validator("reported_at", mode="before")
    @classmethod
    def _coerce_reported_at(cls, value: Any) -> Any:
        if value is None or isinstance(value, (int, float, datetime)):
            return value
        if isinstance(value, str):
            parse_timestamp(value)  # raises ValueError with a clear message on bad input
            return value
        raise TypeError(f"unsupported reported_at type: {type(value).__name__}")

    def resolved_reported_at(self) -> datetime:
        """Return the observation time, defaulting to receipt time when unspecified."""
        if self.reported_at is None:
            from app.core.timeutil import utc_now

            return utc_now()
        return parse_timestamp(self.reported_at)

    def build_location(self) -> EventLocation | None:
        """Combine explicit coordinates with an optional area reference."""
        if self.location is not None and self.location.has_coordinates:
            return self.location
        if self.area_reference:
            return EventLocation.from_area(self.area_reference)
        return self.location


class CitizenReportAccepted(BaseModel):
    """Response returned when a report is accepted.

    ``redacted`` tells the submitter that some text was stripped of personal data.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    status: ReportStatus = ReportStatus.UNVERIFIED
    report_category: ReportCategory
    event_type: EventType
    reported_at: datetime
    submitted_at: datetime
    redacted: bool = False
    message: str = "Report accepted as an unverified observation."
