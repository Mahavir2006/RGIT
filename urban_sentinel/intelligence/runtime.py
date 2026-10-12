from __future__ import annotations

from dataclasses import dataclass

from urban_sentinel.core.config import Settings
from urban_sentinel.intelligence.cache import AnalysisCache
from urban_sentinel.intelligence.llm import LLMClient
from urban_sentinel.repositories.graph import GraphRepository
from urban_sentinel.repositories.operational import OperationalRepository


@dataclass
class IntelligenceRuntime:
    settings: Settings
    operational: OperationalRepository
    graph: GraphRepository
    llm: LLMClient
    cache: AnalysisCache
