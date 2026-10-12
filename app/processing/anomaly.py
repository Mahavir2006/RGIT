"""Stage C — rule-based anomaly detection.

Every rule is pure: ``(event, context, config) -> findings``. The service layer supplies the
bounded history (previous readings from the same subject) and nearby readings; this module never
touches the database.

Environmental anomalies (threshold, baseline, rate-of-change) are kept strictly separate from
sensor-health anomalies (flatline, implausible jump, stale source, neighbour conflict, repeated
malformed data, timestamp anomaly). An offline or flatlined sensor is an observability problem,
never proof of a physical emergency.

Units are never mixed: a rule fires only when the measurement's canonical unit equals the rule's
unit (and, where configured, its observation period matches).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.processing.baselines import robust_baseline
from app.processing.config import Band, ProcessingConfig, RateRule, ThresholdRule
from app.processing.correlation import haversine_m, subject_of
from app.schemas.anomaly import AnomalyFinding, AnomalyKind, AnomalyType
from app.schemas.event import CanonicalEvent, Measurement

__all__ = ["Reading", "AnomalyContext", "detect_anomalies", "detect_stale_source",
           "detect_repeated_malformed", "evaluated_rule_subjects"]


@dataclass(slots=True, frozen=True)
class Reading:
    """A previous reading of one measurement from the same subject."""

    event_id: str
    event_time: datetime
    value: float
    unit: str
    period_seconds: int | None = None
    was_anomalous: bool = False
    latitude: float | None = None
    longitude: float | None = None
    subject: str | None = None


@dataclass(slots=True)
class AnomalyContext:
    #: measurement name -> readings from the same subject, strictly before the event, newest last.
    history: dict[str, list[Reading]] = field(default_factory=dict)
    #: measurement name -> concurrent readings from *other* subjects nearby.
    neighbours: dict[str, list[Reading]] = field(default_factory=dict)


def _band(bands: list[Band], value: float, direction: str) -> Band | None:
    hit = None
    for b in bands:
        if (direction in ("above", "rise") and value >= b.value) or \
           (direction in ("below", "fall") and value <= b.value):
            hit = b
    return hit


def _measure(event: CanonicalEvent, name: str) -> Measurement | None:
    for m in event.measurements:
        if m.name == name:
            return m
    return None


def _threshold(event: CanonicalEvent, rule: ThresholdRule, subject: str) -> AnomalyFinding | None:
    m = _measure(event, rule.measurement)
    if m is None or m.unit != rule.unit:
        return None
    if rule.period_seconds and m.period_seconds and m.period_seconds != rule.period_seconds:
        return None
    bands = list(rule.bands)
    source_note = rule.source
    if rule.event_threshold_measurement:
        local = _measure(event, rule.event_threshold_measurement)
        if local is not None and local.unit == rule.unit:
            # The station's own configured threshold replaces the lowest band boundary.
            bands[0] = Band(value=local.value, severity=bands[0].severity)
            bands = [b for i, b in enumerate(bands) if i == 0 or b.value > local.value]
            source_note = f"station threshold {local.value:g} {local.unit} from the source dataset"
    band = _band(bands, m.value, rule.direction)
    if band is None:
        return None
    cmp = ">=" if rule.direction == "above" else "<="
    return AnomalyFinding(
        anomaly_type=AnomalyType.THRESHOLD_EXCEEDED, kind=AnomalyKind.ENVIRONMENTAL,
        severity=band.severity, rule_id=rule.rule_id, rule_version=rule.version,
        source_id=event.source_id, event_id=event.event_id, subject=subject,
        measurement=m.name, observed_value=m.value, unit=m.unit, threshold=band.value,
        method="threshold",
        expected_range={"direction": rule.direction, "bands": [b.model_dump() for b in bands]},
        explanation=f"{m.name} = {m.value:g} {m.unit} {cmp} {band.value:g} {m.unit} "
                    f"({band.severity} band of {rule.rule_id}; {source_note})",
    )


def _rate(event: CanonicalEvent, rule: RateRule, prev: list[Reading], subject: str
          ) -> list[AnomalyFinding]:
    m = _measure(event, rule.measurement)
    if m is None or m.unit != rule.unit or not prev:
        return []
    last = prev[-1]
    if last.unit != m.unit or (last.period_seconds or 0) != (m.period_seconds or 0):
        return []  # never compare incompatible units or observation periods
    dt = (event.event_time - last.event_time).total_seconds()
    if dt < rule.min_interval_seconds or dt > rule.max_interval_seconds:
        return []
    delta = m.value - last.value
    rate = delta / (dt / 3600.0)
    signed = rate if rule.direction == "rise" else -rate
    details = {"previous_value": last.value, "previous_event_id": last.event_id,
               "previous_time": last.event_time.isoformat(), "current_value": m.value,
               "elapsed_seconds": dt, "rate_per_hour": round(rate, 6), "unit": m.unit}
    if rule.implausible_rate_per_hour is not None and abs(rate) >= rule.implausible_rate_per_hour:
        return [AnomalyFinding(
            anomaly_type=AnomalyType.IMPLAUSIBLE_JUMP, kind=AnomalyKind.SENSOR_HEALTH,
            severity="MEDIUM", rule_id=f"{rule.rule_id}.implausible", rule_version=rule.version,
            source_id=event.source_id, event_id=event.event_id, subject=subject,
            measurement=m.name, observed_value=m.value, unit=m.unit,
            threshold=rule.implausible_rate_per_hour, score=abs(rate), method="rate_of_change",
            explanation=f"{m.name} changed {delta:+g} {m.unit} in {dt:.0f}s "
                        f"({rate:+.3g} {m.unit}/h), beyond the physically plausible "
                        f"{rule.implausible_rate_per_hour:g} {m.unit}/h; treated as a sensor fault",
            details=details)]
    band = _band(rule.bands, signed, "rise")
    if band is None:
        return []
    return [AnomalyFinding(
        anomaly_type=AnomalyType.RAPID_CHANGE, kind=AnomalyKind.ENVIRONMENTAL,
        severity=band.severity, rule_id=rule.rule_id, rule_version=rule.version,
        source_id=event.source_id, event_id=event.event_id, subject=subject, measurement=m.name,
        observed_value=m.value, unit=m.unit, threshold=band.value, score=round(signed, 6),
        method="rate_of_change",
        expected_range={"max_rate_per_hour": rule.bands[0].value, "direction": rule.direction},
        explanation=f"{m.name} {'rose' if delta > 0 else 'fell'} from {last.value:g} to "
                    f"{m.value:g} {m.unit} in {dt / 60:.0f} min ({abs(rate):.3g} {m.unit}/h >= "
                    f"{band.value:g} {m.unit}/h, {band.severity})",
        details=details)]


def detect_anomalies(
    event: CanonicalEvent, ctx: AnomalyContext, cfg: ProcessingConfig
) -> list[AnomalyFinding]:
    """Run every configured rule against one event. Deterministic for a given context."""
    subject = subject_of(event)
    findings: list[AnomalyFinding] = []

    for rule in cfg.thresholds:
        if rule.event_types and event.event_type.value not in rule.event_types:
            continue
        f = _threshold(event, rule, subject)
        if f:
            findings.append(f)

    for rule in cfg.rates:
        findings.extend(_rate(event, rule, ctx.history.get(rule.measurement, []), subject))

    for rule in cfg.baselines:
        m = _measure(event, rule.measurement)
        if m is None or m.unit != rule.unit:
            continue
        window_start = event.event_time.timestamp() - rule.window_hours * 3600
        hist = [(r.value, r.was_anomalous) for r in ctx.history.get(rule.measurement, [])
                if r.unit == m.unit and r.event_time.timestamp() >= window_start]
        stats = robust_baseline(m.value, hist, min_samples=rule.min_samples)
        if not stats.usable:
            continue  # insufficient history / zero MAD: no z-score is presented as reliable
        band = _band(rule.bands, abs(stats.robust_z or 0.0), "above")
        if band is None:
            continue
        findings.append(AnomalyFinding(
            anomaly_type=AnomalyType.BASELINE_DEVIATION, kind=AnomalyKind.ENVIRONMENTAL,
            severity=band.severity, rule_id=rule.rule_id, rule_version=rule.version,
            source_id=event.source_id, event_id=event.event_id, subject=subject,
            measurement=m.name, observed_value=m.value, unit=m.unit, threshold=band.value,
            score=round(stats.robust_z, 4), method="robust_z", sample_count=stats.sample_count,  # type: ignore[arg-type]
            baseline_window_hours=rule.window_hours,
            expected_range={"median": stats.median, "mad": stats.mad,
                            "excluded_anomalous_samples": stats.excluded},
            explanation=f"{m.name} = {m.value:g} {m.unit}; robust z = {stats.robust_z:+.2f} vs "
                        f"median {stats.median:g} (MAD {stats.mad:g}, n={stats.sample_count}, "
                        f"{rule.window_hours} h window) |z| >= {band.value:g}",
        ))

    findings.extend(_crowd_spike(event, ctx, subject))
    findings.extend(_sensor_health(event, ctx, cfg, subject))
    return findings


def _crowd_spike(event: CanonicalEvent, ctx: AnomalyContext, subject: str) -> list[AnomalyFinding]:
    """Detect crowd count spikes where current reading is > 2x rolling average."""
    findings: list[AnomalyFinding] = []
    for m in event.measurements:
        if m.name in ("head_count", "crowd_count"):
            prev = [r for r in ctx.history.get(m.name, []) if r.unit == m.unit]
            if len(prev) >= 3:
                recent = prev[-10:]
                rolling_avg = sum(r.value for r in recent) / len(recent)
                if rolling_avg >= 5.0 and m.value >= 2.0 * rolling_avg:
                    severity = "CRITICAL" if m.value >= 3.0 * rolling_avg else "HIGH"
                    findings.append(
                        AnomalyFinding(
                            anomaly_type=AnomalyType.CROWD_SPIKE,
                            kind=AnomalyKind.ENVIRONMENTAL,
                            severity=severity,
                            rule_id="crowd.count_spike",
                            rule_version="1",
                            source_id=event.source_id,
                            event_id=event.event_id,
                            subject=subject,
                            measurement=m.name,
                            observed_value=m.value,
                            unit=m.unit,
                            threshold=round(2.0 * rolling_avg, 2),
                            score=round(m.value / rolling_avg, 2),
                            method="rolling_average_multiplier",
                            sample_count=len(recent),
                            expected_range={"rolling_average": round(rolling_avg, 2), "multiplier_threshold": 2.0},
                            explanation=(
                                f"{m.name} spiked to {m.value:g} {m.unit} "
                                f"({m.value / rolling_avg:.1f}x rolling average of {rolling_avg:.1f} {m.unit}, n={len(recent)}); "
                                "sudden surge in crowd density indicates potential gathering, congestion, or protest."
                            ),
                            details={
                                "rolling_average": round(rolling_avg, 2),
                                "multiplier": round(m.value / rolling_avg, 2),
                                "recent_samples": [r.value for r in recent],
                            },
                        )
                    )
    return findings


def _sensor_health(event: CanonicalEvent, ctx: AnomalyContext, cfg: ProcessingConfig,
                   subject: str) -> list[AnomalyFinding]:
    sh = cfg.sensor_health
    out: list[AnomalyFinding] = []

    # Flatline: N identical consecutive readings (including this one) over a minimum span.
    for m in event.measurements:
        prev = ctx.history.get(m.name, [])
        tail = prev[-(sh.flatline_min_readings - 1):] if sh.flatline_min_readings > 1 else []
        if len(tail) == sh.flatline_min_readings - 1 and all(
            r.value == m.value and r.unit == m.unit for r in tail
        ):
            span = (event.event_time - tail[0].event_time).total_seconds()
            if span >= sh.flatline_min_span_seconds:
                out.append(AnomalyFinding(
                    anomaly_type=AnomalyType.FLATLINE, kind=AnomalyKind.SENSOR_HEALTH,
                    severity="LOW", rule_id="sensor.flatline", rule_version="1",
                    source_id=event.source_id, event_id=event.event_id, subject=subject,
                    measurement=m.name, observed_value=m.value, unit=m.unit, method="flatline",
                    sample_count=sh.flatline_min_readings,
                    explanation=f"{m.name} reported exactly {m.value:g} {m.unit} "
                                f"{sh.flatline_min_readings} times over {span / 60:.0f} min; "
                                "possible stuck sensor (data-quality issue, not an incident)",
                ))

    # Neighbour conflict: nearby sensors disagree strongly at the same time.
    for name in sh.conflict_measurements:
        m = _measure(event, name)
        loc = event.location
        if m is None or not (loc and loc.has_coordinates):
            continue
        peers = [r for r in ctx.neighbours.get(name, [])
                 if r.unit == m.unit and r.latitude is not None and r.longitude is not None
                 and abs((r.event_time - event.event_time).total_seconds()) <= sh.conflict_window_seconds
                 and haversine_m(loc.latitude, loc.longitude, r.latitude, r.longitude)  # type: ignore[arg-type]
                 <= sh.conflict_radius_m]
        if not peers:
            continue
        peer_median = sorted(r.value for r in peers)[len(peers) // 2]
        scale = max(abs(m.value), abs(peer_median))
        if scale == 0:
            continue
        rel = abs(m.value - peer_median) / scale
        if rel >= sh.conflict_relative_difference:
            out.append(AnomalyFinding(
                anomaly_type=AnomalyType.SENSOR_CONFLICT, kind=AnomalyKind.SENSOR_HEALTH,
                severity="LOW", rule_id="sensor.neighbour_conflict", rule_version="1",
                source_id=event.source_id, event_id=event.event_id, subject=subject,
                measurement=name, observed_value=m.value, unit=m.unit,
                threshold=sh.conflict_relative_difference, score=round(rel, 4),
                method="neighbour_comparison", sample_count=len(peers),
                expected_range={"neighbour_median": peer_median},
                explanation=f"{name} = {m.value:g} {m.unit} disagrees with {len(peers)} sensor(s) "
                            f"within {sh.conflict_radius_m:.0f} m (median {peer_median:g}); "
                            f"relative difference {rel:.0%}. One of them may be faulty, or the "
                            "condition is very local",
                details={"neighbour_event_ids": [r.event_id for r in peers]},
            ))

    # Timestamp anomaly: observation claimed after receipt (provider clock skew).
    skew = (event.event_time - event.ingest_time).total_seconds()
    if skew > 1:
        out.append(AnomalyFinding(
            anomaly_type=AnomalyType.TIMESTAMP_ANOMALY, kind=AnomalyKind.SENSOR_HEALTH,
            severity="INFO", rule_id="sensor.clock_skew", rule_version="1",
            source_id=event.source_id, event_id=event.event_id, subject=subject,
            method="timestamp_check", score=skew,
            explanation=f"event_time is {skew:.0f}s after ingest_time; provider clock skew",
        ))
    return out


def evaluated_rule_subjects(event: CanonicalEvent, cfg: ProcessingConfig) -> list[str]:
    """Rule ids whose condition was *evaluated* (measurement present, unit compatible).

    Used to resolve an active anomaly when a later reading of the same subject is normal. A rule
    whose measurement is missing was not evaluated, so absence never clears an anomaly.
    """
    ids: list[str] = []
    for rule in cfg.thresholds:
        m = _measure(event, rule.measurement)
        if m is not None and m.unit == rule.unit:
            ids.append(rule.rule_id)
    return ids


def detect_stale_source(source_id: str, latest_event_time: datetime | None, now: datetime,
                        sla_seconds: int) -> AnomalyFinding | None:
    if latest_event_time is None:
        return None  # never observed: "unknown", not "stale"
    age = (now - latest_event_time).total_seconds()
    if age <= sla_seconds:
        return None
    return AnomalyFinding(
        anomaly_type=AnomalyType.STALE_SOURCE, kind=AnomalyKind.SENSOR_HEALTH,
        severity="MEDIUM" if age > 4 * sla_seconds else "LOW", rule_id="sensor.stale_source",
        rule_version="1", source_id=source_id, subject=f"source:{source_id}",
        method="freshness_sla", observed_value=age, unit="s", threshold=float(sla_seconds),
        explanation=f"no observation from {source_id} for {age / 60:.0f} min (expected within "
                    f"{sla_seconds / 60:.0f} min). Missing data is an observability gap and is "
                    "not evidence that conditions are normal",
    )


def detect_repeated_malformed(source_id: str, count: int, window_seconds: int,
                              min_count: int) -> AnomalyFinding | None:
    if count < min_count:
        return None
    return AnomalyFinding(
        anomaly_type=AnomalyType.REPEATED_MALFORMED, kind=AnomalyKind.SENSOR_HEALTH,
        severity="LOW", rule_id="sensor.repeated_malformed", rule_version="1",
        source_id=source_id, subject=f"source:{source_id}", method="quarantine_rate",
        observed_value=float(count), threshold=float(min_count),
        explanation=f"{count} malformed/quarantined records from {source_id} in the last "
                    f"{window_seconds / 60:.0f} min",
    )
