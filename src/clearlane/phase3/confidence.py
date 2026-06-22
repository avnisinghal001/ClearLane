"""Transparent, versioned confidence fields.

Confidence is kept SEPARATE from PIC and is never multiplied into the primary PIC
score. Each component is a documented 0..1 score; overall confidence is their
mean. The methodology is emitted to reports/confidence_methodology.json.
"""

from __future__ import annotations

from typing import Any, Optional

METHODOLOGY_VERSION = "phase3-confidence-v1"


def historical_confidence(device_days: Optional[float], spatial_test_status: Optional[str]) -> float:
    score = 0.0
    dd = device_days or 0
    if dd >= 30:
        score += 0.6
    elif dd >= 14:
        score += 0.45
    elif dd >= 5:
        score += 0.3
    else:
        score += 0.1
    score += 0.4 if spatial_test_status == "TESTED" else 0.15
    return round(min(1.0, score), 4)


def baseline_confidence(baseline_status: Optional[str], sample_count: Optional[int]) -> float:
    base = {
        "READY_ROLLING_P10": 0.9,
        "PROVISIONAL_MAPPLS_NON_TRAFFIC": 0.45,
        "PROVISIONAL_INSUFFICIENT_HISTORY": 0.4,
        "UNAVAILABLE": 0.0,
    }.get(baseline_status or "UNAVAILABLE", 0.0)
    sc = sample_count or 0
    bonus = min(0.1, sc / 200.0)
    return round(min(1.0, base + bonus), 4)


def live_observation_confidence(
    *,
    is_valid: bool,
    fresh: bool,
    route_consistent: bool,
) -> float:
    if not is_valid:
        return 0.0
    score = 0.5
    if fresh:
        score += 0.3
    if route_consistent:
        score += 0.2
    return round(min(1.0, score), 4)


def directional_confidence(directional_coverage_status: Optional[str]) -> float:
    return {
        "BOTH_DIRECTIONS_VALID": 1.0,
        "ONE_DIRECTION_VALID": 0.6,
        "NO_VALID_DIRECTION": 0.0,
    }.get(directional_coverage_status or "NO_VALID_DIRECTION", 0.0)


def overall_confidence(components: dict[str, float]) -> float:
    vals = [v for v in components.values() if v is not None]
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 4)


def compute_all(
    *,
    device_days: Optional[float],
    spatial_test_status: Optional[str],
    baseline_status: Optional[str],
    baseline_sample_count: Optional[int],
    live_valid: bool,
    fresh: bool,
    route_consistent: bool,
    directional_coverage_status: Optional[str],
) -> dict[str, Any]:
    hist = historical_confidence(device_days, spatial_test_status)
    base = baseline_confidence(baseline_status, baseline_sample_count)
    live = live_observation_confidence(is_valid=live_valid, fresh=fresh, route_consistent=route_consistent)
    direction = directional_confidence(directional_coverage_status)
    overall = overall_confidence(
        {
            "historical_confidence": hist,
            "baseline_confidence": base,
            "live_observation_confidence": live,
            "directional_confidence": direction,
        }
    )
    return {
        "historical_confidence": hist,
        "baseline_confidence": base,
        "live_observation_confidence": live,
        "directional_confidence": direction,
        "overall_pic_confidence": overall,
    }


def methodology() -> dict[str, Any]:
    return {
        "version": METHODOLOGY_VERSION,
        "principle": "Confidence is reported separately and is NEVER multiplied into PIC.",
        "components": {
            "historical_confidence": "device-day exposure + Phase 2 spatial_test_status (TESTED).",
            "baseline_confidence": "baseline_status tier + small bonus for sample_count.",
            "live_observation_confidence": "validity + freshness + route consistency.",
            "directional_confidence": "both / one / no valid monitored direction.",
            "overall_pic_confidence": "unweighted mean of the four components.",
        },
        "ranges": "All components and overall are in [0, 1].",
    }
