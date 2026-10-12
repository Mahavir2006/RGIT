from __future__ import annotations

from urban_sentinel.domain.models import EventType, NormalizedEvent, ProcessedWorkflowInput, SourceHealthStatus
from urban_sentinel.intelligence.models import (
    AmbiguityNote,
    DuplicateReference,
    ExtractedFact,
    QualityConcern,
    SignalAnalysis,
)


def deterministic_signal(payload: ProcessedWorkflowInput) -> SignalAnalysis:
    facts: list[ExtractedFact] = []
    ambiguities: list[AmbiguityNote] = []
    duplicates: list[DuplicateReference] = []
    concerns: list[QualityConcern] = []
    relevant: list[str] = []

    events_by_type: dict[str, list[NormalizedEvent]] = {}
    for event in payload.normalized_events:
        relevant.append(event.event_id)
        events_by_type.setdefault(event.event_type.value, []).append(event)
        if event.text:
            lowered = event.text.lower()
            facts.append(
                ExtractedFact(
                    event_id=event.event_id,
                    statement=_summarize_text(event),
                    kind="observation",
                )
            )
            if any(token in lowered for token in ("maybe", "unclear", "not sure", "possibly")):
                ambiguities.append(
                    AmbiguityNote(
                        event_id=event.event_id,
                        description="Citizen report language is hedged or incomplete.",
                        missing_fields=["exact_location", "water_depth"],
                    )
                )
        if event.duplicate_of:
            duplicates.append(
                DuplicateReference(
                    event_id=event.event_id,
                    possible_duplicate_of=event.duplicate_of,
                    reason="Pipeline marked an exact or near duplicate.",
                )
            )
        if event.quality_score is not None and event.quality_score < 0.4:
            concerns.append(
                QualityConcern(
                    event_id=event.event_id,
                    source_id=event.source_id,
                    description="Low source-quality score from the deterministic pipeline.",
                    reliability="low",
                )
            )
        if event.event_type == EventType.CITIZEN_REPORT and not event.location:
            ambiguities.append(
                AmbiguityNote(
                    event_id=event.event_id,
                    description="Citizen report is missing a structured location.",
                    missing_fields=["location"],
                )
            )
        if event.event_type == EventType.CROWD or event.unit == "count":
            count_val = int(event.numeric_value) if event.numeric_value is not None else 0
            facts.append(
                ExtractedFact(
                    event_id=event.event_id,
                    statement=f"Vision crowd observation: {count_val} individuals detected ({event.source_id}).",
                    kind="observation",
                )
            )

    for rec in payload.anomaly_records:
        if "crowd" in rec.detector.lower() or "spike" in rec.description.lower():
            facts.append(
                ExtractedFact(
                    event_id=rec.event_id,
                    statement=f"Crowd surge alert: {rec.description} (severity: {rec.severity}).",
                    kind="interpretation",
                )
            )

    for health in payload.source_health:
        if health.status in {SourceHealthStatus.OFFLINE, SourceHealthStatus.DEGRADED}:
            concerns.append(
                QualityConcern(
                    source_id=health.source_id,
                    description=f"Source {health.source_id} is {health.status.value}; absence of readings is not evidence of safe conditions.",
                    reliability="low",
                )
            )
            ambiguities.append(
                AmbiguityNote(
                    description=f"Missing observations from {health.source_id}.",
                    missing_fields=[health.source_id],
                )
            )

    water = events_by_type.get(EventType.WATER_LEVEL.value, [])
    if not water:
        ambiguities.append(
            AmbiguityNote(
                description="No water-level observations in the current batch.",
                missing_fields=["water_level"],
            )
        )

    late = [
        event
        for event in payload.normalized_events
        if event.ingested_at and event.observed_at and event.ingested_at > event.observed_at
    ]
    for event in late:
        facts.append(
            ExtractedFact(
                event_id=event.event_id,
                statement="Event arrived later than its observation timestamp.",
                kind="interpretation",
                confidence_note="late-arriving",
            )
        )

    summary_parts = [
        f"{len(payload.normalized_events)} processed events",
        f"{len(payload.anomaly_records)} anomaly records",
        f"{len(concerns)} quality concerns",
    ]
    return SignalAnalysis(
        extracted_facts=facts,
        relevant_event_ids=sorted(set(relevant)),
        ambiguities=ambiguities,
        possible_duplicates=duplicates,
        quality_concerns=concerns,
        evidence_summary="; ".join(summary_parts),
        used_fallback=True,
    )


def _summarize_text(event: NormalizedEvent) -> str:
    text = (event.text or "").strip()
    if len(text) > 180:
        text = text[:177] + "..."
    return f"Citizen/unstructured observation: {text}" if text else "Unstructured observation present."
