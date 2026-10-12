from __future__ import annotations

from typing import Any

from urban_sentinel.core.config import Settings
from urban_sentinel.intelligence.exceptions import GraphUnavailableError
from urban_sentinel.intelligence.models import AgentRun, CascadeScenario, DependencyPath, Hypothesis
from urban_sentinel.repositories.graph import InMemoryGraphRepository


class Neo4jGraphRepository:
    """Thin adapter around the agreed Neo4j contract.

    Production Cypher lives with the graph team. This adapter either wraps a live
    driver when credentials exist or degrades without fabricating graph evidence.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        fallback: InMemoryGraphRepository | None = None,
        driver: Any | None = None,
    ) -> None:
        self.settings = settings
        self.fallback = fallback or InMemoryGraphRepository()
        self.driver = driver
        self.available = True
        if driver is None and settings.neo4j_uri and settings.neo4j_password:
            try:
                from neo4j import GraphDatabase

                self.driver = GraphDatabase.driver(
                    settings.neo4j_uri,
                    auth=(settings.neo4j_user, settings.neo4j_password),
                )
                self.driver.verify_connectivity()
            except Exception:  # noqa: BLE001
                self.available = False
                self.driver = None
        elif settings.neo4j_uri and not settings.neo4j_password:
            self.available = False

    def _require(self) -> None:
        if not self.available:
            raise GraphUnavailableError("Neo4j unavailable")

    def get_incident_evidence(self, incident_id: str) -> dict[str, Any]:
        self._require()
        if self.driver is None:
            return self.fallback.get_incident_evidence(incident_id)
        query = """
        MATCH (i:Incident {id: $incident_id})-[:EVIDENCED_BY]->(e:Event)
        RETURN collect(e.id) AS event_ids
        """
        with self.driver.session(database=self.settings.neo4j_database) as session:
            record = session.run(query, incident_id=incident_id).single()
            return {"incident_id": incident_id, "event_ids": record["event_ids"] if record else []}

    def get_incident_hypotheses(self, incident_id: str) -> list[Hypothesis]:
        self._require()
        return self.fallback.get_incident_hypotheses(incident_id)

    def link_event_to_incident(
        self, event_id: str, incident_id: str, *, decision: str, run_id: str
    ) -> None:
        self._require()
        self.fallback.link_event_to_incident(
            event_id, incident_id, decision=decision, run_id=run_id
        )

    def upsert_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis:
        self._require()
        return self.fallback.upsert_hypothesis(hypothesis)

    def link_evidence_to_hypothesis(
        self,
        hypothesis_id: str,
        *,
        supporting_event_ids: list[str],
        contradicting_event_ids: list[str],
    ) -> None:
        self._require()
        self.fallback.link_evidence_to_hypothesis(
            hypothesis_id,
            supporting_event_ids=supporting_event_ids,
            contradicting_event_ids=contradicting_event_ids,
        )

    def upsert_agent_run(self, run: AgentRun) -> None:
        self._require()
        self.fallback.upsert_agent_run(run)

    def upsert_scenario(self, scenario: CascadeScenario) -> CascadeScenario:
        self._require()
        return self.fallback.upsert_scenario(scenario)

    def get_cascade_paths(self, incident_id: str, max_depth: int) -> list[DependencyPath]:
        self._require()
        return self.fallback.get_cascade_paths(incident_id, max_depth)

    def get_incident_graph(self, incident_id: str) -> dict[str, Any]:
        self._require()
        return self.fallback.get_incident_graph(incident_id)

    def get_scenarios(self, incident_id: str) -> list[CascadeScenario]:
        self._require()
        return self.fallback.get_scenarios(incident_id)
