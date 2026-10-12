"""Validated, versioned configuration for the deterministic processing engine.

Every threshold, window, and weight lives here, not scattered through the algorithms. The
defaults are **illustrative demonstration values** chosen to make the bundled Mumbai monsoon
fixtures behave sensibly. None of them is a calibrated or regulatory threshold; each one needs
sign-off from a domain owner before operational use (see README, "Processing configuration").

The configuration is hashed into ``processing_version``. Two runs with the same events, the same
history, and the same ``processing_version`` must make the same material decisions.

Override the defaults with a JSON file named by ``PROCESSING_CONFIG_PATH``; the file is merged
over the defaults and re-validated.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "ENGINE_VERSION",
    "ProcessingConfig",
    "ThresholdRule",
    "RateRule",
    "BaselineRule",
    "get_processing_config",
    "load_processing_config",
]

#: Bump when algorithm *code* changes in a way that alters decisions.
ENGINE_VERSION = "1.0"

Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]


class Band(BaseModel):
    """``value`` is the boundary at which ``severity`` starts to apply."""

    value: float
    severity: Severity


class ThresholdRule(BaseModel):
    rule_id: str
    version: str = "1"
    measurement: str
    unit: str
    direction: Literal["above", "below"] = "above"
    bands: list[Band]
    event_types: list[str] = Field(default_factory=list)
    #: Optional measurement on the same event that carries a per-station threshold
    #: (e.g. ``water_level_threshold``). When present it overrides the lowest band boundary.
    event_threshold_measurement: str | None = None
    #: Required observation period, so a 24 h total is never compared with a 1 h threshold.
    period_seconds: int | None = None
    source: str = "demonstration assumption - requires domain calibration"

    @model_validator(mode="after")
    def _ordered(self) -> "ThresholdRule":
        values = [b.value for b in self.bands]
        expected = sorted(values) if self.direction == "above" else sorted(values, reverse=True)
        if values != expected or not values:
            raise ValueError(f"rule {self.rule_id}: bands must be non-empty and monotonic")
        return self


class RateRule(BaseModel):
    rule_id: str
    version: str = "1"
    measurement: str
    unit: str
    direction: Literal["rise", "fall"] = "rise"
    #: Rate in ``unit`` per hour at which each severity starts to apply.
    bands: list[Band]
    #: Physically implausible rate (sensor-health, not environmental) in ``unit`` per hour.
    implausible_rate_per_hour: float | None = None
    min_interval_seconds: int = 60
    max_interval_seconds: int = 3 * 3600
    source: str = "demonstration assumption - requires domain calibration"


class BaselineRule(BaseModel):
    rule_id: str
    version: str = "1"
    measurement: str
    unit: str
    window_hours: int = 72
    min_samples: int = 12
    #: |robust z| at which each severity starts to apply.
    bands: list[Band] = Field(
        default_factory=lambda: [Band(value=3.5, severity="MEDIUM"), Band(value=6.0, severity="HIGH")]
    )


class SensorHealthConfig(BaseModel):
    flatline_min_readings: int = 6
    flatline_min_span_seconds: int = 3600
    conflict_radius_m: float = 1500.0
    conflict_window_seconds: int = 1800
    #: Relative disagreement between neighbouring sensors that is worth an operator's attention.
    conflict_relative_difference: float = 0.6
    conflict_measurements: list[str] = Field(default_factory=lambda: ["water_level", "rainfall_1h"])
    malformed_window_seconds: int = 3600
    malformed_min_count: int = 3


class ValidationPolicy(BaseModel):
    future_tolerance_seconds: int = 300
    #: Older than this (event_time vs processing time) -> warning STALE_OBSERVATION.
    stale_after_seconds: int = 6 * 3600
    #: Older than this -> quarantined (likely clock or replay error).
    max_age_seconds: int = 30 * 24 * 3600
    #: Arrival delay that makes an event "late" (a warning, never a rejection).
    late_after_seconds: int = 600
    supported_schema_versions: list[str] = Field(default_factory=lambda: ["1.0"])
    #: Event-type families that must carry coordinates or an area reference.
    location_required_prefixes: list[str] = Field(
        default_factory=lambda: ["water_level", "traffic", "air_quality", "rainfall"]
    )


class DedupConfig(BaseModel):
    version: str = "1"
    #: Time precision (seconds) of the fallback fingerprint, per source category prefix.
    time_precision_seconds: dict[str, int] = Field(
        default_factory=lambda: {"default": 60, "citizen": 1, "traffic": 60, "weather": 60}
    )
    coordinate_decimals: int = 5  # ~1.1 m: avoids merging distinct nearby events
    #: Near-duplicate window for "possibly the same report/reading, needs review".
    near_window_seconds: int = 300
    near_radius_m: float = 50.0


class CandidateConfig(BaseModel):
    version: str = "1"
    time_window_seconds: int = 3 * 3600
    search_radius_m: float = 2000.0
    #: Beyond radius * this factor, a candidate is hard-rejected as geographically unrelated.
    hard_reject_radius_factor: float = 3.0
    approximate_location_factor: float = 0.8
    area_match_spatial_score: float = 0.5
    weights: dict[str, float] = Field(
        default_factory=lambda: {"T": 0.30, "G": 0.30, "K": 0.20, "A": 0.10, "Q": 0.10}
    )
    match_threshold: float = 0.65
    review_threshold: float = 0.45
    ambiguity_margin: float = 0.08
    max_candidates: int = 50
    source_reliability: dict[str, float] = Field(
        default_factory=lambda: {"live_api": 1.0, "historical": 0.9, "synthetic": 1.0, "manual": 0.6}
    )
    #: Symmetric event-family compatibility. Missing pairs are 0 (incompatible).
    compatibility: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "hydro": {"hydro": 1.0, "rain": 0.8, "traffic": 0.6, "report_flood": 1.0},
            "rain": {"rain": 1.0, "hydro": 0.8, "traffic": 0.4, "report_flood": 0.8},
            "traffic": {"traffic": 1.0, "hydro": 0.6, "rain": 0.4, "report_flood": 0.6,
                        "report_road": 1.0},
            "air": {"air": 1.0, "report_air": 1.0},
            "report_flood": {"report_flood": 1.0, "hydro": 1.0, "rain": 0.8, "traffic": 0.6},
            "report_road": {"report_road": 1.0, "traffic": 1.0},
            "report_air": {"report_air": 1.0, "air": 1.0},
            "report_power": {"report_power": 1.0},
            "report_health": {"report_health": 1.0, "air": 0.5},
        }
    )

    @model_validator(mode="after")
    def _check(self) -> "CandidateConfig":
        if set(self.weights) != {"T", "G", "K", "A", "Q"}:
            raise ValueError("weights must define exactly T, G, K, A, Q")
        if any(w < 0 for w in self.weights.values()) or sum(self.weights.values()) <= 0:
            raise ValueError("weights must be non-negative with a positive sum")
        if not 0 <= self.review_threshold <= self.match_threshold <= 1:
            raise ValueError("require 0 <= review_threshold <= match_threshold <= 1")
        return self


class ProcessingConfig(BaseModel):
    validation: ValidationPolicy = Field(default_factory=ValidationPolicy)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    thresholds: list[ThresholdRule] = Field(default_factory=lambda: _default_thresholds())
    rates: list[RateRule] = Field(default_factory=lambda: _default_rates())
    baselines: list[BaselineRule] = Field(default_factory=lambda: _default_baselines())
    sensor_health: SensorHealthConfig = Field(default_factory=SensorHealthConfig)
    candidates: CandidateConfig = Field(default_factory=CandidateConfig)
    batch_max: int = Field(default=500, ge=1, le=5000)
    concurrency: int = Field(default=4, ge=1, le=32)

    def config_hash(self) -> str:
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    @property
    def processing_version(self) -> str:
        return f"proc-{ENGINE_VERSION}+{self.config_hash()}"


def _b(*pairs: tuple[float, str]) -> list[Band]:
    return [Band(value=v, severity=s) for v, s in pairs]  # type: ignore[arg-type]


def _default_thresholds() -> list[ThresholdRule]:
    return [
        ThresholdRule(
            rule_id="rainfall_1h_high", measurement="rainfall_1h", unit="mm", period_seconds=3600,
            bands=_b((7.5, "LOW"), (15.0, "MEDIUM"), (30.0, "HIGH"), (60.0, "CRITICAL")),
            source="Illustrative, loosely after IMD hourly-intensity categories; not calibrated",
        ),
        ThresholdRule(
            rule_id="water_level_high", measurement="water_level", unit="m",
            event_threshold_measurement="water_level_threshold",
            bands=_b((0.75, "MEDIUM"), (1.0, "HIGH"), (1.5, "CRITICAL")),
            source="Per-gauge threshold from the dataset when present; else demonstration values",
        ),
        ThresholdRule(
            rule_id="traffic_speed_ratio_low", measurement="speed_ratio", unit="ratio",
            direction="below",
            bands=_b((0.5, "LOW"), (0.35, "MEDIUM"), (0.2, "HIGH"), (0.1, "CRITICAL")),
        ),
        ThresholdRule(
            rule_id="pm25_1h_high", measurement="pm25_concentration", unit="ug/m3",
            period_seconds=3600,
            bands=_b((60.0, "LOW"), (90.0, "MEDIUM"), (120.0, "HIGH"), (250.0, "CRITICAL")),
            source="Illustrative bands loosely after India NAQI PM2.5 breakpoints (24 h basis); "
                   "applied to 1 h averages for demo only",
        ),
    ]


def _default_rates() -> list[RateRule]:
    return [
        RateRule(
            rule_id="water_level_rapid_rise", measurement="water_level", unit="m",
            bands=_b((0.3, "MEDIUM"), (0.6, "HIGH"), (1.2, "CRITICAL")),
            implausible_rate_per_hour=5.0,
        ),
        RateRule(
            rule_id="traffic_speed_drop", measurement="speed", unit="km/h", direction="fall",
            bands=_b((20.0, "LOW"), (40.0, "MEDIUM"), (80.0, "HIGH")),
            implausible_rate_per_hour=400.0,
        ),
        RateRule(
            rule_id="pm25_abrupt_rise", measurement="pm25_concentration", unit="ug/m3",
            bands=_b((30.0, "LOW"), (60.0, "MEDIUM")),
            implausible_rate_per_hour=1000.0,
        ),
    ]


def _default_baselines() -> list[BaselineRule]:
    return [
        BaselineRule(rule_id="water_level_baseline", measurement="water_level", unit="m"),
        BaselineRule(rule_id="pm25_baseline", measurement="pm25_concentration", unit="ug/m3"),
        BaselineRule(rule_id="speed_baseline", measurement="speed", unit="km/h"),
    ]


def load_processing_config(path: str | None) -> ProcessingConfig:
    if not path:
        return ProcessingConfig()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    merged = ProcessingConfig().model_dump(mode="json")
    merged.update(data)
    return ProcessingConfig.model_validate(merged)


@lru_cache(maxsize=1)
def get_processing_config() -> ProcessingConfig:
    from app.core.config import get_settings

    return load_processing_config(get_settings().processing_config_path)
