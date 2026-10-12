"""Candidate retrieval (bounded, indexed) and persistence of match decisions."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import ensure_aware, utc_now
from app.db.processing_models import CandidateMatchModel, IncidentModel
from app.processing.config import CandidateConfig
from app.processing.correlation import area_of, family_of, subject_of
from app.schemas.anomaly import SEVERITY_ORDINAL
from app.schemas.candidate import CandidateIncident, CandidateOutcome, MatchDecision
from app.schemas.event import CanonicalEvent

__all__ = ["CandidateService", "OPEN_STATUSES"]

OPEN_STATUSES = ("provisional", "open")


def _sid(*parts: str, prefix: str, n: int = 24) -> str:
    return prefix + hashlib.sha256("|".join(parts).encode()).hexdigest()[:n]


class CandidateService:
    def __init__(self, session: AsyncSession, cfg: CandidateConfig) -> None:
        self.session = session
        self.cfg = cfg

    async def retrieve(self, event: CanonicalEvent) -> list[CandidateIncident]:
        """Open incidents within the time window and a bounding box (if the event is located)."""
        w = timedelta(seconds=self.cfg.time_window_seconds)
        t = event.event_time
        stmt = select(IncidentModel).where(
            IncidentModel.status.in_(OPEN_STATUSES),
            IncidentModel.last_event_time >= t - w,
            IncidentModel.first_event_time <= t + w,
        )
        loc = event.location
        if loc is not None and loc.has_coordinates:
            reach = self.cfg.search_radius_m * self.cfg.hard_reject_radius_factor
            dlat = reach / 111_000.0
            dlon = reach / 60_000.0  # conservative for |lat| < ~55 degrees
            stmt = stmt.where(or_(
                IncidentModel.latitude.is_(None),
                and_(IncidentModel.latitude.between(loc.latitude - dlat, loc.latitude + dlat),
                     IncidentModel.longitude.between(loc.longitude - dlon, loc.longitude + dlon)),
            ))
        stmt = stmt.order_by(IncidentModel.last_event_time.desc(), IncidentModel.incident_id) \
                   .limit(self.cfg.max_candidates)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [CandidateIncident(
            incident_id=r.incident_id, status=r.status, families=list(r.families),
            first_event_time=ensure_aware(r.first_event_time),
            last_event_time=ensure_aware(r.last_event_time),
            latitude=r.latitude, longitude=r.longitude, radius_m=r.radius_m,
            subjects=list(r.subjects), areas=list(r.areas),
        ) for r in rows]

    async def persist(
        self,
        event: CanonicalEvent,
        decision: MatchDecision,
        *,
        eligible_to_seed: bool,
        corroborating: bool,
        severity: str | None,
        run_id: str,
        processing_version: str,
    ) -> tuple[str | None, list[str]]:
        """Store every scored candidate; attach or seed. Returns (incident_id, candidate_ids)."""
        ids: list[str] = []
        for c in decision.candidates:
            cid = _sid(event.event_id, c.incident_id, processing_version, prefix="cand_")
            ids.append(cid)
            if await self.session.get(CandidateMatchModel, cid) is not None:
                continue  # idempotent retry
            attach = (decision.outcome == CandidateOutcome.MATCH_CANDIDATE
                      and c.incident_id == decision.selected_incident_id and corroborating)
            outcome = (decision.outcome.value if c.incident_id == decision.selected_incident_id
                       or decision.outcome != CandidateOutcome.MATCH_CANDIDATE
                       else CandidateOutcome.NO_MATCH.value)
            if c.hard_rejected:
                outcome = CandidateOutcome.NO_MATCH.value
            if decision.outcome == CandidateOutcome.MATCH_CANDIDATE and not corroborating \
                    and c.incident_id == decision.selected_incident_id:
                c.evidence_against.append(
                    "event is a (possible) duplicate: linked for traceability but not counted "
                    "as independent corroboration")
            if not await self._insert(CandidateMatchModel(
                candidate_id=cid, event_id=event.event_id, incident_id=c.incident_id,
                outcome=outcome, attached=attach, seed=False, score=c.score, rank=c.rank,
                components=c.components.model_dump(), weights=c.weights,
                evidence_for=c.evidence_for, evidence_against=c.evidence_against,
                time_delta_seconds=c.time_delta_seconds, distance_m=c.distance_m,
                shared=c.shared, hard_rejected=c.hard_rejected,
                rejection_reason=c.rejection_reason, explanation=decision.explanation,
                recommended_next_step=decision.recommended_next_step,
                config_version=decision.config_version, processing_version=processing_version,
                run_id=run_id, created_at=utc_now(),
            )):
                continue
            if attach:
                await self._attach(c.incident_id, event, severity)

        if decision.outcome == CandidateOutcome.MATCH_CANDIDATE:
            return decision.selected_incident_id, ids
        if decision.outcome == CandidateOutcome.NO_MATCH and eligible_to_seed and corroborating:
            incident_id = await self._seed(event, severity, run_id, processing_version)
            ids.append(_sid(event.event_id, incident_id, processing_version, prefix="cand_"))
            return incident_id, ids
        return None, ids

    async def _insert(self, row: CandidateMatchModel) -> bool:
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError:
            return False
        return True

    async def _attach(self, incident_id: str, event: CanonicalEvent, severity: str | None) -> None:
        inc = await self.session.get(IncidentModel, incident_id)
        if inc is None:
            return
        fam = family_of(event.event_type)
        if fam and fam not in inc.families:
            inc.families = sorted({*inc.families, fam})
        subj = subject_of(event)
        if subj.startswith("place:") and subj not in inc.subjects:
            inc.subjects = sorted({*inc.subjects, subj})
        area = area_of(event)
        if area and area not in inc.areas:
            inc.areas = sorted({*inc.areas, area})
        inc.first_event_time = min(ensure_aware(inc.first_event_time), event.event_time)
        inc.last_event_time = max(ensure_aware(inc.last_event_time), event.event_time)
        loc = event.location
        if loc is not None and loc.has_coordinates:
            n = inc.located_event_count
            if inc.latitude is None:
                inc.latitude, inc.longitude = loc.latitude, loc.longitude
            else:
                inc.latitude = (inc.latitude * n + loc.latitude) / (n + 1)  # type: ignore[operator]
                inc.longitude = (inc.longitude * n + loc.longitude) / (n + 1)  # type: ignore[operator]
            inc.located_event_count = n + 1
        if severity and (inc.peak_severity is None
                         or SEVERITY_ORDINAL[severity] > SEVERITY_ORDINAL[inc.peak_severity]):
            inc.peak_severity = severity
        inc.event_count += 1
        inc.version += 1
        inc.updated_at = utc_now()

    async def _seed(self, event: CanonicalEvent, severity: str | None, run_id: str,
                    processing_version: str) -> str:
        incident_id = _sid(event.event_id, prefix="inc_", n=16)
        if await self.session.get(IncidentModel, incident_id) is None:
            fam = family_of(event.event_type) or "unknown"
            loc = event.location
            located = loc is not None and loc.has_coordinates
            place = area_of(event) or subject_of(event)
            subj = subject_of(event)
            now = utc_now()
            row = IncidentModel(
                incident_id=incident_id, status="provisional",
                title=f"Provisional {fam.replace('_', ' ')} incident near {place}",
                seed_event_id=event.event_id, families=[fam],
                subjects=[subj] if subj.startswith("place:") else [],
                areas=[area_of(event)] if area_of(event) else [],
                first_event_time=event.event_time, last_event_time=event.event_time,
                latitude=loc.latitude if located else None,  # type: ignore[union-attr]
                longitude=loc.longitude if located else None,  # type: ignore[union-attr]
                located_event_count=1 if located else 0,
                radius_m=(loc.accuracy_m if located else None),  # type: ignore[union-attr]
                event_count=1, peak_severity=severity, version=1, created_at=now,
                updated_at=now, processing_version=processing_version,
            )
            try:
                async with self.session.begin_nested():
                    self.session.add(row)
            except IntegrityError:
                existing = (await self.session.execute(
                    select(IncidentModel).where(IncidentModel.seed_event_id == event.event_id)
                )).scalar_one()
                return existing.incident_id
            await self._insert(CandidateMatchModel(
                candidate_id=_sid(event.event_id, incident_id, processing_version, prefix="cand_"),
                event_id=event.event_id, incident_id=incident_id, outcome="PROVISIONAL_SEED",
                attached=True, seed=True, score=1.0, rank=1, components={}, weights={},
                evidence_for=["event seeded this provisional cluster: no existing candidate "
                              "passed the match threshold"],
                evidence_against=[], explanation="provisional cluster seeded by an anomalous or "
                "reported event; requires corroboration before it is treated as an incident",
                recommended_next_step="await corroborating events or operator confirmation",
                config_version=f"cand-{self.cfg.version}", processing_version=processing_version,
                run_id=run_id, created_at=now,
            ))
        return incident_id
