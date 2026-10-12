from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from urban_sentinel.intelligence.exceptions import GraphUnavailableError
from urban_sentinel.intelligence.models import (
    AgentRun,
    CascadeScenario,
    DependencyPath,
    Hypothesis,
)


class GraphRepository(Protocol):
    available: bool

    def get_incident_evidence(self, incident_id: str) -> dict[str, Any]: ...
    def get_incident_hypotheses(self, incident_id: str) -> list[Hypothesis]: ...
    def link_event_to_incident(
        self, event_id: str, incident_id: str, *, decision: str, run_id: str
    ) -> None: ...
    def upsert_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis: ...
    def link_evidence_to_hypothesis(
        self,
        hypothesis_id: str,
        *,
        supporting_event_ids: list[str],
        contradicting_event_ids: list[str],
    ) -> None: ...
    def upsert_agent_run(self, run: AgentRun) -> None: ...
    def upsert_scenario(self, scenario: CascadeScenario) -> CascadeScenario: ...
    def get_cascade_paths(
        self, incident_id: str, max_depth: int
    ) -> list[DependencyPath]: ...
    def get_incident_graph(self, incident_id: str) -> dict[str, Any]: ...
    def get_scenarios(self, incident_id: str) -> list[CascadeScenario]: ...


class InMemoryGraphRepository:
    """Idempotent in-memory stand-in used until the Neo4j team wires production queries."""

    def __init__(self) -> None:
        self.available = True
        self.hypotheses: dict[str, Hypothesis] = {}
        self.scenarios: dict[str, CascadeScenario] = {}
        self.agent_runs: dict[str, AgentRun] = {}
        self.event_links: dict[tuple[str, str], dict[str, str]] = {}
        self.hypothesis_links: dict[str, dict[str, list[str]]] = {}
        self.incident_events: dict[str, set[str]] = {}
        self.incident_assets: dict[str, list[str]] = {}
        self.edges: list[tuple[str, str, str]] = []
        self.write_counts: dict[str, int] = {}
        self.unavailable_reason: str | None = None

    def mark_unavailable(self, reason: str = "neo4j unavailable") -> None:
        self.available = False
        self.unavailable_reason = reason

    def mark_available(self) -> None:
        self.available = True
        self.unavailable_reason = None

    def _require(self) -> None:
        if not self.available:
            raise GraphUnavailableError(self.unavailable_reason or "graph unavailable")

    def seed_assets(self, incident_id: str, asset_ids: list[str]) -> None:
        self.incident_assets[incident_id] = list(asset_ids)

    def seed_edges(self, edges: list[tuple[str, str, str]]) -> None:
        self.edges = list(edges)

    def get_incident_evidence(self, incident_id: str) -> dict[str, Any]:
        self._require()
        return {
            "incident_id": incident_id,
            "event_ids": sorted(self.incident_events.get(incident_id, set())),
            "retrieved_at": datetime.now(UTC).isoformat(),
        }

    def get_incident_hypotheses(self, incident_id: str) -> list[Hypothesis]:
        self._require()
        return [h for h in self.hypotheses.values() if h.incident_id == incident_id]

    def link_event_to_incident(
        self, event_id: str, incident_id: str, *, decision: str, run_id: str
    ) -> None:
        self._require()
        key = (event_id, incident_id)
        if key in self.event_links:
            return
        self.write_counts[f"link:{event_id}:{incident_id}"] = (
            self.write_counts.get(f"link:{event_id}:{incident_id}", 0) + 1
        )
        self.event_links[key] = {"decision": decision, "run_id": run_id}
        self.incident_events.setdefault(incident_id, set()).add(event_id)

    def upsert_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis:
        self._require()
        key = f"hyp:{hypothesis.hypothesis_id}"
        existing = self.hypotheses.get(hypothesis.hypothesis_id)
        if existing and existing.model_dump() == hypothesis.model_dump():
            return existing
        self.write_counts[key] = self.write_counts.get(key, 0) + 1
        self.hypotheses[hypothesis.hypothesis_id] = hypothesis
        return hypothesis

    def link_evidence_to_hypothesis(
        self,
        hypothesis_id: str,
        *,
        supporting_event_ids: list[str],
        contradicting_event_ids: list[str],
    ) -> None:
        self._require()
        self.hypothesis_links[hypothesis_id] = {
            "supporting": sorted(set(supporting_event_ids)),
            "contradicting": sorted(set(contradicting_event_ids)),
        }

    def upsert_agent_run(self, run: AgentRun) -> None:
        self._require()
        self.agent_runs[run.run_id] = run

    def upsert_scenario(self, scenario: CascadeScenario) -> CascadeScenario:
        self._require()
        key = f"scn:{scenario.scenario_id}"
        existing = self.scenarios.get(scenario.scenario_id)
        if existing and existing.model_dump() == scenario.model_dump():
            return existing
        self.write_counts[key] = self.write_counts.get(key, 0) + 1
        self.scenarios[scenario.scenario_id] = scenario
        return scenario

    def get_cascade_paths(self, incident_id: str, max_depth: int) -> list[DependencyPath]:
        self._require()
        starts = self.incident_assets.get(incident_id, [])
        adjacency: dict[str, list[tuple[str, str]]] = {}
        for src, dst, rel in self.edges:
            adjacency.setdefault(src, []).append((dst, rel))
        paths: list[DependencyPath] = []
        for start in starts:
            stack: list[tuple[list[str], list[str]]] = [([start], [])]
            while stack:
                nodes, rels = stack.pop()
                if len(nodes) - 1 >= max_depth:
                    continue
                current = nodes[-1]
                for nxt, rel in adjacency.get(current, []):
                    if nxt in nodes:
                        continue
                    new_nodes = nodes + [nxt]
                    new_rels = rels + [rel]
                    paths.append(DependencyPath(asset_ids=new_nodes, relationships=new_rels))
                    stack.append((new_nodes, new_rels))
        return paths

    def get_incident_graph(self, incident_id: str) -> dict[str, Any]:
        self._require()
        return {
            "incident_id": incident_id,
            "assets": self.incident_assets.get(incident_id, []),
            "edges": self.edges,
            "events": sorted(self.incident_events.get(incident_id, set())),
        }

    def get_scenarios(self, incident_id: str) -> list[CascadeScenario]:
        self._require()
        return [s for s in self.scenarios.values() if s.incident_id == incident_id]
