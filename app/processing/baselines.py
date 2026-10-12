"""Robust baseline statistics.

``robust_z = (x - median) / (1.4826 * MAD)`` where MAD is the median absolute deviation.
1.4826 makes MAD a consistent estimator of the standard deviation for normal data.

A z-score is only reported when the baseline is adequate. Each failure mode returns an explicit
``reason`` instead of a number that would look reliable but is not.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

__all__ = ["BaselineStats", "robust_baseline", "MAD_SCALE"]

MAD_SCALE = 1.4826


@dataclass(slots=True)
class BaselineStats:
    usable: bool
    reason: str | None
    sample_count: int
    median: float | None = None
    mad: float | None = None
    robust_z: float | None = None
    excluded: int = 0
    notes: list[str] = field(default_factory=list)


def robust_baseline(
    value: float,
    history: list[tuple[float, bool]],
    *,
    min_samples: int,
) -> BaselineStats:
    """``history`` is ``[(value, was_anomalous), ...]`` from the same subject and unit.

    Values previously flagged anomalous are excluded to limit baseline contamination; non-finite
    values are dropped. Irregular intervals do not bias a median, so no resampling is done.
    """
    clean = [v for v, flagged in history if not flagged and v is not None and math.isfinite(v)]
    excluded = len(history) - len(clean)
    if not math.isfinite(value):
        return BaselineStats(False, "NON_FINITE_VALUE", len(clean), excluded=excluded)
    if len(clean) < min_samples:
        return BaselineStats(False, "INSUFFICIENT_HISTORY", len(clean), excluded=excluded,
                             notes=[f"{len(clean)} usable samples < minimum {min_samples}"])
    med = statistics.median(clean)
    mad = statistics.median(abs(v - med) for v in clean)
    if mad == 0:
        # A constant baseline gives an infinite/undefined z. Report it rather than invent one.
        return BaselineStats(False, "ZERO_MAD", len(clean), median=med, mad=0.0,
                             excluded=excluded,
                             notes=["baseline is constant; robust z undefined"
                                    + ("" if value == med else f"; value differs by {value - med:+g}")])
    z = (value - med) / (MAD_SCALE * mad)
    return BaselineStats(True, None, len(clean), median=med, mad=mad, robust_z=z,
                         excluded=excluded)
