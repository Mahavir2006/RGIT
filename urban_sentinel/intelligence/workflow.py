from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from urban_sentinel import SCHEMA_VERSION
from urban_sentinel.core.logging import log_event
from urban_sentinel.domain.actions import catalogue_by_id
from urban_sentinel.domain.models import (
    AssociationDecision,
    IncidentSummary,
    ProcessedWorkflowInput,
)
from urban_sentinel.intelligence.agents.causal import deterministic_causal
from urban_sentinel.intelligence.agents.fusion import deterministic_fusion
from urban_sentinel.intelligence.agents.impact import deterministic_impact
from urban_sentinel.intelligence.agents.signal import deterministic_signal
from urban_sentinel.intelligence.exceptions import (
    ConcurrentUpdateError,
    GraphUnavailableError,
    InvalidAgentOutput,
    LlmTimeoutError,
)
from urban_sentinel.intelligence.models import (
    AgentRun,
    CascadeScenario,
    CausalAnalysis,
    FusionDecision,
    Hypothesis,
    ImpactAnalysis,
    ResponseRecommendation,
    SignalAnalysis,
    WorkflowStatus,
)
from urban_sentinel.intelligence.runtime import IntelligenceRuntime
from urban_sentinel.intelligence.state import IntelligenceState
from urban_sentinel.intelligence.triggers import association_is_ambiguous, needs_signal_agent
from urban_sentinel.intelligence.validation import (
    validate_fusion,
    validate_hypothesis,
    validate_recommendation,
    validate_scenario,
    validate_signal,
)

logger = logging.getLogger("urban_sentinel.workflow")

try:
    from langgraph.checkpoint.memory import MemorySaver
except ImportError:  # pragma: no cover
    from langgraph.checkpoint.memory import InMemorySaver as MemorySaver


class SignalLLMOutput(SignalAnalysis):
    pass


class FusionLLMOutput(FusionDecision):
    pass


class CausalLLMOutput(CausalAnalysis):
    pass


class ImpactLLMOutput(ImpactAnalysis):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _scope_includes(state: IntelligenceState, name: str) -> bool:
    scope = [item.upper() for item in state.get("reanalysis_scope") or ["ALL"]]
    return "ALL" in scope or name.upper() in scope


def _payload(state: IntelligenceState) -> ProcessedWorkflowInput:
    return ProcessedWorkflowInput.model_validate(state["input_payload"])


def _ids(state: IntelligenceState) -> tuple[set[str], set[str], set[str], set[str]]:
    return (
        set(state.get("known_event_ids") or []),
        set(state.get("known_incident_ids") or []),
        set(state.get("known_asset_ids") or []),
        set(state.get("known_action_ids") or []),
    )


