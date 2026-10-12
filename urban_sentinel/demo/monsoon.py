from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pprint import pprint

from urban_sentinel.core.config import Settings
from urban_sentinel.domain.models import (
    AnomalyRecord,
    Asset,
    CorrelationResult,
    DependencyEdge,
    EventType,
    GeoPoint,
    IncidentSummary,
    NormalizedEvent,
    ProcessedWorkflowInput,
    ScoreType,
    SourceHealthRecord,
    SourceHealthStatus,
)
from urban_sentinel.intelligence.llm import NullLLM
from urban_sentinel.intelligence.service import IntelligenceService
from urban_sentinel.repositories.graph import InMemoryGraphRepository
from urban_sentinel.repositories.operational import OperationalRepository

AREA = GeoPoint(lat=19.0760, lon=72.8777, area_id="ward-12")
T0 = datetime(2026, 7, 12, 14, 0, tzinfo=UTC)


def monsoon_payload() -> ProcessedWorkflowInput:
    rain = NormalizedEvent(
        event_id="evt-rain-1",
        source_id="weather-imd",
        event_type=EventType.WEATHER,
        observed_at=T0,
        ingested_at=T0 + timedelta(minutes=2),
        location=AREA,
        numeric_value=42.0,
        unit="mm/h",
        quality_score=0.92,
        attributes={"phenomenon": "rainfall"},
    )
    water = NormalizedEvent(
        event_id="evt-water-1",
        source_id="sensor-wl-04",
        event_type=EventType.WATER_LEVEL,
        observed_at=T0 + timedelta(minutes=20),
        ingested_at=T0 + timedelta(minutes=22),
        location=AREA,
        numeric_value=1.4,
        unit="m",
        quality_score=0.88,
    )
    traffic = NormalizedEvent(
        event_id="evt-traffic-1",
        source_id="tomtom-link-88",
        event_type=EventType.TRAFFIC,
        observed_at=T0 + timedelta(minutes=25),
        ingested_at=T0 + timedelta(minutes=26),
        location=AREA,
        numeric_value=8.0,
        unit="km/h",
        quality_score=0.8,
    )
    report = NormalizedEvent(
        event_id="evt-citizen-1",
        source_id="citizen-app",
        event_type=EventType.CITIZEN_REPORT,
        observed_at=T0 + timedelta(minutes=28),
        ingested_at=T0 + timedelta(minutes=40),
        location=AREA,
        text="Knee-deep waterlogging near the hospital road, maybe a blocked drain.",
        quality_score=0.55,
    )
    health = SourceHealthRecord(
        source_id="sensor-wl-09",
        status=SourceHealthStatus.OFFLINE,
        last_seen_at=T0 - timedelta(hours=2),
        notes="Secondary water-level sensor offline",
    )
    incident = IncidentSummary(
        incident_id="inc-monsoon-12",
        title="Ward 12 monsoon disruption",
        severity_score=0.62,
        location=AREA,
        associated_event_ids=["evt-rain-1"],
        asset_ids=["road-hospital-approach", "drain-ward12"],
        evidence_version="1",
    )
    return ProcessedWorkflowInput(
        trigger_event_ids=["evt-rain-1", "evt-water-1", "evt-traffic-1", "evt-citizen-1"],
        candidate_incident_ids=["inc-monsoon-12"],
        incident_id="inc-monsoon-12",
        normalized_events=[rain, water, traffic, report],
        anomaly_records=[
            AnomalyRecord(
                anomaly_id="an-water-1",
                event_id="evt-water-1",
                detector="zscore",
                severity=0.7,
                description="Water level above seasonal baseline",
                score_type=ScoreType.RULE_SEVERITY,
            )
        ],
        correlation_results=[
            CorrelationResult(
                event_id="evt-rain-1",
                incident_id="inc-monsoon-12",
                score=0.91,
                existing_association=True,
            ),
            CorrelationResult(
                event_id="evt-water-1",
                incident_id="inc-monsoon-12",
                score=0.84,
            ),
            CorrelationResult(
                event_id="evt-traffic-1",
                incident_id="inc-monsoon-12",
                score=0.58,
            ),
            CorrelationResult(
                event_id="evt-citizen-1",
                incident_id="inc-monsoon-12",
                score=0.6,
            ),
        ],
        source_health=[health],
        incident=incident,
        incidents=[incident],
        assets=[
            Asset(
                asset_id="road-hospital-approach",
                name="Hospital approach road",
                asset_type="road",
                critical=True,
            ),
            Asset(
                asset_id="drain-ward12",
                name="Ward 12 storm drain",
                asset_type="drainage",
            ),
            Asset(
                asset_id="hospital-er",
                name="Emergency department access",
                asset_type="hospital",
                critical=True,
            ),
        ],
        dependencies=[
            DependencyEdge(
                from_asset_id="drain-ward12",
                to_asset_id="road-hospital-approach",
                relationship="FLOODS",
            ),
            DependencyEdge(
                from_asset_id="road-hospital-approach",
                to_asset_id="hospital-er",
                relationship="PROVIDES_ACCESS",
            ),
        ],
        material_change=True,
        expected_incident_version=1,
    )


async def run_demo() -> dict:
    graph = InMemoryGraphRepository()
    service = IntelligenceService(
        settings=Settings(urban_sentinel_llm_provider="none"),
        operational=OperationalRepository(),
        graph=graph,
        llm=NullLLM(),
    )
    payload = monsoon_payload()
    result = await service.run(payload)
    return result


def main() -> None:
    result = asyncio.run(run_demo())
    print("status:", result.get("status"))
    print("incident:", result.get("incident_id"))
    print("review_required:", result.get("review_required"))
    print("hypotheses:")
    pprint(result.get("hypotheses"))
    print("cascade:")
    pprint(result.get("cascade_scenarios"))
    print("actions:")
    pprint(result.get("candidate_actions"))
    print("operator_summary:", result.get("operator_summary"))
    print("gaps:", result.get("evidence_gaps"))


if __name__ == "__main__":
    main()
