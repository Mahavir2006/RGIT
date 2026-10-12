"""Pure stage sequencing for one event: validation -> dedup -> anomalies -> (match).

No I/O. The service layer loads bounded context (neighbours, history, candidate incidents) and
persists the outputs; this module only decides. Same inputs + same config => same decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.processing.anomaly import AnomalyContext, detect_anomalies, evaluated_rule_subjects
from app.processing.candidates import decide, score_candidate
from app.processing.config import ProcessingConfig
from app.processing.correlation import INCIDENT_FAMILIES, family_of, subject_of
from app.processing.deduplicate import detect_duplicate
from app.processing.validator import validate_event
from app.schemas.anomaly import SEVERITY_ORDINAL, AnomalyFinding, AnomalyKind
from app.schemas.candidate import CandidateIncident, MatchDecision
from app.schemas.event import CanonicalEvent
from app.schemas.processing import DedupDecision, DedupResult, ValidationResult

__all__ = ["StageOutput", "evaluate_event", "match_event", "eligible_for_matching"]


@dataclass(slots=True)
class StageOutput:
    validation: ValidationResult
    dedup: DedupResult | None = None
    findings: list[AnomalyFinding] = field(default_factory=list)
    evaluated: list[tuple[str, str, str, str | None]] = field(default_factory=list)
    eligible: bool = False
    eligibility_reason: str = ""

    @property
    def peak_severity(self) -> str | None:
        env = [f.severity.value for f in self.findings if f.kind == AnomalyKind.ENVIRONMENTAL]
        return max(env, key=SEVERITY_ORDINAL.__getitem__) if env else None


def eligible_for_matching(event: CanonicalEvent, findings: list[AnomalyFinding],
                          dedup: DedupResult) -> tuple[bool, str]:
    """Not every event belongs in an incident. Only incident-relevant signals are matched."""
    fam = family_of(event.event_type)
    if fam not in INCIDENT_FAMILIES:
        return False, f"event type {event.event_type.value} is context, not an incident signal"
    if dedup.decision == DedupDecision.EXACT_DUPLICATE:
        return False, f"exact duplicate of {dedup.duplicate_of}; original carries the evidence"
    if fam.startswith("report_"):
        return True, "citizen report (unverified observation)"
    if any(f.kind == AnomalyKind.ENVIRONMENTAL for f in findings):
        return True, "environmental anomaly detected"
    return False, "normal reading; no anomaly to associate"


def evaluate_event(
    event: CanonicalEvent,
    cfg: ProcessingConfig,
    *,
    now: datetime,
    neighbours: list[CanonicalEvent],
    anomaly_ctx: AnomalyContext,
) -> StageOutput:
    reliability = cfg.candidates.source_reliability.get(event.source_kind.value, 1.0)
    validation = validate_event(event, cfg.validation, now=now, source_reliability=reliability)
    out = StageOutput(validation=validation)
    if not validation.processable:
        out.eligibility_reason = f"validation {validation.verdict.value}"
        return out
    out.dedup = detect_duplicate(event, neighbours, cfg.dedup)
    if out.dedup.decision != DedupDecision.EXACT_DUPLICATE:
        # An exact duplicate would only re-fire the original's anomalies.
        out.findings = detect_anomalies(event, anomaly_ctx, cfg)
        subject = subject_of(event)
        out.evaluated = [
            (rid, event.source_id, subject,
             next(r.measurement for r in cfg.thresholds if r.rule_id == rid))
            for rid in evaluated_rule_subjects(event, cfg)
        ]
    out.eligible, out.eligibility_reason = eligible_for_matching(event, out.findings, out.dedup)
    return out


def match_event(event: CanonicalEvent, candidates: list[CandidateIncident],
                cfg: ProcessingConfig, *, quality: float) -> MatchDecision:
    scores = [score_candidate(event, c, cfg.candidates, quality=quality) for c in candidates]
    return decide(scores, cfg.candidates)
