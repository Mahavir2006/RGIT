"""Stages D/E — candidate incident scoring and decision.

``S(event, candidate) = (wt*T + ws*G + wk*K + wa*A + wq*Q) / (wt + ws + wk + wa + wq)``

Every component is in [0, 1], so ``S`` is in [0, 1]:

* ``T`` — 1 inside the incident's [first, last] event-time span, decaying linearly to 0 at
  ``time_window_seconds`` outside it. Uses event time, never arrival order.
* ``G`` — 1 at the incident centroid, decaying linearly to 0 at ``search_radius_m`` (distance is
  reduced by the event's stated accuracy and the incident's radius). Approximate fixes are capped
  by ``approximate_location_factor``; an area-only event scores ``area_match_spatial_score`` if
  its area matches, else 0. Missing location is never treated as co-located.
* ``K`` — best compatibility between the event family and any family in the incident.
* ``A`` — 1 if the event shares a station/segment/place id with the incident, else 0.
* ``Q`` — the event's validation quality score (already includes source reliability).

This is an **initial heuristic, not a calibrated probability**. Hard rejections (incompatible
type, geographically unrelated) are reported with a reason instead of a low score.
"""

from __future__ import annotations

from app.processing.config import CandidateConfig
from app.processing.correlation import area_of, compatibility, family_of, haversine_m, subject_of
from app.schemas.candidate import (
    CandidateIncident,
    CandidateOutcome,
    CandidateScore,
    ComponentScores,
    MatchDecision,
)
from app.schemas.common import LocationPrecision
from app.schemas.event import CanonicalEvent

__all__ = ["score_candidate", "decide"]


def score_candidate(
    event: CanonicalEvent, cand: CandidateIncident, cfg: CandidateConfig, *, quality: float
) -> CandidateScore:
    w = cfg.weights
    fam = family_of(event.event_type)
    evidence_for: list[str] = []
    against: list[str] = []

    # T — temporal
    t = event.event_time
    if cand.first_event_time <= t <= cand.last_event_time:
        dt = 0.0
    else:
        dt = min(abs((t - cand.first_event_time).total_seconds()),
                 abs((t - cand.last_event_time).total_seconds()))
    T = max(0.0, 1.0 - dt / cfg.time_window_seconds)
    signed = (t - cand.last_event_time).total_seconds()
    if dt == 0:
        evidence_for.append("event time falls within the incident's observed time span")
    elif T > 0:
        evidence_for.append(f"{dt / 60:.0f} min from the incident time span")
    else:
        against.append(f"{dt / 3600:.1f} h outside the {cfg.time_window_seconds / 3600:.0f} h window")

    # G — spatial
    G = 0.0
    distance: float | None = None
    loc = event.location
    if loc and loc.has_coordinates and cand.latitude is not None and cand.longitude is not None:
        distance = haversine_m(loc.latitude, loc.longitude, cand.latitude, cand.longitude)  # type: ignore[arg-type]
        effective = max(0.0, distance - (loc.accuracy_m or 0.0) - (cand.radius_m or 0.0))
        G = max(0.0, 1.0 - effective / cfg.search_radius_m)
        if loc.precision == LocationPrecision.APPROXIMATE:
            G *= cfg.approximate_location_factor
            against.append("event location is approximate; spatial score capped")
        if G > 0:
            evidence_for.append(f"{distance:.0f} m from the incident centroid")
        else:
            against.append(f"{distance:.0f} m away, beyond the {cfg.search_radius_m:.0f} m radius")
    else:
        area = area_of(event)
        if area and area in cand.areas:
            G = cfg.area_match_spatial_score
            evidence_for.append(f"same area reference {area!r} (no coordinates)")
        else:
            against.append("spatial compatibility unknown: no comparable location")

    # K — type compatibility
    K = max((compatibility(cfg.compatibility, fam, f) for f in cand.families), default=0.0)
    if K > 0:
        evidence_for.append(f"event family {fam!r} compatible with incident families "
                            f"{sorted(cand.families)} (k={K:g}; compatibility is not causation)")

    # A — shared subject/asset
    subj = subject_of(event)
    shared = [subj] if subj in cand.subjects and subj.startswith("place:") else []
    A = 1.0 if shared else 0.0
    if shared:
        evidence_for.append(f"shares {shared[0]} with the incident")

    # Q — data quality
    Q = max(0.0, min(1.0, quality))
    if Q < 0.7:
        against.append(f"low data-quality score {Q:.2f}")

    total_w = sum(w.values())
    score = (w["T"] * T + w["G"] * G + w["K"] * K + w["A"] * A + w["Q"] * Q) / total_w

    hard, reason = False, None
    if K == 0:
        hard, reason = True, f"event family {fam!r} is incompatible with {sorted(cand.families)}"
    elif T == 0:
        hard, reason = True, "outside the candidate time window"
    elif distance is not None and distance > cfg.search_radius_m * cfg.hard_reject_radius_factor:
        hard, reason = True, (f"geographically unrelated: {distance:.0f} m > "
                              f"{cfg.search_radius_m * cfg.hard_reject_radius_factor:.0f} m")
    if hard:
        against.append(reason)  # type: ignore[arg-type]

    return CandidateScore(
        incident_id=cand.incident_id, score=round(score, 4),
        components=ComponentScores(T=round(T, 4), G=round(G, 4), K=round(K, 4), A=A,
                                   Q=round(Q, 4)),
        weights=dict(w), time_delta_seconds=signed,
        distance_m=round(distance, 1) if distance is not None else None, shared=shared,
        evidence_for=evidence_for, evidence_against=against, hard_rejected=hard,
        rejection_reason=reason,
    )


