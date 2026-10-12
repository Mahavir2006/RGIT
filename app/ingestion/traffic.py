"""Traffic adapter — TomTom Traffic Flow API.

Provider shape
--------------
TomTom ``/traffic/services/flow/segment`` reports, per road segment, a ``currentSpeed`` in km/h
and a ``freeFlowSpeed`` in km/h.

The current-speed / free-flow-speed ratio
-----------------------------------------
This ratio is only meaningful when *both* values are present and positive. When
``freeFlowSpeed`` is absent the ratio is **not** computed — it is not filled with a default, and
a traffic-flow percentage is not invented. The event is emitted with the speed alone and a
``provider_partial_payload`` flag so the gap is visible downstream.

No credentials, no live traffic
-------------------------------
If ``TOMTOM_API_KEY`` is absent this adapter refuses to fabricate data. It reports the missing
variable by name and the runner falls back to replay. See ``app/ingestion/replay.py``.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.core.config import Settings, get_settings
from app.core.errors import CredentialMissingError, ValidationError
from app.core.logging import get_logger
from app.core.timeutil import parse_timestamp, utc_now
from app.ingestion.base import AdapterOutcome, AdapterResult, FetchRequest, SourceAdapter
from app.ingestion.http import ProviderClient, require_credential
from app.schemas.common import (
    LocationPrecision,
    MeasurementAggregation,
    QualityFlag,
    SourceCategory,
    SourceKind,
)
from app.schemas.event import EventLocation, EventType, Measurement, build_canonical_event

__all__ = ["TrafficAdapter"]

logger = get_logger(__name__)

# Below this ratio a segment is described as congested rather than merely slow. This is a
# presentation threshold, not a causal claim, and it is configurable per deployment.
CONGESTED_RATIO_THRESHOLD = 0.5


class TrafficAdapter(SourceAdapter):
    """TomTom traffic flow for configured road segments."""

    source_id = "traffic.live"
    display_name = "TomTom Traffic Flow (live)"
    category = SourceCategory.TRAFFIC
    provider = "tomtom"
    supports_live = True
    supports_replay = True
    documentation_url = "https://developer.tomtom.com/products/traffic-flow-api/documentation"
    unit_notes = (
        "Speed normalised to km/h. current/free-flow ratio is a dimensionless fraction in [0,1] "
        "and is emitted only when both speeds are present and positive."
    )
    caveats = (
        "Requires TOMTOM_API_KEY plus at least one TRAFFIC_SEGMENT_ID; no traffic is fabricated "
        "without them.",
        "Road-segment geometry is preserved by reference, not re-derived.",
        "Live mode is unverified in this environment: no credential was available to test against.",
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def required_settings(self) -> list[str]:
        return ["tomtom_api_key", "traffic_segment_ids"]

    async def fetch_events(self, request: FetchRequest) -> AdapterResult:
        started = utc_now()
        outcome = AdapterOutcome()

        api_key = require_credential(self.settings.tomtom_api_key, "TOMTOM_API_KEY", self.provider)
        segments = self.settings.traffic_segment_ids
        if not segments:
            raise CredentialMissingError(
                "TomTom live mode requires at least one TRAFFIC_SEGMENT_ID, which is not set. "
                "No traffic data is fabricated; use replay mode instead.",
                details={"missing_settings": ["TRAFFIC_SEGMENT_IDS"]},
            )

        client = ProviderClient(self.provider, settings=self.settings)
        try:
            # TomTom accepts a comma-separated segmentId list, so one request covers every
            # configured segment instead of one round trip per segment.
            payload = await client.get_json(
                f"{self.settings.tomtom_base_url}/traffic/services/flow/segment",
                params={
                    "segmentId": ",".join(segments),
                    "fields": "segmentId,currentSpeed,freeFlowSpeed,confidence",
                },
                headers={"tomtom-apikey": api_key},
            )
            outcome.pages_fetched = 1
            self._parse_segments(segments, payload, outcome)
        finally:
            await client.aclose()

        if not outcome.events:
            outcome.warnings.append(
                "TomTom returned no traffic flow segments. No data is not evidence of free flow."
            )

        return AdapterResult.from_outcome(self.source_id, outcome, started)

    # ------------------------------------------------------------- parsing
    def _parse_segments(
        self, requested: list[str], payload: Any, outcome: AdapterOutcome
    ) -> None:
        """Parse a multi-segment flow response.

        Each returned entry is attributed to the segment id the provider reports, falling back to
        the requested id when the provider omits it.
        """
        if not isinstance(payload, dict):
            outcome.reject(
                reason_code="malformed_payload",
                message="TomTom response was not a JSON object.",
                source_event_id=",".join(requested),
                outcome="quarantined",
            )
            return

        segments = payload.get("segments")
        if not isinstance(segments, list) or not segments:
            outcome.reject(
                reason_code="missing_required_field",
                message=(
                    "TomTom returned no segment data for "
                    f"{len(requested)} requested segment(s)."
                ),
                source_event_id=",".join(requested),
                outcome="quarantined",
            )
            return

        fallback = requested[0] if len(requested) == 1 else None
        for item in segments:
            segment_id = (
                str(item.get("segmentId")) if isinstance(item, dict) and item.get("segmentId")
                else fallback or "unknown-segment"
            )
            self._parse_one_segment(segment_id, item, outcome)

    def _parse_one_segment(self, segment_id: str, item: Any, outcome: AdapterOutcome) -> None:
        if not isinstance(item, dict):
            outcome.reject(
                reason_code="malformed_payload",
                message=f"TomTom segment entry for '{segment_id}' was not an object.",
                source_event_id=segment_id,
                outcome="quarantined",
            )
            return

        current_speed = _as_float(item.get("currentSpeed"))
        free_flow_speed = _as_float(item.get("freeFlowSpeed"))

        if current_speed is None or current_speed < 0:
            # An absent or nonsensical speed is reported, never zero-filled.
            outcome.reject(
                reason_code="invalid_measurement_value",
                message=f"TomTom segment '{segment_id}' had no usable currentSpeed.",
                source_event_id=segment_id,
                outcome="quarantined",
            )
            return

        resolved_segment_id = str(item.get("segmentId") or segment_id)
        flags: list[QualityFlag] = []
        measurements: list[Measurement] = []

        speed = Measurement.build("speed", current_speed, "km/h")
        if speed:
            measurements.append(speed)

        # Ratio only when the denominator is genuinely available.
        if free_flow_speed is not None and free_flow_speed > 0:
            ratio = round(current_speed / free_flow_speed, 4)
            ratio_reading = Measurement.build("speed_ratio", ratio, "ratio")
            if ratio_reading:
                measurements.append(ratio_reading)
            free_flow = Measurement.build("free_flow_speed", free_flow_speed, "km/h")
            if free_flow:
                measurements.append(free_flow)
            event_type = (
                EventType.TRAFFIC_CONGESTION_OBSERVED
                if ratio < CONGESTED_RATIO_THRESHOLD
                else EventType.TRAFFIC_SPEED_OBSERVED
            )
        else:
            # Explicitly flagged: the ratio is unknown, not assumed to be 1.0.
            flags.append(QualityFlag.PROVIDER_PARTIAL_PAYLOAD)
            flags.append(QualityFlag.OPTIONAL_MEASUREMENT_ABSENT)
            event_type = EventType.TRAFFIC_SPEED_OBSERVED

        confidence = item.get("confidence")
        if isinstance(confidence, str) and confidence.lower() == "low":
            # TomTom's own confidence label is recorded as a flag: a low-confidence reading
            # should not silently inform downstream scoring without that being visible.
            flags.append(QualityFlag.PROVIDER_PARTIAL_PAYLOAD)

        location = self._parse_location(item)

        outcome.accept(
            build_canonical_event(
                source_id=self.source_id,
                source_event_id=f"tomtom-{resolved_segment_id}",
                event_type=event_type,
                event_time=self._parse_time(item),
                ingest_time=utc_now(),
                location=location,
                measurements=measurements,
                source_kind=SourceKind.LIVE_API,
                quality_flags=flags,
                payload={
                    "provider": self.provider,
                    "segment_id": resolved_segment_id,
                    "road_class": item.get("roadClass"),
                    "confidence": confidence,
                    "current_speed_kph": current_speed,
                    "free_flow_speed_kph": free_flow_speed,
                    "ratio_computed": free_flow_speed is not None and free_flow_speed > 0,
                },
            )
        )

    @staticmethod
    def _parse_location(item: dict[str, Any]) -> EventLocation | None:
        """Extract coordinates if the provider included them; otherwise segment reference only."""
        lat = _as_float(item.get("latitude"))
        lon = _as_float(item.get("longitude"))
        segment_id = item.get("segmentId")
        if lat is not None and lon is not None:
            return EventLocation(
                latitude=lat,
                longitude=lon,
                precision=LocationPrecision.PRECISE,
                place_id=str(segment_id) if segment_id else None,
            )
        if segment_id:
            # No coordinates: represent as a referenced segment rather than a fabricated pin.
            return EventLocation(precision=LocationPrecision.UNKNOWN,
                                 place_id=str(segment_id))
        return None

    @staticmethod
    def _parse_time(item: dict[str, Any]) -> Any:
        for key in ("timestamp", "eventTime"):
            if item.get(key):
                try:
                    return parse_timestamp(item[key])
                except ValueError:
                    continue
        # Flow API omits a timestamp for the current snapshot; receipt time is the observation.
        return utc_now()


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result
