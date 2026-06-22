"""Congestion severity from live ETA vs reference duration.

    TTI               = live_eta_duration_s / reference_duration_s
    delay_seconds     = max(0, live - reference)
    delay_ratio       = max(0, live - reference) / reference
    congestion_severity = clip(1 - reference/live, 0, 1) = clip(1 - 1/TTI, 0, 1)

Missing ETA or baseline must stay null — never coerced to zero congestion.
Severity labels are display-only.
"""

from __future__ import annotations

import math
from typing import Any, Optional

LABEL_BANDS = [
    ("NORMAL", 0.00, 0.15),
    ("MODERATE", 0.15, 0.35),
    ("HIGH", 0.35, 0.55),
    ("SEVERE", 0.55, 1.01),
]


def _finite_positive(x: Optional[float]) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x) and x > 0


def travel_time_index(live_eta_s: Optional[float], reference_s: Optional[float]) -> Optional[float]:
    if not (_finite_positive(live_eta_s) and _finite_positive(reference_s)):
        return None
    return live_eta_s / reference_s


def delay_seconds(live_eta_s: Optional[float], reference_s: Optional[float]) -> Optional[float]:
    if live_eta_s is None or reference_s is None:
        return None
    if not (math.isfinite(live_eta_s) and math.isfinite(reference_s)):
        return None
    return max(0.0, live_eta_s - reference_s)


def delay_ratio(live_eta_s: Optional[float], reference_s: Optional[float]) -> Optional[float]:
    if not _finite_positive(reference_s) or live_eta_s is None or not math.isfinite(live_eta_s):
        return None
    return max(0.0, live_eta_s - reference_s) / reference_s


def congestion_severity(live_eta_s: Optional[float], reference_s: Optional[float]) -> Optional[float]:
    """clip(1 - reference/live, 0, 1). Returns None if inputs unusable."""
    if not (_finite_positive(live_eta_s) and _finite_positive(reference_s)):
        return None
    sev = 1.0 - (reference_s / live_eta_s)
    return min(1.0, max(0.0, sev))


def severity_label(severity: Optional[float]) -> Optional[str]:
    if severity is None or not math.isfinite(severity):
        return None
    for label, lo, hi in LABEL_BANDS:
        if lo <= severity < hi:
            return label
    return "SEVERE" if severity >= 0.55 else "NORMAL"


def compute(live_eta_s: Optional[float], reference_s: Optional[float]) -> dict[str, Any]:
    sev = congestion_severity(live_eta_s, reference_s)
    return {
        "travel_time_index": travel_time_index(live_eta_s, reference_s),
        "delay_seconds": delay_seconds(live_eta_s, reference_s),
        "delay_ratio": delay_ratio(live_eta_s, reference_s),
        "congestion_severity": sev,
        "congestion_label": severity_label(sev),
    }


BOTH_VALID = "BOTH_DIRECTIONS_VALID"
ONE_VALID = "ONE_DIRECTION_VALID"
NONE_VALID = "NO_VALID_DIRECTION"


def aggregate_directions(
    a_to_b_severity: Optional[float],
    b_to_a_severity: Optional[float],
) -> dict[str, Any]:
    """Per physical segment: aggregate the two directed severities.

    Primary H3 severity is the MAXIMUM valid directional severity, which preserves
    directional obstruction (one blocked direction still flags the cell).
    """
    valid = [
        (d, s)
        for d, s in (("A_TO_B", a_to_b_severity), ("B_TO_A", b_to_a_severity))
        if _finite_positive(s) or (s is not None and math.isfinite(s) and s >= 0)
    ]
    if not valid:
        return {
            "maximum_severity": None,
            "mean_severity": None,
            "maximum_severity_direction": None,
            "valid_direction_count": 0,
            "directional_coverage_status": NONE_VALID,
        }
    severities = [s for _, s in valid]
    max_dir, max_sev = max(valid, key=lambda kv: kv[1])
    status = BOTH_VALID if len(valid) == 2 else ONE_VALID
    return {
        "maximum_severity": max_sev,
        "mean_severity": sum(severities) / len(severities),
        "maximum_severity_direction": max_dir,
        "valid_direction_count": len(valid),
        "directional_coverage_status": status,
    }
