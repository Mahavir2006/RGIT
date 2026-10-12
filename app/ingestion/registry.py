"""Source adapter registry.

Source ids are namespaced ``<category>.<mode>`` so that a category filter is a prefix match and
a live and a replay instance of the same provider never collide.
"""

from __future__ import annotations

from app.core.errors import NotFoundError
from app.ingestion.base import SourceAdapter

__all__ = ["SourceRegistry", "registry"]


class SourceRegistry:
    """Holds every configured adapter and resolves them by id or category."""

    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        if not adapter.source_id:
            raise ValueError(f"adapter {type(adapter).__name__} has no source_id")
        self._adapters[adapter.source_id] = adapter

    def get(self, source_id: str) -> SourceAdapter:
        adapter = self._adapters.get(source_id)
        if adapter is None:
            raise NotFoundError(
                f"Unknown source '{source_id}'.",
                details={
                    "source_id": source_id,
                    "available": sorted(self._adapters.keys()),
                },
            )
        return adapter

    def resolve(self, name: str) -> SourceAdapter:
        """Resolve an exact source id, an id prefix, or a category name to one adapter.

        ``replay`` -> ``replay.all``, ``weather`` -> ``weather.live``, ``air_quality`` ->
        ``airquality.live``. An alias that matches more than one adapter is rejected rather than
        guessed, so adding a second adapter to a category can never silently redirect a trigger.
        """
        if name in self._adapters:
            return self._adapters[name]
        key = name.strip().lower().replace("-", "_")
        matches = {
            a.source_id: a
            for a in self._adapters.values()
            if a.source_id.split(".", 1)[0] == key.replace("_", "") or a.category.value == key
        }
        if len(matches) == 1:
            return next(iter(matches.values()))
        if len(matches) > 1:
            raise NotFoundError(
                f"Source alias '{name}' is ambiguous; use a full source id.",
                details={"source_id": name, "candidates": sorted(matches)},
            )
        return self.get(name)

    def has(self, source_id: str) -> bool:
        return source_id in self._adapters

    def all(self) -> list[SourceAdapter]:
        return list(self._adapters.values())

    def ids(self) -> list[str]:
        return sorted(self._adapters.keys())

    def by_category(self, category: str) -> list[SourceAdapter]:
        return [a for a in self._adapters.values() if a.category.value == category]


registry = SourceRegistry()
