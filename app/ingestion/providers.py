"""Adapter registration.

Called once at application startup. Source ids are namespaced ``<category>.<mode>`` so a live and
a replay instance of the same provider never collide, and a category filter is a prefix match.
"""

from __future__ import annotations

from app.ingestion.citizen import CitizenReportAdapter
from app.ingestion.crowd import CrowdDensityAdapter
from app.ingestion.openweather import OpenWeatherAdapter
from app.ingestion.openaq import OpenAQAdapter
from app.ingestion.registry import SourceRegistry, registry
from app.ingestion.replay import ReplayAdapter
from app.ingestion.traffic import TrafficAdapter
from app.ingestion.water import WaterDatasetAdapter

__all__ = ["registry", "build_default_registry", "register_defaults"]

_ADAPTER_CLASSES = (
    OpenWeatherAdapter,
    OpenAQAdapter,
    TrafficAdapter,
    WaterDatasetAdapter,
    CitizenReportAdapter,
    ReplayAdapter,
    CrowdDensityAdapter,
)


def build_default_registry() -> SourceRegistry:
    """Construct a registry populated with every built-in adapter."""
    built = SourceRegistry()
    for adapter_cls in _ADAPTER_CLASSES:
        built.register(adapter_cls())
    return built


def register_defaults(target: SourceRegistry | None = None) -> SourceRegistry:
    """Populate the process-wide registry, replacing any previous contents."""
    global registry
    built = build_default_registry()
    if target is not None:
        target._adapters.update(built._adapters)  # noqa: SLF001 - deliberate registry merge
        return target
    for adapter in built.all():
        registry.register(adapter)
    return registry
