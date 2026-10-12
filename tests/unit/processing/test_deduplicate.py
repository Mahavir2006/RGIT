"""Stage B: processing fingerprint and near-duplicate decisions."""

from __future__ import annotations

from app.processing.config import DedupConfig
from app.processing.deduplicate import detect_duplicate, processing_fingerprint
from app.schemas.event import CanonicalEvent
from app.schemas.processing import DedupDecision
from tests.fixtures.processing.factory import report, water

CFG = DedupConfig()


def test_fingerprint_ignores_json_key_order_and_metadata():
    a = water("a", 1.0)
    data = a.model_dump()
    reordered = {k: data[k] for k in reversed(list(data))}
    reordered.update(event_id="b", idempotency_key="idk_other", fingerprint="fp_other",
                     payload={"provider_meta": {"x": 1}})
    b = CanonicalEvent.model_validate(reordered)
    assert processing_fingerprint(a, CFG) == processing_fingerprint(b, CFG)


def test_same_observation_under_another_id_is_exact_duplicate_and_not_corroboration():
    a = water("a", 1.0)
    b = water("b", 1.0, source_id="water.replay")  # same category, other delivery path
    r = detect_duplicate(b, [a], CFG)
    assert r.decision == DedupDecision.EXACT_DUPLICATE
    assert r.duplicate_of == "a" and r.counts_as_corroboration is False


def test_similar_but_distinct_events_are_unique():
    a = water("a", 1.0)
    b = water("b", 1.3, minutes=10)  # different reading, ten minutes later
    assert detect_duplicate(b, [a], CFG).decision == DedupDecision.UNIQUE
    c = water("c", 1.0, place_id="WGD-09", lat=19.2, lon=72.9)  # different station
    assert detect_duplicate(c, [a], CFG).decision == DedupDecision.UNIQUE


def test_near_identical_reading_flagged_possible_duplicate_for_review():
    a = water("a", 1.0)
    b = water("b", 1.0, minutes=2)  # same value, different time bucket
    r = detect_duplicate(b, [a], CFG)
    assert r.decision == DedupDecision.POSSIBLE_DUPLICATE
    assert r.counts_as_corroboration is False


def test_two_citizens_with_different_words_are_independent():
    a = report("r1", "knee deep water near the metro")
    b = report("r2", "road flooded, cars stuck", minutes=1)
    assert detect_duplicate(b, [a], CFG).decision == DedupDecision.UNIQUE


def test_event_never_duplicates_itself():
    a = water("a", 1.0)
    assert detect_duplicate(a, [a], CFG).decision == DedupDecision.UNIQUE