class IntelligenceWorkflow:
    def __init__(self, runtime: IntelligenceRuntime) -> None:
        self.runtime = runtime
        self.checkpointer = MemorySaver()
        self.graph = self._build()

    def _build(self):
        builder = StateGraph(IntelligenceState)
        builder.add_node("validate_input", self.validate_input)
        builder.add_node("retrieve_context", self.retrieve_context)
        builder.add_node("signal_intelligence", self.signal_intelligence)
        builder.add_node("incident_fusion", self.incident_fusion)
        builder.add_node("persist_association", self.persist_association)
        builder.add_node("causal_cascade", self.causal_cascade)
        builder.add_node("impact_response", self.impact_response)
        builder.add_node("validate_outputs", self.validate_outputs)
        builder.add_node("persist_results", self.persist_results)
        builder.add_node("consolidate", self.consolidate)

        builder.add_edge(START, "validate_input")
        builder.add_edge("validate_input", "retrieve_context")
        builder.add_conditional_edges(
            "retrieve_context",
            self._after_retrieve,
            {
                "signal_intelligence": "signal_intelligence",
                "incident_fusion": "incident_fusion",
                "persist_association": "persist_association",
                "persist_results": "persist_results",
            },
        )
        builder.add_conditional_edges(
            "signal_intelligence",
            self._after_signal,
            {
                "incident_fusion": "incident_fusion",
                "persist_association": "persist_association",
            },
        )
        builder.add_edge("incident_fusion", "persist_association")
        builder.add_conditional_edges(
            "persist_association",
            self._after_persist_assoc,
            {"causal_cascade": "causal_cascade", "impact_response": "impact_response"},
        )
        builder.add_edge("causal_cascade", "impact_response")
        builder.add_edge("impact_response", "validate_outputs")
        builder.add_edge("validate_outputs", "persist_results")
        builder.add_edge("persist_results", "consolidate")
        builder.add_edge("consolidate", END)
        return builder.compile(checkpointer=self.checkpointer)

    def _after_retrieve(self, state: IntelligenceState) -> str:
        if state.get("cache_hit"):
            return "persist_results"
        if state.get("skip_signal"):
            if state.get("skip_fusion"):
                return "persist_association"
            return "incident_fusion"
        return "signal_intelligence"

    def _after_signal(self, state: IntelligenceState) -> str:
        if state.get("skip_fusion"):
            return "persist_association"
        return "incident_fusion"

    def _after_persist_assoc(self, state: IntelligenceState) -> str:
        if _scope_includes(state, "CAUSAL"):
            return "causal_cascade"
        return "impact_response"

    def _record_run(
        self,
        state: IntelligenceState,
        *,
        agent_name: str,
        fallback_used: bool,
        retries: int,
        started: datetime,
        error: str | None = None,
        status: str = "completed",
    ) -> dict[str, Any]:
        finished = _now()
        run = AgentRun(
            run_id=str(uuid4()),
            agent_name=agent_name,
            status=status,
            model_version=self.runtime.llm.model_version,
            prompt_version=self.runtime.settings.prompt_version,
            started_at=started,
            finished_at=finished,
            latency_ms=(finished - started).total_seconds() * 1000,
            retries=retries,
            error=error,
            fallback_used=fallback_used,
        )
        runs = list(state.get("agent_runs") or [])
        runs.append(run.model_dump(mode="json"))
        # Publish each specialist completion so operator clients can follow a running workflow.
        self.runtime.operational.save_workflow(
            {**state, "workflow_id": state["workflow_id"], "agent_runs": runs,
             "status": WorkflowStatus.RUNNING.value}
        )
        log_event(
            logger,
            "agent_run",
            agent=agent_name,
            workflow_id=state.get("workflow_id"),
            latency_ms=run.latency_ms,
            retries=retries,
            fallback=fallback_used,
            error=error,
        )
        return {"agent_runs": runs}

    async def _complete_json(
        self,
        schema: type[BaseModel],
        system: str,
        user: str,
    ) -> BaseModel:
        timeout = self.runtime.settings.llm_timeout_seconds
        return await asyncio.wait_for(
            self.runtime.llm.complete_json(
                system=system, user=user, schema=schema, timeout=timeout
            ),
            timeout=timeout,
        )

    async def _with_retries(
        self,
        *,
        schema: type[BaseModel],
        system: str,
        user: str,
        validate,
        fallback,
    ) -> tuple[BaseModel, int, bool, str | None]:
        retries = 0
        last_error: str | None = None
        max_retries = self.runtime.settings.llm_max_retries
        if self.runtime.llm.available:
            while retries <= max_retries:
                try:
                    output = await self._complete_json(schema, system, user)
                    validate(output)
                    return output, retries, False, None
                except asyncio.TimeoutError as exc:
                    last_error = f"LLM timeout: {exc}"
                    break
                except LlmTimeoutError as exc:
                    last_error = str(exc)
                    break
                except (InvalidAgentOutput, ValidationError, ValueError) as exc:
                    last_error = str(exc)
                    retries += 1
                    continue
        result = fallback()
        return result, retries, True, last_error

    async def validate_input(self, state: IntelligenceState) -> dict[str, Any]:
        payload = _payload(state)
        errors = list(state.get("errors") or [])
        if not payload.normalized_events and not payload.trigger_event_ids:
            errors.append("No processed events supplied.")
        known_events = [event.event_id for event in payload.normalized_events]
        known_incidents = [item.incident_id for item in payload.incidents]
        if payload.incident:
            known_incidents.append(payload.incident.incident_id)
        known_incidents.extend(payload.candidate_incident_ids)
        if payload.incident_id:
            known_incidents.append(payload.incident_id)
        known_assets = [asset.asset_id for asset in payload.assets]
        if payload.incident:
            known_assets.extend(payload.incident.asset_ids)
        skip_signal = not needs_signal_agent(payload) or not _scope_includes(state, "SIGNAL")
        skip_fusion = (
            not association_is_ambiguous(payload, self.runtime.settings)
            or not _scope_includes(state, "FUSION")
        )
        return {
            "status": WorkflowStatus.RUNNING.value,
            "schema_version": SCHEMA_VERSION,
            "errors": errors,
            "known_event_ids": sorted(set(known_events)),
            "known_incident_ids": sorted(set(known_incidents)),
            "known_asset_ids": sorted(set(known_assets)),
            "known_action_ids": sorted(catalogue_by_id()),
            "skip_signal": skip_signal,
            "skip_fusion": skip_fusion,
            "incident_id": payload.incident_id
            or (payload.incident.incident_id if payload.incident else None),
            "trigger_event_ids": payload.trigger_event_ids,
            "candidate_incident_ids": payload.candidate_incident_ids,
            "normalized_events": [e.model_dump(mode="json") for e in payload.normalized_events],
            "anomaly_records": [a.model_dump(mode="json") for a in payload.anomaly_records],
            "correlation_results": [c.model_dump(mode="json") for c in payload.correlation_results],
            "source_health": [s.model_dump(mode="json") for s in payload.source_health],
            "expected_incident_version": payload.expected_incident_version,
        }

    async def retrieve_context(self, state: IntelligenceState) -> dict[str, Any]:
        payload = _payload(state)
        incident_id = state.get("incident_id")
        graph_degraded = False
        degraded_reason = None
        evidence: dict[str, Any] = {"graph_available": True}
        paths: list[dict[str, Any]] = []
        existing_h = []
        existing_s = []
        if incident_id:
            try:
                evidence_raw, graph_raw, hyps, scns, cascade = await asyncio.gather(
                    asyncio.to_thread(self.runtime.graph.get_incident_evidence, incident_id),
                    asyncio.to_thread(self.runtime.graph.get_incident_graph, incident_id),
                    asyncio.to_thread(self.runtime.graph.get_incident_hypotheses, incident_id),
                    asyncio.to_thread(self.runtime.graph.get_scenarios, incident_id),
                    asyncio.to_thread(
                        self.runtime.graph.get_cascade_paths,
                        incident_id,
                        self.runtime.settings.max_graph_depth,
                    ),
                )
                evidence = {
                    "graph_available": True,
                    "linked_event_ids": evidence_raw.get("event_ids", []),
                    "notes": [f"graph nodes={len(graph_raw.get('assets', []))}"],
                    "cascade_paths": [p.model_dump(mode="json") for p in cascade],
                    "existing_hypotheses": [h.model_dump(mode="json") for h in hyps],
                    "existing_scenarios": [s.model_dump(mode="json") for s in scns],
                }
                paths = evidence["cascade_paths"]
                existing_h = evidence["existing_hypotheses"]
                existing_s = evidence["existing_scenarios"]
            except GraphUnavailableError as exc:
                graph_degraded = True
                degraded_reason = str(exc)
                evidence = {
                    "graph_available": False,
                    "degraded_reason": degraded_reason,
                    "linked_event_ids": [],
                    "notes": ["Neo4j unavailable; graph evidence was not fabricated."],
                    "cascade_paths": [],
                    "existing_hypotheses": [],
                    "existing_scenarios": [],
                }
        fingerprint = self.runtime.cache.fingerprint(
            incident_id=incident_id,
            event_ids=payload.trigger_event_ids,
            evidence_version=payload.incident.evidence_version if payload.incident else "0",
            scope=payload.reanalysis_scope,
            schema_version=SCHEMA_VERSION,
        )
        cached = self.runtime.cache.get(fingerprint)
        patch: dict[str, Any] = {
            "evidence_context": evidence,
            "graph_degraded": graph_degraded,
            "cascade_paths_raw": paths,
            "hypotheses": existing_h,
            "cascade_scenarios": existing_s,
            "cache_key": fingerprint,
        }
        if cached and not payload.material_change:
            patch["cache_hit"] = True
            patch.update(cached)
            patch["skip_signal"] = True
            patch["skip_fusion"] = True
        return patch

    async def signal_intelligence(self, state: IntelligenceState) -> dict[str, Any]:
        started = _now()
        payload = _payload(state)
        events, _, _, _ = _ids(state)

        def fallback() -> SignalAnalysis:
            return deterministic_signal(payload)

        def validate(output: SignalAnalysis) -> None:
            validate_signal(output, events)

        user = (
            "Extract facts from processed events. Reference existing event IDs only. "
            "Do not invent events or rerun numerical anomaly detection. "
            f"events={state.get('normalized_events')} "
            f"health={state.get('source_health')} anomalies={state.get('anomaly_records')}"
        )
        output, retries, used_fallback, error = await self._with_retries(
            schema=SignalLLMOutput,
            system="You are the Urban Sentinel signal intelligence agent.",
            user=user,
            validate=validate,
            fallback=fallback,
        )
        if not used_fallback:
            output = output.model_copy(update={"used_fallback": False})
        run = self._record_run(
            state,
            agent_name="signal_intelligence",
            fallback_used=used_fallback,
            retries=retries,
            started=started,
            error=error,
            status="completed" if not error or used_fallback else "failed",
        )
        return {
            "signal_analysis": output.model_dump(mode="json"),
            "llm_degraded": used_fallback and bool(error),
            "errors": list(state.get("errors") or []) + ([error] if error and used_fallback else []),
            **run,
        }

    async def incident_fusion(self, state: IntelligenceState) -> dict[str, Any]:
        started = _now()
        payload = _payload(state)
        events, incidents, _, _ = _ids(state)
        decisions: list[FusionDecision] = []
        retries_total = 0
        used_fallback = False
        last_error = None
        for event_id in payload.trigger_event_ids or [e.event_id for e in payload.normalized_events]:

            def fallback(eid: str = event_id) -> FusionDecision:
                return deterministic_fusion(payload, self.runtime.settings, eid)

            def validate(output: FusionDecision) -> None:
                validate_fusion(output, events, incidents)

            output, retries, fb, error = await self._with_retries(
                schema=FusionLLMOutput,
                system="You are the Urban Sentinel incident fusion agent. Hard-rejection rules take precedence.",
                user=f"event_id={event_id} correlations={state.get('correlation_results')} candidates={payload.candidate_incident_ids}",
                validate=validate,
                fallback=fallback,
            )
            retries_total += retries
            used_fallback = used_fallback or fb
            last_error = error or last_error
            if not fb:
                output = output.model_copy(update={"used_fallback": False})
            decisions.append(output)
        primary = decisions[0] if decisions else None
        review = any(item.review_required for item in decisions)
        run = self._record_run(
            state,
            agent_name="incident_fusion",
            fallback_used=used_fallback,
            retries=retries_total,
            started=started,
            error=last_error,
        )
        return {
            "fusion_decisions": [item.model_dump(mode="json") for item in decisions],
            "fusion_decision": primary.model_dump(mode="json") if primary else None,
            "review_required": state.get("review_required", False) or review,
            **run,
        }

    async def persist_association(self, state: IntelligenceState) -> dict[str, Any]:
        payload = _payload(state)
        errors = list(state.get("errors") or [])
        review = bool(state.get("review_required"))
        decisions = [FusionDecision.model_validate(item) for item in state.get("fusion_decisions") or []]
        if not decisions:
            for event_id in payload.trigger_event_ids or [e.event_id for e in payload.normalized_events]:
                decisions.append(deterministic_fusion(payload, self.runtime.settings, event_id))
        incident_id = state.get("incident_id")
        graph_degraded = bool(state.get("graph_degraded"))
        attachments: dict[str, list[str]] = {}
        for decision in decisions:
            if decision.decision == AssociationDecision.AMBIGUOUS_REVIEW:
                review = True
            selected = decision.selected_incident_id or incident_id
            if not selected:
                continue
            incident_id = selected
            if decision.decision in {
                AssociationDecision.ATTACH_TO_INCIDENT,
                AssociationDecision.AMBIGUOUS_REVIEW,
            }:
                attachments.setdefault(selected, []).append(decision.event_id)
                if not graph_degraded:
                    try:
                        self.runtime.graph.link_event_to_incident(
                            decision.event_id,
                            selected,
                            decision=decision.decision.value,
                            run_id=state["workflow_id"],
                        )
                    except GraphUnavailableError as exc:
                        graph_degraded = True
                        errors.append(str(exc))
        for selected, event_ids in attachments.items():
            try:
                if payload.incident or self.runtime.operational.get_incident(selected):
                    if (
                        payload.incident
                        and payload.incident.incident_id == selected
                        and self.runtime.operational.get_incident(selected) is None
                    ):
                        self.runtime.operational.upsert_incident(payload.incident)
                    self.runtime.operational.attach_events(
                        selected,
                        event_ids,
                        expected_version=state.get("expected_incident_version"),
                    )
            except ConcurrentUpdateError as exc:
                errors.append(str(exc))
                review = True
        if payload.incident and incident_id == payload.incident.incident_id:
            if not self.runtime.operational.get_incident(incident_id):
                try:
                    self.runtime.operational.upsert_incident(
                        payload.incident,
                        expected_version=state.get("expected_incident_version"),
                    )
                except ConcurrentUpdateError as exc:
                    errors.append(str(exc))
                    review = True
        return {
            "fusion_decisions": [item.model_dump(mode="json") for item in decisions],
            "fusion_decision": decisions[0].model_dump(mode="json") if decisions else None,
            "incident_id": incident_id,
            "review_required": review,
            "errors": errors,
            "graph_degraded": graph_degraded,
        }

    async def causal_cascade(self, state: IntelligenceState) -> dict[str, Any]:
        started = _now()
        payload = _payload(state)
        events, _, assets, _ = _ids(state)
        from urban_sentinel.intelligence.models import DependencyPath

        raw_paths = state.get("evidence_context", {}).get("cascade_paths") or state.get(
            "cascade_paths_raw"
        ) or []
        paths = [DependencyPath.model_validate(item) if not isinstance(item, DependencyPath) else item for item in raw_paths]
        graph_available = not state.get("graph_degraded")

        def fallback() -> CausalAnalysis:
            return deterministic_causal(
                payload, state, paths, graph_available=graph_available
            )

        def validate(output: CausalAnalysis) -> None:
            for hyp in output.hypotheses:
                validate_hypothesis(hyp, events)
            if assets:
                for scn in output.cascade_scenarios:
                    validate_scenario(scn, assets)

        output, retries, used_fallback, error = await self._with_retries(
            schema=CausalLLMOutput,
            system="You propose hypotheses but do not establish causality. Use only provided event and asset IDs.",
            user=f"incident={state.get('incident_id')} events={state.get('normalized_events')} paths={raw_paths}",
            validate=validate,
            fallback=fallback,
        )
        if not used_fallback:
            output = output.model_copy(update={"used_fallback": False})
        run = self._record_run(
            state,
            agent_name="causal_cascade",
            fallback_used=used_fallback,
            retries=retries,
            started=started,
            error=error,
        )
        gaps = list(state.get("evidence_gaps") or []) + output.suggested_additional_evidence
        return {
            "hypotheses": [h.model_dump(mode="json") for h in output.hypotheses],
            "cascade_scenarios": [s.model_dump(mode="json") for s in output.cascade_scenarios],
            "evidence_gaps": gaps,
            **run,
        }

    async def impact_response(self, state: IntelligenceState) -> dict[str, Any]:
        started = _now()
        payload = _payload(state)
        events, _, _, actions = _ids(state)
        causal = CausalAnalysis(
            hypotheses=[Hypothesis.model_validate(h) for h in state.get("hypotheses") or []],
            cascade_scenarios=[
                CascadeScenario.model_validate(s) for s in state.get("cascade_scenarios") or []
            ],
            suggested_additional_evidence=list(state.get("evidence_gaps") or []),
            insufficient_evidence=any(
                (h.get("claim") == "INSUFFICIENT_EVIDENCE") for h in (state.get("hypotheses") or [])
            ),
        )
        signal = (
            SignalAnalysis.model_validate(state["signal_analysis"])
            if state.get("signal_analysis")
            else None
        )

        def fallback() -> ImpactAnalysis:
            return deterministic_impact(payload, self.runtime.settings, causal, signal)

        def validate(output: ImpactAnalysis) -> None:
            for rec in output.candidate_actions:
                validate_recommendation(rec, events, actions)

        output, retries, used_fallback, error = await self._with_retries(
            schema=ImpactLLMOutput,
            system="You explain severity and rank catalogue actions. Do not compute safety-critical scores. Do not dispatch.",
            user=f"incident={state.get('incident_id')} hypotheses={state.get('hypotheses')}",
            validate=validate,
            fallback=fallback,
        )
        if not used_fallback:
            output = output.model_copy(update={"used_fallback": False})
        review = bool(state.get("review_required")) or any(
            rec.approval_required for rec in output.candidate_actions
        )
        run = self._record_run(
            state,
            agent_name="impact_response",
            fallback_used=used_fallback,
            retries=retries,
            started=started,
            error=error,
        )
        return {
            "severity_assessment": output.severity.model_dump(mode="json"),
            "candidate_actions": [a.model_dump(mode="json") for a in output.candidate_actions],
            "operator_summary": output.operator_summary,
            "evidence_gaps": list(state.get("evidence_gaps") or []) + output.uncertainty_notes,
            "review_required": review,
            **run,
        }

    async def validate_outputs(self, state: IntelligenceState) -> dict[str, Any]:
        events, incidents, assets, actions = _ids(state)
        errors = list(state.get("errors") or [])
        if state.get("signal_analysis"):
            try:
                validate_signal(SignalAnalysis.model_validate(state["signal_analysis"]), events)
            except InvalidAgentOutput as exc:
                errors.append(str(exc))
        for raw in state.get("fusion_decisions") or []:
            try:
                validate_fusion(FusionDecision.model_validate(raw), events, incidents)
            except InvalidAgentOutput as exc:
                errors.append(str(exc))
        for raw in state.get("hypotheses") or []:
            try:
                validate_hypothesis(Hypothesis.model_validate(raw), events)
            except InvalidAgentOutput as exc:
                errors.append(str(exc))
        if assets:
            for raw in state.get("cascade_scenarios") or []:
                try:
                    validate_scenario(CascadeScenario.model_validate(raw), assets)
                except InvalidAgentOutput as exc:
                    errors.append(str(exc))
        for raw in state.get("candidate_actions") or []:
            try:
                validate_recommendation(
                    ResponseRecommendation.model_validate(raw),
                    events,
                    actions,
                )
            except InvalidAgentOutput as exc:
                errors.append(str(exc))
        return {"errors": errors}

    async def persist_results(self, state: IntelligenceState) -> dict[str, Any]:
        incident_id = state.get("incident_id")
        errors = list(state.get("errors") or [])
        graph_degraded = bool(state.get("graph_degraded"))
        hyps = [Hypothesis.model_validate(item) for item in state.get("hypotheses") or []]
        scns = [CascadeScenario.model_validate(item) for item in state.get("cascade_scenarios") or []]
        recs = [ResponseRecommendation.model_validate(item) for item in state.get("candidate_actions") or []]
        if incident_id:
            self.runtime.operational.replace_hypotheses(incident_id, hyps)
            self.runtime.operational.replace_scenarios(incident_id, scns)
            self.runtime.operational.replace_recommendations(incident_id, recs)
        if not graph_degraded:
            try:
                for hyp in hyps:
                    self.runtime.graph.upsert_hypothesis(hyp)
                    self.runtime.graph.link_evidence_to_hypothesis(
                        hyp.hypothesis_id,
                        supporting_event_ids=hyp.supporting_event_ids,
                        contradicting_event_ids=hyp.contradicting_event_ids,
                    )
                for scn in scns:
                    self.runtime.graph.upsert_scenario(scn)
                for raw in state.get("agent_runs") or []:
                    self.runtime.graph.upsert_agent_run(AgentRun.model_validate(raw))
            except GraphUnavailableError as exc:
                graph_degraded = True
                errors.append(str(exc))
        cache_key = state.get("cache_key")
        if cache_key:
            self.runtime.cache.put(
                cache_key,
                {
                    "hypotheses": state.get("hypotheses") or [],
                    "cascade_scenarios": state.get("cascade_scenarios") or [],
                    "candidate_actions": state.get("candidate_actions") or [],
                    "severity_assessment": state.get("severity_assessment"),
                    "signal_analysis": state.get("signal_analysis"),
                    "fusion_decisions": state.get("fusion_decisions") or [],
                    "operator_summary": state.get("operator_summary"),
                },
            )
        return {"errors": errors, "graph_degraded": graph_degraded}

    async def consolidate(self, state: IntelligenceState) -> dict[str, Any]:
        errors = list(state.get("errors") or [])
        if state.get("graph_degraded") or state.get("llm_degraded"):
            status = WorkflowStatus.DEGRADED.value
        elif state.get("review_required"):
            status = WorkflowStatus.REVIEW_REQUIRED.value
        elif errors:
            status = WorkflowStatus.FAILED.value
        else:
            status = WorkflowStatus.COMPLETED.value
        patch = {"status": status}
        self.runtime.operational.save_workflow({**state, **patch})
        return patch

    async def ainvoke(self, payload: ProcessedWorkflowInput, workflow_id: str) -> IntelligenceState:
        initial: IntelligenceState = {
            "workflow_id": workflow_id,
            "input_payload": payload.model_dump(mode="json"),
            "reanalysis_scope": payload.reanalysis_scope,
            "material_change": payload.material_change,
            "schema_version": SCHEMA_VERSION,
            "errors": [],
            "agent_runs": [],
            "review_required": False,
            "status": WorkflowStatus.RUNNING.value,
        }
        config = {"configurable": {"thread_id": workflow_id}}
        timeout = self.runtime.settings.workflow_timeout_seconds
        started = perf_counter()
        try:
            result = await asyncio.wait_for(
                self.graph.ainvoke(initial, config=config),
                timeout=timeout,
            )
        except TimeoutError:
            result = {**initial, "status": WorkflowStatus.FAILED.value, "errors": ["workflow timeout"]}
        log_event(
            logger,
            "workflow_complete",
            workflow_id=workflow_id,
            status=result.get("status"),
            latency_ms=(perf_counter() - started) * 1000,
        )
        self.runtime.operational.save_workflow(result)  # type: ignore[arg-type]
        return result  # type: ignore[return-value]
