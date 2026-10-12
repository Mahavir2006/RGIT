from __future__ import annotations

from hashlib import sha1

from urban_sentinel.domain.models import EventType, ProcessedWorkflowInput, ScoreType, SourceHealthStatus
from urban_sentinel.intelligence.models import (
    CascadeScenario,
    CausalAnalysis,
    DependencyPath,
    Hypothesis,
    HypothesisStatus,
)
from urban_sentinel.intelligence.state import IntelligenceState


def _hid(incident_id: str, claim: str) -> str:
    digest = sha1(f"{incident_id}:{claim}".encode(), usedforsecurity=False).hexdigest()[:12]
    return f"hyp-{digest}"


def _sid(incident_id: str, start: str) -> str:
    digest = sha1(f"{incident_id}:{start}".encode(), usedforsecurity=False).hexdigest()[:12]
    return f"scn-{digest}"


def deterministic_causal(
    payload: ProcessedWorkflowInput,
    state: IntelligenceState,
    paths: list[DependencyPath],
    *,
    graph_available: bool,
) -> CausalAnalysis:
    incident_id = state.get("incident_id") or payload.incident_id or "unknown-incident"
    events = {event.event_id: event for event in payload.normalized_events}
    by_type: dict[str, list[str]] = {}
    for event in payload.normalized_events:
        by_type.setdefault(event.event_type.value, []).append(event.event_id)

    rain = by_type.get(EventType.WEATHER.value, [])
    water = by_type.get(EventType.WATER_LEVEL.value, [])
    traffic = by_type.get(EventType.TRAFFIC.value, [])
    reports = by_type.get(EventType.CITIZEN_REPORT.value, [])
    crowd = by_type.get(EventType.CROWD.value, [])
    for eid, ev in events.items():
        if (ev.unit == "count" or "crowd" in ev.source_id.lower()) and eid not in crowd:
            crowd.append(eid)
    offline = [h.source_id for h in payload.source_health if h.status == SourceHealthStatus.OFFLINE]

    hypotheses: list[Hypothesis] = []
    gaps: list[str] = []

    if not water:
        gaps.append("water-level reading from an in-area sensor")
    if offline:
        gaps.append(f"restore observations from offline sources: {', '.join(offline)}")
        gaps.append("Do not treat missing sensor data as proof that flooding is absent.")

    flood_support = rain + water + reports
    flood_contra = []
    if traffic and not water:
        flood_contra.extend(traffic)

    if flood_support:
        hypotheses.append(
            Hypothesis(
                hypothesis_id=_hid(incident_id, "monsoon-waterlogging"),
                incident_id=incident_id,
                claim="Localized waterlogging driven by rainfall and rising water levels.",
                status=HypothesisStatus.PROPOSED,
                score=min(1.0, 0.35 + 0.15 * len(flood_support)),
                score_type=ScoreType.HEURISTIC_SUPPORT,
                supporting_event_ids=flood_support,
                contradicting_event_ids=flood_contra,
                assumptions=[
                    "Water-level rise temporally follows rainfall where both are present.",
                    "Citizen reports describe observed standing water rather than a confirmed cause.",
                ],
                limitations=[
                    "Heuristic evidence-support score is not a causal probability.",
                    "Graph connectivity is not proof of causation.",
                ],
                model_version="deterministic-v1",
                alternatives=["Independent traffic incident coinciding with rainfall."],
            )
        )

    if traffic:
        traffic_support = list(traffic)
        traffic_contra = list(water + reports)
        hypotheses.append(
            Hypothesis(
                hypothesis_id=_hid(incident_id, "traffic-incident"),
                incident_id=incident_id,
                claim="Independent traffic disruption (collision, blockage, or congestion) coinciding with weather.",
                status=HypothesisStatus.PROPOSED,
                score=0.4 if not water else 0.28,
                score_type=ScoreType.HEURISTIC_SUPPORT,
                supporting_event_ids=traffic_support,
                contradicting_event_ids=traffic_contra,
                assumptions=[
                    "Speed drop is an observation, not by itself a confirmed crash.",
                ],
                limitations=["Competing hypotheses are preserved rather than forced to a single cause."],
                model_version="deterministic-v1",
                alternatives=["Rain-induced waterlogging reducing traffic speed."],
            )
        )

    if crowd:
        hypotheses.append(
            Hypothesis(
                hypothesis_id=_hid(incident_id, "public-gathering-protest"),
                incident_id=incident_id,
                claim="Public gathering or protest activity evidenced by quantitative vision crowd density.",
                status=HypothesisStatus.PROPOSED,
                score=min(1.0, 0.40 + 0.15 * len(crowd)),
                score_type=ScoreType.HEURISTIC_SUPPORT,
                supporting_event_ids=list(crowd),
                contradicting_event_ids=[],
                assumptions=[
                    "Vision-detected head counts indicate localized physical human assembly.",
                    "Sudden count spikes (>2x rolling average) correlate with assembly formation rather than baseline pedestrian flow.",
                ],
                limitations=[
                    "Camera field-of-view provides sector-level density, not full crowd census.",
                    "Assembly intent (demonstration vs festive vs transport bottleneck) requires multi-source corroboration.",
                ],
                model_version="deterministic-v1",
                alternatives=[
                    "Transit bottleneck or festival congestion without civil demonstration.",
                ],
            )
        )

    insufficient = not hypotheses or (not water and not reports and not rain and not crowd)
    if insufficient:
        hypotheses = [
            Hypothesis(
                hypothesis_id=_hid(incident_id, "insufficient"),
                incident_id=incident_id,
                claim="INSUFFICIENT_EVIDENCE",
                status=HypothesisStatus.UNRESOLVED,
                score=None,
                score_type=ScoreType.INSUFFICIENT,
                supporting_event_ids=list(events),
                contradicting_event_ids=[],
                assumptions=["Available observations do not uniquely support a cause."],
                limitations=["No cause is asserted."],
                model_version="deterministic-v1",
            )
        ]

    scenarios: list[CascadeScenario] = []
    if not graph_available:
        scenarios = []
        gaps.append("Neo4j/graph evidence unavailable; cascade analysis ran in degraded mode.")
    elif not paths:
        scenarios.append(
            CascadeScenario(
                scenario_id=_sid(incident_id, "none"),
                incident_id=incident_id,
                starting_asset_ids=payload.incident.asset_ids if payload.incident else [],
                affected_asset_ids=[],
                dependency_paths=[],
                assumptions=["No validated dependency edges were returned for this incident."],
                risk_score=0.0,
                score_type=ScoreType.GRAPH_PATH_HEURISTIC,
                simulated=True,
                limitations=["Empty cascade is an absence of known edges, not a safety guarantee."],
            )
        )
    else:
        affected: list[str] = []
        for path in paths:
            affected.extend(path.asset_ids[1:])
        starts = payload.incident.asset_ids if payload.incident else []
        if not starts and paths:
            starts = [path.asset_ids[0] for path in paths]
        critical = [asset.asset_id for asset in payload.assets if asset.critical]
        risk = min(1.0, 0.2 + 0.15 * len(set(affected)) + (0.2 if set(affected) & set(critical) else 0))
        scenarios.append(
            CascadeScenario(
                scenario_id=_sid(incident_id, ",".join(starts) or "graph"),
                incident_id=incident_id,
                starting_asset_ids=starts,
                affected_asset_ids=sorted(set(affected)),
                dependency_paths=paths,
                assumptions=[
                    "Traversal uses recorded DEPENDS_ON edges only.",
                    "Results are simulated/heuristic pending operator validation.",
                ],
                risk_score=risk,
                score_type=ScoreType.SIMULATED_CASCADE,
                simulated=True,
                limitations=[
                    "Do not treat graph connectivity as proof of causation.",
                    "Assets and edges were not invented; only repository-returned paths are listed.",
                ],
            )
        )
        if any("hospital" in (asset.name + asset.asset_type).lower() or asset.critical for asset in payload.assets):
            gaps.append("Confirm whether emergency-access corridors remain passable.")

    return CausalAnalysis(
        hypotheses=hypotheses,
        cascade_scenarios=scenarios,
        suggested_additional_evidence=gaps,
        insufficient_evidence=insufficient,
        used_fallback=True,
    )
