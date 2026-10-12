"""Water-level adapter — dataset ingestion (CSV / JSON) with an explicit column mapping.

There is **no invented live water endpoint**. No authorised water-level API was available in this
environment, so this adapter reads a file-backed dataset and says so plainly. If an authorised
API later becomes available, add it as a separate source id rather than silently switching
provenance.

Configuration
-------------
``WATER_DATASET_PATH``
    Path to the CSV or JSON file.
``WATER_MAPPING_PATH``
    Path to a JSON mapping document. Without one, the adapter uses the documented default column
    names below. The mapping is explicit and inspectable, because a silently mis-mapped column is
    indistinguishable from a real reading downstream.

Every record preserves station identity, observation time, unit, datum, and the configured alert
threshold. Sample values are labelled ``historical`` or ``synthetic`` — never presented as live
observations.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, UpstreamUnavailableError
from app.core.logging import get_logger
from app.core.timeutil import parse_timestamp, utc_now
from app.ingestion.base import AdapterOutcome, AdapterResult, FetchRequest, SourceAdapter
from app.schemas.common import (
    LocationPrecision,
    MeasurementAggregation,
    QualityFlag,
    SourceCategory,
    SourceKind,
)
from app.schemas.event import EventLocation, EventType, Measurement, build_canonical_event

__all__ = ["WaterDatasetAdapter", "RowError", "DEFAULT_MAPPING"]

logger = get_logger(__name__)

#: Documented default column mapping. Override with WATER_MAPPING_PATH.
DEFAULT_MAPPING: dict[str, Any] = {
    "station_id": "station_id",
    "station_name": "station_name",
    "observed_at": "observed_at",
    "water_level": "water_level",
    "unit": "unit",
    "latitude": "latitude",
    "longitude": "longitude",
    "datum": "datum",
    "alert_threshold": "alert_threshold",
    "threshold_unit": "threshold_unit",
    "reporting_interval_seconds": "reporting_interval_seconds",
    # Which provenance to stamp on records read from a file.
    "source_kind": "historical",
}


class RowError(ValueError):
    """A dataset row that cannot be mapped, carrying a stable reason code.

    Distinguishing "a required field was absent" from "a value was unusable" matters: the first is
    usually a dataset/connector problem, the second is usually a bad sensor reading.
    """

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class WaterDatasetAdapter(SourceAdapter):
    """Water-level readings from a configured CSV/JSON dataset."""

    source_id = "water.dataset"
    display_name = "Water level dataset (file)"
    category = SourceCategory.WATER
    provider = "dataset"
    supports_live = False
    supports_replay = True
    unit_notes = (
        "Water level normalised to metres. The dataset's own unit and datum are retained, and "
        "the configured alert threshold is recorded with its own unit rather than assumed."
    )
    caveats = (
        "No live water-level endpoint is implemented or claimed; this adapter reads a file.",
        "Fixture values are labelled historical/synthetic and must not be read as live readings.",
        "A missing threshold is recorded as absent, never defaulted to a safe value.",
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def required_settings(self) -> list[str]:
        return []  # falls back to the bundled sample dataset

    def dataset_path(self) -> Path:
        """Resolve the dataset path, falling back to the bundled sample."""
        configured = self.settings.water_dataset_path
        if configured:
            return Path(configured)
        return Path(self.settings.replay_fixtures_dir) / "water_levels.csv"

    def mapping(self) -> dict[str, Any]:
        """Load the column mapping, falling back to the documented defaults."""
        mapping_path = self.settings.water_mapping_path
        if mapping_path:
            file_path = Path(mapping_path)
            if not file_path.exists():
                raise UpstreamUnavailableError(
                    f"WATER_MAPPING_PATH points at a file that does not exist: {file_path.name}.",
                    details={"missing_settings": ["WATER_MAPPING_PATH"]},
                )
            try:
                loaded = json.loads(file_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise UpstreamUnavailableError(
                    f"Water mapping file is not valid JSON (line {exc.lineno}).",
                    details={"provider": self.provider},
                ) from exc
            if not isinstance(loaded, dict):
                raise UpstreamUnavailableError(
                    "Water mapping file must contain a JSON object.",
                    details={"provider": self.provider},
                )
            return {**DEFAULT_MAPPING, **loaded}
        return dict(DEFAULT_MAPPING)

    async def fetch_events(self, request: FetchRequest) -> AdapterResult:
        started = utc_now()
        outcome = AdapterOutcome()

        path = self.dataset_path()
        if not path.exists():
            raise NotFoundError(
                f"Water dataset not found: {path.name}. "
                f"Set WATER_DATASET_PATH to an existing CSV or JSON file.",
                details={"provider": self.provider, "setting": "WATER_DATASET_PATH"},
            )

        mapping = self.mapping()
        rows = self._read_rows(path)
        outcome.pages_fetched = 1
        outcome.provider_meta = {
            "dataset": path.name,
            "row_count": len(rows),
            "mapping": "explicit" if self.settings.water_mapping_path else "default",
        }

        if not rows:
            outcome.warnings.append(
                f"Water dataset '{path.name}' contains no rows. "
                "This is a missing signal, not a statement that water levels are normal."
            )
            return AdapterResult.from_outcome(self.source_id, outcome, started)

        for line_no, row in enumerate(rows, start=1):
            try:
                event = self._parse_row(row, mapping, line_no)
            except RowError as exc:
                outcome.reject(
                    reason_code=exc.reason_code,
                    message=str(exc),
                    outcome="quarantined",
                )
                continue
            if event is None:
                continue
            outcome.accept(event)

        return AdapterResult.from_outcome(self.source_id, outcome, started)

    # -------------------------------------------------------------- reading
    def _read_rows(self, path: Path) -> list[dict[str, Any]]:
        """Read a dataset file into dictionaries, supporting CSV and JSON."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise UpstreamUnavailableError(
                f"Could not read water dataset '{path.name}': {exc.strerror}.",
                details={"provider": self.provider},
            ) from exc

        suffix = path.suffix.lower()
        if suffix == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise UpstreamUnavailableError(
                    f"Water dataset '{path.name}' is not valid JSON (line {exc.lineno}).",
                    details={"provider": self.provider},
                ) from exc
            if isinstance(data, list):
                return [r for r in data if isinstance(r, dict)]
            if isinstance(data, dict):
                for key in ("records", "data", "observations", "results"):
                    value = data.get(key)
                    if isinstance(value, list):
                        return [r for r in value if isinstance(r, dict)]
            raise UpstreamUnavailableError(
                f"Water dataset '{path.name}' must be a list of objects, or an object "
                f"containing one under 'records', 'data', 'observations', or 'results'.",
                details={"provider": self.provider},
            )

        if suffix in (".csv", ".txt", ""):
            reader = csv.DictReader(text.splitlines())
            if reader.fieldnames is None:
                return []
            return [dict(row) for row in reader]

        raise UpstreamUnavailableError(
            f"Unsupported water dataset format '{suffix or 'none'}'. Use .csv or .json.",
            details={"provider": self.provider},
        )

    # -------------------------------------------------------------- parsing
    def _parse_row(
        self, row: dict[str, Any], mapping: dict[str, Any], line_no: int
    ) -> Any:
        """Map one dataset row onto a canonical water-level event.

        Raises:
            RowError: when the row cannot be mapped, so the caller can quarantine it with a
                specific reason rather than dropping it silently.
        """
        def field(name: str) -> Any:
            column = mapping.get(name, name)
            value = row.get(column)
            if isinstance(value, str):
                value = value.strip()
            return value if value not in ("", None) else None

        station_id = field("station_id")
        observed_raw = field("observed_at")
        level_raw = field("water_level")
        unit = field("unit")

        # Absent required fields are a dataset-mapping problem, not a bad reading.
        for name, value in (
            ("station_id", station_id),
            ("observed_at", observed_raw),
            ("water_level", level_raw),
            ("unit", unit),
        ):
            if not value:
                raise RowError(
                    "missing_required_field",
                    f"row {line_no}: missing required field '{name}'",
                )

        try:
            observed_at = parse_timestamp(observed_raw)
        except ValueError as exc:
            raise RowError(
                "invalid_timestamp", f"row {line_no}: invalid observed_at ({exc})"
            ) from exc

        try:
            level_value = float(level_raw)
        except (TypeError, ValueError) as exc:
            raise RowError(
                "invalid_measurement_value",
                f"row {line_no}: water_level is not a number ({level_raw!r})",
            ) from exc
        if level_value != level_value or level_value in (float("inf"), float("-inf")):
            raise RowError(
                "invalid_measurement_value",
                f"row {line_no}: water_level is not a finite number",
            )

        location = self._parse_location(row, mapping, station_id)

        # Reporting interval determines whether the reading is a point value or an average.
        interval_seconds = _as_int(field("reporting_interval_seconds"))
        aggregation = (
            MeasurementAggregation.AVERAGE if interval_seconds else MeasurementAggregation.INSTANTANEOUS
        )

        reading = Measurement.build(
            "water_level",
            level_value,
            unit,
            aggregation=aggregation,
            period_seconds=interval_seconds,
        )
        if reading is None:  # pragma: no cover - guarded above
            raise ValueError(f"row {line_no}: water_level could not be normalised")

        measurements = [reading]

        # The configured alert threshold travels with the record, in its own unit.
        threshold_raw = field("alert_threshold")
        threshold_unit = field("threshold_unit") or unit
        flags: list[QualityFlag] = []
        if threshold_raw is None:
            # An absent threshold is recorded as absent; it is not defaulted.
            flags.append(QualityFlag.OPTIONAL_MEASUREMENT_ABSENT)
        else:
            try:
                threshold_value = float(threshold_raw)
                threshold = Measurement.build(
                    "water_level_threshold",
                    threshold_value,
                    threshold_unit,
                    aggregation=MeasurementAggregation.INSTANTANEOUS,
                )
                if threshold:
                    measurements.append(threshold)
            except ValueError:
                flags.append(QualityFlag.PROVIDER_PARTIAL_PAYLOAD)

        if location is None:
            flags.append(QualityFlag.LOCATION_MISSING)

        source_kind = _as_source_kind(mapping.get("source_kind", "historical"))

        return build_canonical_event(
            source_id=self.source_id,
            source_event_id=f"{station_id}:{observed_at.isoformat()}",
            event_type=EventType.WATER_LEVEL_OBSERVED,
            event_time=observed_at,
            ingest_time=utc_now(),
            location=location,
            measurements=measurements,
            source_kind=source_kind,
            quality_flags=flags,
            payload={
                "provider": self.provider,
                "dataset": mapping.get("__dataset__", "water"),
                "station_id": station_id,
                "station_name": field("station_name"),
                "datum": field("datum"),
                "reporting_interval_seconds": interval_seconds,
                "threshold_present": threshold_raw is not None,
                "row_number": line_no,
            },
        )

    @staticmethod
    def _parse_location(
        row: dict[str, Any], mapping: dict[str, Any], station_id: str
    ) -> EventLocation | None:
        lat = _as_float(row.get(mapping.get("latitude", "latitude")))
        lon = _as_float(row.get(mapping.get("longitude", "longitude")))
        if lat is None or lon is None:
            # No coordinates: identify the station by reference rather than inventing a pin.
            return EventLocation(precision=LocationPrecision.UNKNOWN, place_id=str(station_id))
        return EventLocation(
            latitude=lat,
            longitude=lon,
            precision=LocationPrecision.PRECISE,
            place_id=str(station_id),
        )


def _as_source_kind(value: Any) -> SourceKind:
    try:
        return SourceKind(str(value).strip().lower())
    except ValueError:
        # An unrecognised provenance label must not be silently promoted to "live".
        return SourceKind.HISTORICAL


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
