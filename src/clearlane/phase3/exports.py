"""Dashboard-ready exports: Parquet, CSV, JSON, GeoJSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def write_parquet(df: pd.DataFrame, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    return p


def write_csv(df: pd.DataFrame, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False)
    return p


def write_json_records(df: pd.DataFrame, path: str | Path, extra: dict[str, Any] | None = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"records": json.loads(df.to_json(orient="records"))}
    if extra:
        payload.update(extra)
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return p


def points_to_geojson(
    df: pd.DataFrame,
    lat_col: str,
    lng_col: str,
    property_cols: list[str],
    path: str | Path,
) -> Path:
    features = []
    for _, r in df.iterrows():
        lat, lng = r.get(lat_col), r.get(lng_col)
        if pd.isna(lat) or pd.isna(lng):
            continue
        props = {c: (None if pd.isna(r.get(c)) else r.get(c)) for c in property_cols if c in df.columns}
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lng), float(lat)]},
                "properties": props,
            }
        )
    fc = {"type": "FeatureCollection", "features": features}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(fc, indent=2, default=str), encoding="utf-8")
    return p


def segments_to_geojson(df: pd.DataFrame, property_cols: list[str], path: str | Path) -> Path:
    """route_geometry column holds a GeoJSON LineString dict (or JSON string)."""
    features = []
    for _, r in df.iterrows():
        geom = r.get("route_geometry")
        if isinstance(geom, str):
            try:
                geom = json.loads(geom)
            except Exception:
                geom = None
        if not isinstance(geom, dict):
            continue
        props = {c: (None if pd.isna(r.get(c)) else r.get(c)) for c in property_cols if c in df.columns}
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    fc = {"type": "FeatureCollection", "features": features}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(fc, indent=2, default=str), encoding="utf-8")
    return p
