from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from urban_sentinel.core.config import Settings, get_settings
from urban_sentinel.core.logging import log_event
from urban_sentinel.domain.models import ProcessedWorkflowInput, ReviewDecision
from urban_sentinel.intelligence.cache import AnalysisCache
from urban_sentinel.intelligence.llm import LLMClient, build_llm
from urban_sentinel.intelligence.models import WorkflowStatus
from urban_sentinel.intelligence.runtime import IntelligenceRuntime
from urban_sentinel.intelligence.triggers import should_run_intelligence
from urban_sentinel.intelligence.workflow import IntelligenceWorkflow
from urban_sentinel.repositories.graph import GraphRepository, InMemoryGraphRepository
from urban_sentinel.repositories.neo4j_repo import Neo4jGraphRepository
from urban_sentinel.repositories.operational import OperationalRepository

logger = logging.getLogger("urban_sentinel.service")


class IntelligenceService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        operational: OperationalRepository | None = None,
        graph: GraphRepository | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.operational = operational or OperationalRepository(self.settings.report_store_path)
        if graph is not None:
            self.graph = graph
        elif self.settings.neo4j_uri:
            self.graph = Neo4jGraphRepository(self.settings)
        else:
            self.graph = InMemoryGraphRepository()
        self.llm = build_llm(self.settings, llm)
        self.runtime = IntelligenceRuntime(
            settings=self.settings,
            operational=self.operational,
            graph=self.graph,
            llm=self.llm,
            cache=AnalysisCache(self.settings.cache_ttl_seconds),
        )
        self.workflow = IntelligenceWorkflow(self.runtime)
        self._tasks: set[asyncio.Task] = set()

    def enqueue(self, payload: ProcessedWorkflowInput) -> str:
        workflow_id = str(uuid4())
        self.operational.create_workflow(workflow_id)
        if not should_run_intelligence(payload, self.settings):
            state = self.operational.get_workflow(workflow_id)
            if state is not None:
                state["status"] = WorkflowStatus.COMPLETED.value
                state["errors"] = ["Skipped: no material change, anomaly, or ambiguous association."]
                self.operational.save_workflow(state)
            return workflow_id
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self.run(payload, workflow_id), name=f"intel-{workflow_id}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        except RuntimeError:
            asyncio.run(self.run(payload, workflow_id))
        return workflow_id

    async def run(
        self, payload: ProcessedWorkflowInput, workflow_id: str | None = None
    ) -> dict:
        workflow_id = workflow_id or str(uuid4())
        if self.operational.get_workflow(workflow_id) is None:
            self.operational.create_workflow(workflow_id)
        log_event(logger, "workflow_start", workflow_id=workflow_id, incident_id=payload.incident_id)
        if payload.incident and not self.operational.get_incident(payload.incident.incident_id):
            self.operational.upsert_incident(payload.incident)
        if payload.incident_id and payload.assets:
            seed = getattr(self.graph, "seed_assets", None)
            if callable(seed):
                seed(payload.incident_id, [a.asset_id for a in payload.assets])
        if payload.dependencies:
            seed_edges = getattr(self.graph, "seed_edges", None)
            if callable(seed_edges):
                seed_edges(
                    [
                        (edge.from_asset_id, edge.to_asset_id, edge.relationship)
                        for edge in payload.dependencies
                    ]
                )
        result = await self.workflow.ainvoke(payload, workflow_id)
        return dict(result)

    def get_workflow(self, workflow_id: str) -> dict | None:
        state = self.operational.get_workflow(workflow_id)
        return dict(state) if state else None

    def record_review(
        self,
        *,
        incident_id: str,
        actor: str,
        decision: ReviewDecision,
        target_id: str | None,
        notes: str | None,
    ):
        return self.operational.record_review(
            incident_id=incident_id,
            actor=actor,
            decision=decision,
            target_id=target_id,
            notes=notes,
        )
