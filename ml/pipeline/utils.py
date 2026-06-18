"""
Shared helpers: IST conversion, JSON-array parsing, violation severity lookup,
geo-bucketing, percentile normalization, and JSON-safe serialization.

Pure functions only — every tunable constant comes from config.py.
"""
from __future__ import annotations

import json
import math
from typing import Iterable

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C  # noqa: E402


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #
def to_ist(series: pd.Series) -> pd.Series:
    """Parse a UTC timestamp column (+00) and convert to tz-naive IST."""
    dt = pd.to_datetime(series, utc=True, errors="coerce", format="mixed")
    return dt.dt.tz_convert(C.IST_TZ).dt.tz_localize(None)


# --------------------------------------------------------------------------- #
# Violation / offence array parsing
# --------------------------------------------------------------------------- #
def parse_array(cell) -> list:
    """Parse a JSON-array string like '["WRONG PARKING","NO PARKING"]' -> list.

    Handles NULL / NaN / empty, plain strings, and already-parsed lists.
    """
    if isinstance(cell, list):
        return cell
    if cell is None or (isinstance(cell, float) and math.isnan(cell)):
        return []
    s = str(cell).strip()
    if s in ("", "NULL", "nan", "None", "[]"):
        return []
    try:
        val = json.loads(s)
        if isinstance(val, list):
            return [str(x).strip() for x in val]
        return [str(val).strip()]
    except (json.JSONDecodeError, ValueError):
        # Fall back to a bare comma split on a non-JSON string.
        return [tok.strip().strip('"[]') for tok in s.split(",") if tok.strip()]


def _canonical(token: str) -> str:
    return str(token).upper().strip()


def is_parking_token(token: str) -> bool:
    t = _canonical(token)
    if any(bad in t for bad in C.NON_PARKING_TOKENS):
        # explicit non-parking noise unless it ALSO clearly mentions parking
        if not any(k in t for k in ("PARKING", "FOOTPATH", "ROAD CROSSING",
                                    "MAIN ROAD", "DOUBLE", "ZEBRA")):
            return False
    return any(k in t for k in C.PARKING_KEYWORDS)


def severity_of(token: str) -> float:
    """Severity weight for a single violation token (carriageway-blocking)."""
    t = _canonical(token)
    if t in C.SEVERITY_WEIGHTS:
        return C.SEVERITY_WEIGHTS[t]
    # substring match against the canonical table (handles BTP phrasings)
    for key, w in C.SEVERITY_WEIGHTS.items():
        if key in t:
            return w
    if is_parking_token(t):
        return C.SEVERITY_WEIGHTS["WRONG PARKING"]   # generic parking fallback
    return C.SEVERITY_DEFAULT


def primary_violation(tokens: Iterable[str]) -> str | None:
    """Highest-severity parking token on a row (the row's primary obstruction)."""
    best, best_sev = None, -1.0
    for tok in tokens:
        if not is_parking_token(tok):
            continue
        s = severity_of(tok)
        if s > best_sev:
            best, best_sev = _canonical(tok), s
    return best


def row_severity(tokens: Iterable[str]) -> float:
    """Severity contribution of a row = max parking-token severity."""
    sevs = [severity_of(t) for t in tokens if is_parking_token(t)]
    return max(sevs) if sevs else 0.0


def has_parking(tokens: Iterable[str]) -> bool:
    return any(is_parking_token(t) for t in tokens)


# --------------------------------------------------------------------------- #
# Vehicle
# --------------------------------------------------------------------------- #
def vehicle_weight(vtype) -> float:
    if vtype is None or (isinstance(vtype, float) and math.isnan(vtype)):
        return C.VEHICLE_DEFAULT
    t = _canonical(vtype)
    if t in C.VEHICLE_WEIGHTS:
        return C.VEHICLE_WEIGHTS[t]
    for key, w in C.VEHICLE_WEIGHTS.items():
        if key in t:
            return w
    return C.VEHICLE_DEFAULT


# --------------------------------------------------------------------------- #
# Geo
# --------------------------------------------------------------------------- #
def in_bbox(lat: pd.Series, lon: pd.Series) -> pd.Series:
    return (
        (lat >= C.BBOX["lat_min"]) & (lat <= C.BBOX["lat_max"]) &
        (lon >= C.BBOX["lon_min"]) & (lon <= C.BBOX["lon_max"])
    )


def bucket_100m(lat: pd.Series, lon: pd.Series) -> pd.Series:
    return (lat.round(C.BUCKET_100M_DECIMALS).astype(str) + "_" +
            lon.round(C.BUCKET_100M_DECIMALS).astype(str))


def point_11m(lat: pd.Series, lon: pd.Series) -> pd.Series:
    return (lat.round(C.POINT_11M_DECIMALS).astype(str) + "_" +
            lon.round(C.POINT_11M_DECIMALS).astype(str))


def superzone_cell(lat: pd.Series, lon: pd.Series) -> pd.Series:
    """Snap to the ~500 m grid cell index (deterministic grid-merge)."""
    cy = np.floor(lat / C.SUPERZONE_CELL_DEG).astype("int64")
    cx = np.floor(lon / C.SUPERZONE_CELL_DEG).astype("int64")
    return cy.astype(str) + "_" + cx.astype(str)


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def nearest_anchor_m(lat, lon, anchors) -> float:
    """Metres from (lat,lon) to the nearest (name,lat,lon) anchor; inf if none."""
    best = float("inf")
    for _, alat, alon in anchors:
        d = haversine_m(lat, lon, alat, alon)
        if d < best:
            best = d
    return best


# --------------------------------------------------------------------------- #
# Carriageway Impact Index helpers (stage 04) — static road context, NOT flow.
# --------------------------------------------------------------------------- #
def classify_road(segment) -> str:
    """Map a zone's modal address segment to a carriageway class.

    Pure substring match against config.ROAD_CLASS_KEYWORDS (first hit wins).
    Returns 'unknown' when nothing matches or the segment is empty.
    """
    if segment is None or (isinstance(segment, float) and math.isnan(segment)):
        return "unknown"
    s = str(segment).lower()
    for kw, cls in C.ROAD_CLASS_KEYWORDS:
        if kw in s:
            return cls
    return "unknown"


def demand_proximity(dist_m) -> float:
    """Linear decay of demand-generator proximity to [0,1].

    1.0 within DEMAND_NEAR_M, 0.0 beyond DEMAND_FAR_M, linear in between.
    """
    if dist_m is None or dist_m == float("inf") or (isinstance(dist_m, float) and math.isnan(dist_m)):
        return 0.0
    near, far = C.DEMAND_NEAR_M, C.DEMAND_FAR_M
    if dist_m <= near:
        return 1.0
    if dist_m >= far:
        return 0.0
    return float((far - dist_m) / (far - near))


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #
def percentile_norm(values: pd.Series) -> pd.Series:
    """Percentile-rank to 0–100. Robust to outliers (unlike min-max)."""
    if values.nunique() <= 1:
        return pd.Series(np.full(len(values), 50.0), index=values.index)
    return values.rank(pct=True) * 100.0


# --------------------------------------------------------------------------- #
# JSON-safe serialization (NaN / Inf / numpy types)
# --------------------------------------------------------------------------- #
def json_safe(obj):
    """Recursively convert numpy/pandas types and scrub NaN/Inf -> None."""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.ndarray,)):
        return [json_safe(v) for v in obj.tolist()]
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    if obj is pd.NaT:
        return None
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def write_json(path, obj):
    import pathlib
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(json_safe(obj), f, separators=(",", ":"))
    return path
