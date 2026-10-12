"""Citizen reports: privacy posture, validation, and unverified provenance."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.ingestion.base import FetchRequest
from app.ingestion.citizen import CitizenReportAdapter
from app.schemas.common import MeasurementAggregation, QualityFlag, SourceKind
from app.schemas.event import EventLocation, Measurement
from app.schemas.report import (
    CitizenReportCreate,
    ReportCategory,
    ReportStatus,
    redact_pii,
)
from tests.conftest import make_settings


def _adapter() -> CitizenReportAdapter:
    return CitizenReportAdapter(make_settings())


def test_report_maps_to_unverified_canonical_event():
    report = CitizenReportCreate(
        report_category=ReportCategory.WATERLOGGING,
        text="Road near the metro station is under knee-deep water.",
        reported_at="2026-10-12T09:12:00+05:30",
        location=EventLocation(latitude=19.0760, longitude=72.8777, accuracy_m=30),
        area_reference="Andheri East",
        reporter_id="reporter_a1",
    )
    event, redacted = _adapter().build_event(report)
    assert event.event_type.value == "waterlogging_reported"
    assert event.source_kind == SourceKind.MANUAL
    assert QualityFlag.CITIZEN_UNVERIFIED in event.quality_flags
    assert redacted is False
    # Observation time and receipt time are distinct.
    assert event.event_time.isoformat() == "2026-10-12T03:42:00+00:00"
    assert event.ingest_time != event.event_time
    assert event.payload["report_status"] == ReportStatus.UNVERIFIED.value


def test_report_carries_no_measurements():
    """A qualitative report must not fabricate numeric readings."""
    report = CitizenReportCreate(report_category=ReportCategory.OTHER, text="Streetlight off.")
    event, _ = _adapter().build_event(report)
    assert event.measurements == []


def test_pii_is_redacted_from_report_text():
    report = CitizenReportCreate(
        report_category=ReportCategory.ROAD_BLOCKAGE,
        text="Waterlogging near the junction. Call 9876543210 or email me at rider@example.com",
    )
    event, redacted = _adapter().build_event(report)
    assert redacted is True
    assert "9876543210" not in (event.text or "")
    assert "rider@example.com" not in (event.text or "")
    assert "[phone]" in (event.text or "") and "[email]" in (event.text or "")
    assert QualityFlag.REDACTED_TEXT in event.quality_flags


@pytest.mark.parametrize(
    "reporter_id",
    ["rider@example.com", "+91 98765 43210", "9876543210", "name: John"],
)
def test_personal_reporter_identifiers_rejected(reporter_id):
    with pytest.raises(PydanticValidationError):
        CitizenReportCreate(report_category=ReportCategory.OTHER, reporter_id=reporter_id)


def test_pseudonymous_reporter_key_accepted():
    report = CitizenReportCreate(
        report_category=ReportCategory.OTHER, reporter_id="reporter_a1"
    )
    assert report.reporter_id == "reporter_a1"


def test_oversized_text_rejected():
    with pytest.raises(PydanticValidationError):
        CitizenReportCreate(report_category=ReportCategory.OTHER, text="x" * 2001)


def test_control_characters_are_stripped():
    report = CitizenReportCreate(
        report_category=ReportCategory.OTHER, text="line one\x00\x07 line two"
    )
    assert "\x00" not in (report.text or "")
    assert "\x07" not in (report.text or "")


def test_area_only_report_gets_no_fabricated_pin():
    report = CitizenReportCreate(
        report_category=ReportCategory.WATERLOGGING, area_reference="Andheri East"
    )
    event, _ = _adapter().build_event(report)
    assert event.location.latitude is None
    assert event.location.area_reference == "Andheri East"
    assert QualityFlag.LOCATION_MISSING in event.quality_flags


def test_missing_observation_time_defaults_to_receipt_time():
    report = CitizenReportCreate(report_category=ReportCategory.OTHER, text="x")
    event, _ = _adapter().build_event(report)
    assert event.event_time == event.ingest_time


def test_every_category_maps_to_a_closed_event_type():
    for category in ReportCategory:
        assert category.to_event_type() is not None


def test_unknown_category_rejected():
    with pytest.raises(ValueError):
        ReportCategory("alien_invasion")


def test_redact_pii_helper():
    text, changed = redact_pii("reach me on 9998887777 or a@b.co")
    assert changed is True
    assert "9998887777" not in text
    text2, changed2 = redact_pii("just a normal report")
    assert changed2 is False


async def test_batch_replay_marks_reports_synthetic_not_manual():
    """Replayed fixtures did not arrive live, so they must not be stamped 'manual'."""
    adapter = CitizenReportAdapter(make_settings())
    result = await adapter.fetch_events(
        FetchRequest(source_id=adapter.source_id, correlation_id="t")
    )
    assert len(result.events) == 3
    assert all(e.source_kind == SourceKind.SYNTHETIC for e in result.events)
    assert all(
        QualityFlag.CITIZEN_UNVERIFIED in e.quality_flags for e in result.events
    )


async def test_batch_replay_redacts_fixture_phone_number(samples_dir):
    adapter = CitizenReportAdapter(make_settings(replay_fixtures_dir=str(samples_dir)))
    result = await adapter.fetch_events(
        FetchRequest(source_id=adapter.source_id, correlation_id="t")
    )
    joined = " ".join(e.text or "" for e in result.events)
    assert "9876543210" not in joined
