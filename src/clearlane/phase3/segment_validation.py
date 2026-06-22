"""Road-segment validity rules and candidate scoring (pure)."""

from __future__ import annotations

import hashlib
import math
from typing import Any, Optional

# Bengaluru bounding box (generous) — coordinates must stay inside.
BLR_BBOX = {"min_lat": 12.6, "max_lat": 13.3, "min_lng": 77.3, "max_lng": 77.9}


def inside_bengaluru(lat: float, lng: float) -> bool:
    return (
        BLR_BBOX["min_lat"] <= lat <= BLR_BBOX["max_lat"]
        and BLR_BBOX["min_lng"] <= lng <= BLR_BBOX["max_lng"]
    )


def is_valid_segment(
    *,
    route_ok: bool,
    distance_m: Optional[float],
    duration_s: Optional[float],
    geometry_decoded: bool,
    geometry_status: str,
    n_points: int,
    distance_min_m: float,
    distance_max_m: float,
    midpoint_distance_from_h3_m: Optional[float],
    max_midpoint_distance_m: float,
    detour_ratio: Optional[float],
    max_detour_ratio: float,
    coords_inside_blr: bool,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not route_ok:
        reasons.append("ROUTE_FAILED")
    if distance_m is None or not math.isfinite(distance_m) or distance_m <= 0:
        reasons.append("BAD_DISTANCE")
    if duration_s is None or not math.isfinite(duration_s) or duration_s <= 0:
        reasons.append("BAD_DURATION")
    if not geometry_decoded:
        reasons.append("GEOMETRY_NOT_DECODED")
    if geometry_status == "GEOMETRY_DISTANCE_MISMATCH":
        reasons.append("GEOMETRY_DISTANCE_MISMATCH")
    if n_points < 2:
        reasons.append("GEOMETRY_TOO_FEW_POINTS")
    if distance_m is not None:
        if distance_m < distance_min_m:
            reasons.append("TOO_SHORT")
        if distance_m > distance_max_m:
            reasons.append("TOO_LONG")
    if midpoint_distance_from_h3_m is not None and midpoint_distance_from_h3_m > max_midpoint_distance_m:
        reasons.append("MIDPOINT_TOO_FAR_FROM_H3")
    if detour_ratio is not None and detour_ratio > max_detour_ratio:
        reasons.append("EXTREME_LOOP")
    if not coords_inside_blr:
        reasons.append("OUTSIDE_BENGALURU")
    return (len(reasons) == 0), reasons


def score_candidate(
    *,
    route_ok: bool,
    distance_m: Optional[float],
    target_length_m: float,
    midpoint_distance_from_h3_m: Optional[float],
    max_midpoint_distance_m: float,
    detour_ratio: Optional[float],
    geometry_valid: bool,
    endpoints_valid: bool,
    duplicate_penalty: float = 0.0,
) -> float:
    """Higher is better, roughly in [0, 1]."""
    if not route_ok or distance_m is None:
        return 0.0
    score = 0.0
    score += 0.35 if geometry_valid else 0.0
    score += 0.15 if endpoints_valid else 0.0
    # distance closeness to target
    close = max(0.0, 1.0 - abs(distance_m - target_length_m) / max(target_length_m, 1.0))
    score += 0.25 * close
    # midpoint closeness
    if midpoint_distance_from_h3_m is not None:
        midclose = max(0.0, 1.0 - midpoint_distance_from_h3_m / max(max_midpoint_distance_m, 1.0))
        score += 0.15 * midclose
    # detour penalty
    if detour_ratio is not None:
        score += 0.10 * max(0.0, 1.0 - (detour_ratio - 1.0))
    score -= duplicate_penalty
    return round(max(0.0, min(1.0, score)), 6)


def _round_coord(v: float, ndigits: int = 5) -> float:
    return round(v, ndigits)


def physical_segment_id(h3: str, a: tuple[float, float], b: tuple[float, float], algo_version: str) -> str:
    """Deterministic ID from H3 + rounded endpoints + algorithm version.

    Endpoints are sorted so A_TO_B and B_TO_A share the same physical id.
    Run id / timestamp are intentionally excluded.
    """
    pa = (_round_coord(a[0]), _round_coord(a[1]))
    pb = (_round_coord(b[0]), _round_coord(b[1]))
    lo, hi = sorted([pa, pb])
    key = f"{h3}|{lo[0]},{lo[1]}|{hi[0]},{hi[1]}|{algo_version}"
    return "pseg_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def directed_segment_id(physical_id: str, direction: str) -> str:
    return f"{physical_id}_{direction}"
