from __future__ import annotations

from collections.abc import Iterable

from urban_sentinel.intelligence.exceptions import InvalidAgentOutput
from urban_sentinel.intelligence.models import (
    CascadeScenario,
    FusionDecision,
    Hypothesis,
    ResponseRecommendation,
    SignalAnalysis,
)


def _unknown(ids: Iterable[str], known: set[str]) -> list[str]:
    return sorted({item for item in ids if item not in known})


def validate_signal(analysis: SignalAnalysis, known_event_ids: set[str]) -> None:
    referenced = list(analysis.relevant_event_ids)
    referenced.extend(fact.event_id for fact in analysis.extracted_facts)
    referenced.extend(note.event_id for note in analysis.ambiguities if note.event_id)
    referenced.extend(dup.event_id for dup in analysis.possible_duplicates)
    referenced.extend(dup.possible_duplicate_of for dup in analysis.possible_duplicates)
    referenced.extend(item.event_id for item in analysis.quality_concerns if item.event_id)
    bad = _unknown(referenced, known_event_ids)
    if bad:
        raise InvalidAgentOutput(f"signal analysis referenced unknown event IDs: {bad}")


def validate_fusion(
    decision: FusionDecision,
    known_event_ids: set[str],
    known_incident_ids: set[str],
) -> None:
    if decision.event_id not in known_event_ids:
        raise InvalidAgentOutput(f"fusion referenced unknown event ID: {decision.event_id}")
    bad_events = _unknown(decision.evidence_event_ids, known_event_ids)
    if bad_events:
        raise InvalidAgentOutput(f"fusion referenced unknown evidence event IDs: {bad_events}")
    allowed_incidents = set(known_incident_ids)
    bad_incidents = _unknown(decision.candidate_incident_ids, allowed_incidents)
    if bad_incidents:
        raise InvalidAgentOutput(f"fusion referenced unknown incident IDs: {bad_incidents}")
    if decision.selected_incident_id and decision.selected_incident_id not in allowed_incidents:
        raise InvalidAgentOutput(
            f"fusion selected unknown incident ID: {decision.selected_incident_id}"
        )


def validate_hypothesis(hypothesis: Hypothesis, known_event_ids: set[str]) -> None:
    bad = _unknown(
        [*hypothesis.supporting_event_ids, *hypothesis.contradicting_event_ids],
        known_event_ids,
    )
    if bad:
        raise InvalidAgentOutput(
            f"hypothesis {hypothesis.hypothesis_id} referenced unknown event IDs: {bad}"
        )


def validate_scenario(scenario: CascadeScenario, known_asset_ids: set[str]) -> None:
    ids = list(scenario.starting_asset_ids) + list(scenario.affected_asset_ids)
    for path in scenario.dependency_paths:
        ids.extend(path.asset_ids)
    bad = _unknown(ids, known_asset_ids)
    if bad:
        raise InvalidAgentOutput(
            f"scenario {scenario.scenario_id} referenced unknown asset IDs: {bad}"
        )


def validate_recommendation(
    rec: ResponseRecommendation,
    known_event_ids: set[str],
    known_action_ids: set[str],
) -> None:
    if rec.action_id not in known_action_ids:
        raise InvalidAgentOutput(f"recommendation used unknown action ID: {rec.action_id}")
    bad = _unknown(rec.evidence_event_ids, known_event_ids)
    if bad:
        raise InvalidAgentOutput(f"recommendation referenced unknown event IDs: {bad}")
