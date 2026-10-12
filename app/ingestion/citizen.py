"""Citizen-report adapter.

Two entry points, one normalisation path:

* ``POST /api/v1/reports`` submits a report interactively and converts it through
  :meth:`build_event`.
* A batch source file (``citizen_reports.json``) can be replayed; ``fetch_events`` reads it.

Provenance and privacy
----------------------
Reports are ``source_kind = manual`` (interactive) or ``synthetic``/``historical`` (replayed
fixtures) and are always flagged ``citizen_unverified``. They are observations, not confirmed
facts, and nothing downstream should treat them as measurements.

Report text is PII-scrubbed before storage, and ``reporter_id`` must be an opaque pseudonymous
key. The API never returns report text to a read-only client.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.timeutil import utc_now
from app.ingestion.base import AdapterOutcome, AdapterResult, FetchRequest, SourceAdapter
from app.schemas.common import QualityFlag, SourceCategory, SourceKind
from app.schemas.event import build_canonical_event
from app.schemas.report import CitizenReportCreate, ReportCategory, ReportStatus, redact_pii

__all__ = ["CitizenReportAdapter"]

logger = get_logger(__name__)


class CitizenReportAdapter(SourceAdapter):
    """Citizen-submitted incident reports."""

    source_id = "citizen.manual"
    display_name = "Citizen reports (manual)"
    category = SourceCategory.CITIZEN
    provider = "manual"
    supports_live = True
    supports_replay = True
    unit_notes = "Reports carry no measurements; text is qualitative and unverified."
    caveats = (
        "Reports are unverified observations and must not be treated as sensor corroboration.",
        "Report text is PII-scrubbed and withheld from read-only API responses.",
        "Two reports from the same reporter are not independent corroboration; source dependence "
        "is handled in Milestone 2.",
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def required_settings(self) -> list[str]:
        return []

    # ------------------------------------------------------- single report
    def build_event(self, report: CitizenReportCreate, *, submitted_at: Any = None) -> Any:
        """Convert an inbound report into a canonical event.

        Returns:
            (CanonicalEvent, was_redacted)
        """
        received = submitted_at or utc_now()
        reported_at = received if report.reported_at is None else report.resolved_reported_at()

        # Scrub obvious personal data before it is ever stored or logged.
        text = report.text
        redacted = False
        if text:
            text, redacted = redact_pii(text)

        flags: list[QualityFlag] = [QualityFlag.CITIZEN_UNVERIFIED]
        if redacted:
            flags.append(QualityFlag.REDACTED_TEXT)

        location = report.build_location()
        if location is None:
            flags.append(QualityFlag.LOCATION_MISSING)

        event = build_canonical_event(
            source_id=self.source_id,
            source_event_id=report.reporter_id or None,
            event_type=report.report_category.to_event_type(),
            # The reporter's observation time is authoritative; receipt time is recorded separately.
            event_time=reported_at,
            ingest_time=received,
            location=location,
            measurements=[],
            source_kind=SourceKind.MANUAL,
            quality_flags=flags,
            text=text,
            payload={
                "provider": self.provider,
                "report_category": report.report_category.value,
                "report_status": ReportStatus.UNVERIFIED.value,
                "area_reference": report.area_reference,
                "attachment_ref": report.attachment_ref,
                "has_reporter_key": bool(report.reporter_id),
                "text_redacted": redacted,
                # Note: submission time is carried in ingest_time, never in event_time.
                "submitted_at": received.isoformat(),
            },
        )
        return event, redacted

    # ----------------------------------------------------------- batch/replay
    async def fetch_events(self, request: FetchRequest) -> AdapterResult:
        """Replay a batch of reports from a JSON fixture."""
        started = utc_now()
        outcome = AdapterOutcome()

        path = Path(self.settings.replay_fixtures_dir) / "citizen_reports.json"
        if not path.exists():
            raise NotFoundError(
                f"Citizen report fixture not found: {path.name}.",
                details={"provider": self.provider, "setting": "REPLAY_FIXTURES_DIR"},
            )

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise NotFoundError(
                f"Citizen report fixture is not valid JSON (line {exc.lineno}).",
                details={"provider": self.provider},
            ) from exc

        records = _extract_records(data)
        if not records:
            outcome.warnings.append("Citizen report fixture contained no usable records.")
            return AdapterResult.from_outcome(self.source_id, outcome, started)

        for index, record in enumerate(records):
            report = self._to_report(record)
            if report is None:
                outcome.reject(
                    reason_code="malformed_payload",
                    message=f"Citizen fixture record {index} could not be parsed.",
                    outcome="quarantined",
                )
                continue
            try:
                event, _ = self.build_event(report, submitted_at=utc_now())
            except ValueError as exc:
                outcome.reject(
                    reason_code="invalid_measurement_value",
                    message=f"Citizen fixture record {index} rejected: {exc}",
                    outcome="quarantined",
                )
                continue
            # Replayed fixtures are synthetic, never "manual" — they did not arrive live.
            event = event.model_copy(update={"source_kind": SourceKind.SYNTHETIC})
            outcome.accept(event)

        return AdapterResult.from_outcome(self.source_id, outcome, started)

    @staticmethod
    def _to_report(record: Any) -> CitizenReportCreate | None:
        """Build a validated report from a fixture record, or None when unusable."""
        if not isinstance(record, dict):
            return None
        try:
            category = ReportCategory(str(record.get("report_category", "other")).strip().lower())
        except ValueError:
            return None

        location = None
        raw_location = record.get("location")
        if isinstance(raw_location, dict):
            from app.schemas.event import EventLocation

            try:
                location = EventLocation(
                    latitude=raw_location.get("latitude"),
                    longitude=raw_location.get("longitude"),
                    accuracy_m=raw_location.get("accuracy_m"),
                    area_reference=raw_location.get("area_reference"),
                )
            except ValueError:
                location = None

        try:
            return CitizenReportCreate(
                report_category=category,
                text=record.get("text"),
                reported_at=record.get("reported_at"),
                location=location,
                area_reference=record.get("area_reference"),
                attachment_ref=record.get("attachment_ref"),
                reporter_id=record.get("reporter_id"),
            )
        except ValueError:
            return None


def _extract_records(data: Any) -> list[Any]:
    """Pull the record list out of a fixture document."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("reports", "records", "data", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []
