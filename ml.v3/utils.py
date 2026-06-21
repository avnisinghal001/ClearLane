"""
ClearLane v3 — shared pure helpers.

IST conversion, JSON-array parsing, violation severity, vehicle footprint,
geo / H3 helpers, percentile normalisation, and JSON-safe serialisation.

Everything here is a PURE function; every tunable constant comes from config.py.
The H3 wrappers tolerate BOTH the h3 v4 API (`latlng_to_cell`, `grid_disk`,
`cell_to_latlng`, `cell_to_boundary`) and the older v3 API (`geo_to_h3`,
`k_ring`, `h3_to_geo`, `h3_to_geo_boundary`) so the code runs whatever wheel is
installed.
"""
from __future__ import annotations

import json
import math
import os
import sys
from typing import Iterable

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C  # noqa: E402


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #
def to_ist(series: pd.Series) -> pd.Series:
    """Parse a UTC timestamp column (+00) and convert to tz-naive IST.

    Example: '2023-11-20 00:28:46+00'  ->  2023-11-20 05:58:46 IST  (+5:30).
    """
    dt = pd.to_datetime(series, utc=True, errors="coerce", format="mixed")
    return dt.dt.tz_convert(C.IST_TZ).dt.tz_localize(None)


# --------------------------------------------------------------------------- #
# Violation / offence array parsing
# --------------------------------------------------------------------------- #
def parse_array(cell) -> list:
    """Parse a JSON-array string like '["WRONG PARKING","NO PARKING"]' -> list."""
    if isinstance(cell, list):
        return cell
    if cell is None or (isinstance(cell, float) and math.isnan(cell)):
        return []
    s = str(cell).strip()
    if s in ("", "NULL", "nan", "None", "[]"):
        return []
    try:
        val = json.loads(s)
        return [str(x).strip() for x in val] if isinstance(val, list) else [str(val).strip()]
    except (json.JSONDecodeError, ValueError):
        return [tok.strip().strip('"[]') for tok in s.split(",") if tok.strip()]


def _canonical(token: str) -> str:
    return str(token).upper().strip()


def is_parking_token(token: str) -> bool:
    t = _canonical(token)
    if any(bad in t for bad in C.NON_PARKING_TOKENS):
        if not any(k in t for k in ("PARKING", "FOOTPATH", "ROAD CROSSING",
                                    "MAIN ROAD", "DOUBLE", "ZEBRA")):
            return False
    return any(k in t for k in C.PARKING_KEYWORDS)


def severity_of(token: str) -> float:
    """Carriageway-blocking severity for a single violation token (0–1).

    Example: 'PARKING NEAR ROAD CROSSING' -> 0.90;  'FOOTPATH' -> 0.25.
    """
    t = _canonical(token)
    if t in C.SEVERITY_WEIGHTS:
        return C.SEVERITY_WEIGHTS[t]
    for key, w in C.SEVERITY_WEIGHTS.items():          # substring fallback
        if key in t:
            return w
    if is_parking_token(t):
        return C.SEVERITY_WEIGHTS["WRONG PARKING"]      # generic parking fallback
    return C.SEVERITY_DEFAULT


def primary_violation(tokens: Iterable[str]) -> str | None:
    """Highest-severity parking token on a row (its primary obstruction)."""
    best, best_sev = None, -1.0
    for tok in tokens:
        if is_parking_token(tok):
            s = severity_of(tok)
            if s > best_sev:
                best, best_sev = _canonical(tok), s
    return best


def row_severity(tokens: Iterable[str]) -> float:
    """Row severity = MAX parking-token severity (the worst obstruction wins)."""
    sevs = [severity_of(t) for t in tokens if is_parking_token(t)]
    return max(sevs) if sevs else 0.0


def has_parking(tokens: Iterable[str]) -> bool:
    return any(is_parking_token(t) for t in tokens)


def vehicle_weight(vtype) -> float:
    """Physical lane footprint of a vehicle class (0–1). CAR -> 0.60, BUS -> 1.0."""
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
    return ((lat >= C.BBOX["lat_min"]) & (lat <= C.BBOX["lat_max"]) &
            (lon >= C.BBOX["lon_min"]) & (lon <= C.BBOX["lon_max"]))


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def classify_road(segment) -> str:
    """Map an address string to a carriageway class (first keyword hit wins)."""
    if segment is None or (isinstance(segment, float) and math.isnan(segment)):
        return "unknown"
    s = str(segment).lower()
    for kw, cls in C.ROAD_CLASS_KEYWORDS:
        if kw in s:
            return cls
    return "unknown"


# --------------------------------------------------------------------------- #
# H3 — version-safe wrappers (works on h3 v4 OR v3)
# --------------------------------------------------------------------------- #
try:
    import h3 as _h3
    _HAS_H3 = True
except Exception:                       # pragma: no cover
    _HAS_H3 = False


def h3_available() -> bool:
    return _HAS_H3


def h3_cell(lat: float, lon: float, res: int) -> str | None:
    """(lat, lon) -> H3 cell id at `res`. Example: (12.9256, 77.6187, 10)."""
    if not _HAS_H3 or lat is None or lon is None:
        return None
    try:                                # h3 v4
        return _h3.latlng_to_cell(lat, lon, res)
    except AttributeError:              # h3 v3
        return _h3.geo_to_h3(lat, lon, res)


def h3_to_latlng(cell: str) -> tuple[float, float]:
    """H3 cell -> (lat, lon) of its centroid."""
    try:
        return tuple(_h3.cell_to_latlng(cell))          # v4
    except AttributeError:
        return tuple(_h3.h3_to_geo(cell))               # v3


def h3_ring(cell: str, k: int = 1) -> list[str]:
    """The cells within k rings of `cell`, EXCLUDING the centre cell."""
    try:
        ring = set(_h3.grid_disk(cell, k))              # v4
    except AttributeError:
        ring = set(_h3.k_ring(cell, k))                 # v3
    ring.discard(cell)
    return list(ring)


def h3_parent(cell: str, res: int) -> str:
    """Coarse parent cell at `res` (used to build spatial CV blocks)."""
    try:
        return _h3.cell_to_parent(cell, res)            # v4
    except AttributeError:
        return _h3.h3_to_parent(cell, res)              # v3


def h3_boundary(cell: str) -> list[list[float]]:
    """Polygon ring [[lat,lon],...] for drawing the hexagon on a map."""
    try:
        return [list(p) for p in _h3.cell_to_boundary(cell)]        # v4
    except AttributeError:
        return [list(p) for p in _h3.h3_to_geo_boundary(cell)]      # v3


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #
def percentile_norm(values: pd.Series) -> pd.Series:
    """Percentile-rank to 0–100. Robust to outliers (unlike min-max)."""
    if values.nunique() <= 1:
        return pd.Series(np.full(len(values), 50.0), index=values.index)
    return values.rank(pct=True) * 100.0


# --------------------------------------------------------------------------- #
# JSON-safe serialisation (NaN / Inf / numpy types -> plain JSON)
# --------------------------------------------------------------------------- #
def json_safe(obj):
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
    return obj


def write_json(path, obj):
    import pathlib
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(json_safe(obj), f, separators=(",", ":"))
    return path
