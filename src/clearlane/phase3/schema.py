"""Explicit schema adapter for the Phase 2 hotspot table.

We prefer the real Phase 2 column names but tolerate documented equivalents so a
future Phase 2 rename does not silently break Phase 3. Adaptation is explicit and
reported (see input_schema_report.json), never guessed at call sites.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# canonical -> list of acceptable source names (first match wins)
COLUMN_ALIASES: dict[str, list[str]] = {
    "h3_res10": ["h3_res10", "h3_index", "h3"],
    "centroid_latitude": ["centroid_latitude", "lat", "latitude"],
    "centroid_longitude": ["centroid_longitude", "lng", "lon", "longitude"],
    "mode_police_station": ["mode_police_station", "police_station", "station"],
    "mode_junction": ["mode_junction", "junction", "junction_name"],
    "eligible_for_corrected_ranking": ["eligible_for_corrected_ranking", "eligible"],
    "normalized_propensity": ["normalized_propensity", "propensity"],
    "corrected_rank": ["corrected_rank", "rank"],
    "citation_count": ["citation_count", "tickets", "citations"],
    "device_days": ["device_days", "device_day_exposure"],
    "spatial_test_status": ["spatial_test_status", "spatial_status"],
}

REQUIRED_CANONICAL = [
    "h3_res10",
    "centroid_latitude",
    "centroid_longitude",
    "mode_police_station",
    "eligible_for_corrected_ranking",
    "normalized_propensity",
    "corrected_rank",
    "spatial_test_status",
]


class SchemaError(RuntimeError):
    pass


def resolve_columns(columns: list[str]) -> dict[str, str]:
    """Return canonical -> actual source column name for every alias found."""
    present = set(columns)
    mapping: dict[str, str] = {}
    for canonical, candidates in COLUMN_ALIASES.items():
        for cand in candidates:
            if cand in present:
                mapping[canonical] = cand
                break
    return mapping


def schema_report(df: pd.DataFrame) -> dict[str, Any]:
    mapping = resolve_columns(list(df.columns))
    missing_required = [c for c in REQUIRED_CANONICAL if c not in mapping]
    adapted = {c: src for c, src in mapping.items() if src != c}
    return {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "resolved_mapping": mapping,
        "adapted_columns": adapted,
        "missing_required_columns": missing_required,
        "required_columns_present": not missing_required,
        "all_columns": list(df.columns),
    }


def canonicalize(df: pd.DataFrame) -> pd.DataFrame:
    """Return a view with canonical column names available (originals retained).

    Missing required columns raise SchemaError. Equivalent names are copied to
    canonical names so downstream code only references canonical names.
    """
    mapping = resolve_columns(list(df.columns))
    missing = [c for c in REQUIRED_CANONICAL if c not in mapping]
    if missing:
        raise SchemaError(
            "Phase 2 hotspot table is missing required columns (no alias matched): "
            + ", ".join(missing)
        )
    out = df.copy()
    for canonical, src in mapping.items():
        if src != canonical and canonical not in out.columns:
            out[canonical] = out[src]
    return out
