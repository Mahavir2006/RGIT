"""Source adapters.

Each adapter converts one provider's payload into canonical events. Adapters never write to the
database; the ingestion runner persists what they return.
"""

from app.ingestion.base import AdapterResult, FetchRequest, SourceAdapter

__all__ = ["AdapterResult", "FetchRequest", "SourceAdapter"]