def decide(scores: list[CandidateScore], cfg: CandidateConfig) -> MatchDecision:
    """Rank and decide. Alternatives are always retained; ties are never silently broken."""
    ranked = sorted(scores, key=lambda s: (s.hard_rejected, -s.score, s.incident_id))
    for i, s in enumerate(ranked, start=1):
        s.rank = i
    live = [s for s in ranked if not s.hard_rejected]
    version = f"cand-{cfg.version}"
    if not live:
        return MatchDecision(
            outcome=CandidateOutcome.NO_MATCH, candidates=ranked, config_version=version,
            explanation="no compatible open incident within the time window and search radius"
            if ranked else "no open incident candidates in the search window",
            recommended_next_step="open a provisional incident if the event is anomalous; "
                                  "otherwise record as unmatched",
        )
    top = live[0]
    second = live[1] if len(live) > 1 else None
    gap = top.score - second.score if second else 1.0
    if top.score >= cfg.match_threshold and gap < cfg.ambiguity_margin:
        return MatchDecision(
            outcome=CandidateOutcome.AMBIGUOUS, candidates=ranked, config_version=version,
            explanation=f"top two candidates {top.incident_id} ({top.score:.2f}) and "
                        f"{second.incident_id} ({second.score:.2f}) differ by {gap:.2f} < "  # type: ignore[union-attr]
                        f"{cfg.ambiguity_margin}; both retained",
            recommended_next_step="send to the fusion analyst / operator to choose; do not merge",
        )
    if top.score >= cfg.match_threshold:
        return MatchDecision(
            outcome=CandidateOutcome.MATCH_CANDIDATE, selected_incident_id=top.incident_id,
            candidates=ranked, config_version=version,
            explanation=f"{top.incident_id} scored {top.score:.2f} >= {cfg.match_threshold} "
                        f"(T={top.components.T}, G={top.components.G}, K={top.components.K}, "
                        f"A={top.components.A}, Q={top.components.Q})",
            recommended_next_step="associate as supporting evidence; heuristic score, not a "
                                  "probability",
        )
    if top.score >= cfg.review_threshold:
        return MatchDecision(
            outcome=CandidateOutcome.NEEDS_REVIEW, candidates=ranked, config_version=version,
            explanation=f"best candidate {top.incident_id} scored {top.score:.2f}, between the "
                        f"review ({cfg.review_threshold}) and match ({cfg.match_threshold}) "
                        "thresholds",
            recommended_next_step="operator review before association",
        )
    return MatchDecision(
        outcome=CandidateOutcome.NO_MATCH, candidates=ranked, config_version=version,
        explanation=f"best candidate {top.incident_id} scored {top.score:.2f} < review "
                    f"threshold {cfg.review_threshold}",
        recommended_next_step="open a provisional incident if the event is anomalous; otherwise "
                              "record as unmatched",
    )
