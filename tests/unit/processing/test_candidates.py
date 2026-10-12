"""Stages D/E: candidate scoring, hard rejections and decisions."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.processing.candidates import decide, score_candidate
from app.processing.config import CandidateConfig
from app.schemas.candidate import CandidateIncident, CandidateOutcome
from tests.fixtures.processing.factory import LAT, LON, T0, make_event, report, traffic, water

CFG = CandidateConfig()


def incident(iid="inc_a", *, families=("hydro",), lat=LAT, lon=LON, minutes=0, span=10,
             subjects=("place:WGD-04",), areas=()):
    return CandidateIncident(
        incident_id=iid, status="provisional", families=list(families),
        first_event_time=T0 + timedelta(minutes=minutes),
        last_event_time=T0 + timedelta(minutes=minutes + span),
        latitude=lat, longitude=lon, subjects=list(subjects), areas=list(areas))


def test_strong_temporal_and_spatial_compatibility_matches():
    s = score_candidate(water("e", 1.2, minutes=5), incident(), CFG, quality=1.0)
    assert s.components.T == 1 and s.components.G == 1 and s.components.K == 1
    assert s.components.A == 1 and s.score == 1.0
    d = decide([s], CFG)
    assert d.outcome == CandidateOutcome.MATCH_CANDIDATE and d.selected_incident_id == "inc_a"


def test_compatible_types_partially_scored_and_incompatible_hard_rejected():
    rep = report("r", "flooded underpass", minutes=5)
    assert score_candidate(rep, incident(), CFG, quality=0.6).components.K == 1.0
    air = make_event("a", event_type="air_quality_observed", source_id="airquality.live",
                     place_id=None, minutes=5, measurements=[
                         {"name": "pm25_concentration", "value": 90, "unit": "ug/m3",
                          "aggregation": "average", "period_seconds": 3600}])
    s = score_candidate(air, incident(), CFG, quality=1.0)
    assert s.hard_rejected and s.components.K == 0
    assert decide([s], CFG).outcome == CandidateOutcome.NO_MATCH


def test_missing_coordinates_never_counted_as_colocated():
    rep = report("r", "water", lat=None, lon=None, area="Andheri East", minutes=5)
    s = score_candidate(rep, incident(), CFG, quality=0.6)
    assert s.components.G == 0 and s.distance_m is None
    assert any("spatial compatibility unknown" in x for x in s.evidence_against)
    s2 = score_candidate(rep, incident(areas=("andheri east",)), CFG, quality=0.6)
    assert s2.components.G == CFG.area_match_spatial_score


def test_two_equally_plausible_candidates_are_ambiguous_and_both_retained():
    e = water("e", 1.2, minutes=5, place_id=None)
    a = score_candidate(e, incident("inc_a", subjects=()), CFG, quality=1.0)
    b = score_candidate(e, incident("inc_b", subjects=()), CFG, quality=1.0)
    d = decide([a, b], CFG)
    assert d.outcome == CandidateOutcome.AMBIGUOUS and d.selected_incident_id is None
    assert {c.incident_id for c in d.candidates} == {"inc_a", "inc_b"}


def test_outside_time_window_rejected():
    s = score_candidate(water("e", 1.2, minutes=600), incident(), CFG, quality=1.0)
    assert s.hard_rejected and "time window" in s.rejection_reason


def test_close_in_time_but_geographically_unrelated():
    far = water("e", 1.2, minutes=5, lat=19.40, lon=72.85, place_id="WGD-99")
    s = score_candidate(far, incident(), CFG, quality=1.0)
    assert s.hard_rejected and "geographically unrelated" in s.rejection_reason


def test_late_event_uses_event_time_not_arrival_order():
    late = water("e", 1.2, minutes=-30, ingest_delay_s=7200)  # observed before the incident
    s = score_candidate(late, incident(), CFG, quality=0.95)
    assert 0 < s.components.T < 1 and s.time_delta_seconds < 0 and not s.hard_rejected


def test_no_candidates_is_no_match():
    d = decide([], CFG)
    assert d.outcome == CandidateOutcome.NO_MATCH and "provisional" in d.recommended_next_step


def test_poor_quality_and_approximate_location_lower_the_score():
    good = score_candidate(traffic("t", 0.2, minutes=5), incident(families=("traffic",),
                           subjects=("place:seg-77",)), CFG, quality=1.0)
    poor = score_candidate(traffic("t2", 0.2, minutes=5, precision="approximate"),
                           incident(families=("traffic",), subjects=("place:seg-77",)), CFG,
                           quality=0.4)
    assert poor.score < good.score
    assert any("low data-quality" in x for x in poor.evidence_against)
    assert any("approximate" in x for x in poor.evidence_against)


def test_breakdown_is_consistent_with_score():
    s = score_candidate(report("r", "water", minutes=20), incident(), CFG, quality=0.6)
    w, c = s.weights, s.components.model_dump()
    assert s.score == pytest.approx(sum(w[k] * c[k] for k in w) / sum(w.values()), abs=1e-3)
    assert 0 <= s.score <= 1 and s.score_type == "deterministic_match_heuristic"


def test_needs_review_band():
    # ~1.5 km away, traffic vs hydro (k=0.6), reduced quality: plausible but not a match.
    e = traffic("t", 0.2, minutes=5, place_id=None, lat=LAT + 0.0135)
    s = score_candidate(e, incident(subjects=()), CFG, quality=0.6)
    assert CFG.review_threshold <= s.score < CFG.match_threshold
    assert decide([s], CFG).outcome == CandidateOutcome.NEEDS_REVIEW
