"""Candidate incident matching schemas.

Scores are deterministic heuristics in [0, 1]. They are **not** calibrated probabilities: a score
of 0.82 does not mean an 82 % chance that the event belongs to the incident.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

__all__ = ["CandidateOutcome", "ComponentScores", "CandidateIncident", "CandidateScore",
           "MatchDecision"]


class CandidateOutcome(str, Enum):
    MATCH_CANDIDATE = "MATCH_CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NO_MATCH = "NO_MATCH"


class ComponentScores(BaseModel):
    """Each component is in [0, 1]. ``None`` means not computable for this pair."""

    T: float = Field(ge=0, le=1, description="temporal compatibility")
    G: float = Field(ge=0, le=1, description="spatial compatibility")
    K: float = Field(ge=0, le=1, description="event-type compatibility")
    A: float = Field(ge=0, le=1, description="shared asset/station/segment/area")
    Q: float = Field(ge=0, le=1, description="data-quality adjustment")


class CandidateIncident(BaseModel):
    """What the scorer needs to know about an existing incident or provisional cluster."""

    incident_id: str
    status: str
    families: list[str]
    first_event_time: datetime
    last_event_time: datetime
    latitude: float | None = None
    longitude: float | None = None
    radius_m: float | None = None
    subjects: list[str] = Field(default_factory=list)
    areas: list[str] = Field(default_factory=list)


class CandidateScore(BaseModel):
    incident_id: str
    score: float = Field(ge=0, le=1, description="weighted heuristic, NOT a probability")
    score_type: str = "deterministic_match_heuristic"
    components: ComponentScores
    weights: dict[str, float]
    time_delta_seconds: float
    distance_m: float | None = None
    shared: list[str] = Field(default_factory=list)
    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)
    hard_rejected: bool = False
    rejection_reason: str | None = None
    rank: int = 0


class MatchDecision(BaseModel):
    outcome: CandidateOutcome
    selected_incident_id: str | None = None
    candidates: list[CandidateScore] = Field(default_factory=list)
    explanation: str
    recommended_next_step: str
    config_version: str
