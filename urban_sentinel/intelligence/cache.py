from __future__ import annotations

import hashlib
import json
import time
from typing import Any


class AnalysisCache:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self.ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}

    @staticmethod
    def fingerprint(
        *,
        incident_id: str | None,
        event_ids: list[str],
        evidence_version: str,
        scope: list[str],
        schema_version: str,
    ) -> str:
        payload = {
            "incident_id": incident_id,
            "event_ids": sorted(event_ids),
            "evidence_version": evidence_version,
            "scope": sorted(scope),
            "schema_version": schema_version,
        }
        encoded = json.dumps(payload, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < time.time():
            self._store.pop(key, None)
            return None
        return value

    def put(self, key: str, value: dict[str, Any]) -> None:
        self._store[key] = (time.time() + self.ttl_seconds, value)

    def invalidate_prefix(self, prefix: str) -> None:
        for key in list(self._store):
            if key.startswith(prefix):
                self._store.pop(key, None)
