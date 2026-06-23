"""Traffic quantification from Mappls route distance and durations.

    TTI               = live_eta_duration_s / reference_duration_s
    current_speed     = live_distance_m / live_eta_duration_s
    reference_speed   = reference_distance_m / reference_duration_s
    speed_reduction   = max(0, 1 - current_speed/reference_speed)
    delay_seconds     = max(0, live - reference)
    delay_percentage  = max(0, live - reference) / reference * 100
    congestion_severity = clip(1 - reference/live, 0, 1) = clip(1 - 1/TTI, 0, 1)

Missing ETA or baseline must stay null — never coerced to zero congestion.
Traffic labels are display-only and come from config thresholds.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

DEFAULT_TRAFFIC_LABEL_BANDS = [
    ("NORMAL", 0.0, 10.0),
    ("LIGHT_CONGESTION", 10.0, 25.0),
    ("MODERATE_CONGESTION", 25.0, 45.0),
    ("HIGH_CONGESTION", 45.0, 65.0),
    ("SEVERE_CONGESTION", 65.0, 100.000001),
]

LEGACY_SEVERITY_BANDS = [
    ("NORMAL", 0.00, 0.15),
    ("MODERATE", 0.15, 0.35),
    ("HIGH", 0.35, 0.55),
    ("SEVERE", 0.55, 1.01),
]


def _finite_positive(x: Optional[float]) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x) and x > 0


def _finite_number(x: Optional[float]) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def travel_time_index(live_eta_s: Optional[float], reference_s: Optional[float]) -> Optional[float]:
    if not (_finite_positive(live_eta_s) and _finite_positive(reference_s)):
        return None
    return live_eta_s / reference_s


def speed_kmh(distance_m: Optional[float], duration_s: Optional[float]) -> Optional[float]:
    if not (_finite_positive(distance_m) and _finite_positive(duration_s)):
        return None
    return (distance_m / duration_s) * 3.6


def speed_reduction_percentage(
    current_speed_kmh: Optional[float],
    reference_speed_kmh: Optional[float],
) -> Optional[float]:
    if not (_finite_positive(current_speed_kmh) and _finite_positive(reference_speed_kmh)):
        return None
    return max(0.0, 1.0 - (current_speed_kmh / reference_speed_kmh)) * 100.0


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


def delay_percentage(live_eta_s: Optional[float], reference_s: Optional[float]) -> Optional[float]:
    ratio = delay_ratio(live_eta_s, reference_s)
    return None if ratio is None else ratio * 100.0


def congestion_severity(live_eta_s: Optional[float], reference_s: Optional[float]) -> Optional[float]:
    """clip(1 - reference/live, 0, 1). Returns None if inputs unusable."""
    if not (_finite_positive(live_eta_s) and _finite_positive(reference_s)):
        return None
    sev = 1.0 - (reference_s / live_eta_s)
    return min(1.0, max(0.0, sev))


def congestion_severity_percentage(
    live_eta_s: Optional[float],
    reference_s: Optional[float],
) -> Optional[float]:
    sev = congestion_severity(live_eta_s, reference_s)
    return None if sev is None else sev * 100.0


def percentage_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """Signed percentage change from previous to current."""
    if not (_finite_number(current) and _finite_positive(previous)):
        return None
    return ((current - previous) / previous) * 100.0


def _traffic_label_bands(config: Mapping[str, Any] | None = None) -> list[tuple[str, float, float]]:
    raw = ((config or {}).get("congestion") or {}).get("traffic_label_bands")
    if not raw:
        return DEFAULT_TRAFFIC_LABEL_BANDS
    items = raw.items() if isinstance(raw, Mapping) else enumerate(raw)
    bands: list[tuple[str, float, float]] = []
    for key, value in items:
        if not isinstance(value, Mapping):
            continue
        label = str(value.get("label") or key).upper()
        lo = float(value["minimum"])
        hi = float(value["maximum"])
        bands.append((label, lo, hi))
    return bands or DEFAULT_TRAFFIC_LABEL_BANDS


def traffic_label(
    speed_reduction_pct: Optional[float],
    config: Mapping[str, Any] | None = None,
) -> Optional[str]:
    if speed_reduction_pct is None or not math.isfinite(speed_reduction_pct):
        return None
    pct = max(0.0, min(100.0, speed_reduction_pct))
    bands = _traffic_label_bands(config)
    for i, (label, lo, hi) in enumerate(bands):
        is_last = i == len(bands) - 1
        if lo <= pct < hi or (is_last and lo <= pct <= hi):
            return label
    return bands[-1][0] if pct >= bands[-1][1] else bands[0][0]


def severity_label(severity: Optional[float]) -> Optional[str]:
    """Legacy 0..1 severity label retained for compatibility."""
    if severity is None or not math.isfinite(severity):
        return None
    for label, lo, hi in LEGACY_SEVERITY_BANDS:
        if lo <= severity < hi:
            return label
    return "SEVERE" if severity >= 0.55 else "NORMAL"


def compute(
    live_eta_s: Optional[float],
    reference_s: Optional[float],
    *,
    current_distance_m: Optional[float] = None,
    reference_distance_m: Optional[float] = None,
    previous_live_eta_s: Optional[float] = None,
    previous_current_speed_kmh: Optional[float] = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current_speed = speed_kmh(current_distance_m, live_eta_s)
    reference_speed = speed_kmh(reference_distance_m, reference_s)
    reduction_pct = speed_reduction_percentage(current_speed, reference_speed)
    sev = congestion_severity(live_eta_s, reference_s)
    label = traffic_label(reduction_pct, config)
    return {
        "current_eta_seconds": live_eta_s,
        "reference_duration_seconds": reference_s,
        "current_speed_kmh": current_speed,
        "reference_speed_kmh": reference_speed,
        "speed_reduction_percentage": reduction_pct,
        "travel_time_index": travel_time_index(live_eta_s, reference_s),
        "delay_seconds": delay_seconds(live_eta_s, reference_s),
        "delay_ratio": delay_ratio(live_eta_s, reference_s),
        "delay_percentage": delay_percentage(live_eta_s, reference_s),
        "congestion_severity": sev,
        "congestion_severity_percentage": None if sev is None else sev * 100.0,
        "traffic_label": label,
        "congestion_label": label,
        "eta_change_percentage": percentage_change(live_eta_s, previous_live_eta_s),
        "speed_change_percentage": percentage_change(current_speed, previous_current_speed_kmh),
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
