from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from clearlane.phase1.reporting import json_safe

from .h3_geometry import feature_collection, h3_feature


def write_json(path: str | Path, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(json_safe(obj), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_table(df: pd.DataFrame, parquet_path: str | Path,
                csv_path: str | Path | None = None) -> None:
    p = Path(parquet_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    if csv_path is not None:
        c = Path(csv_path)
        c.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(c, index=False)


def write_hotspot_geojson(df: pd.DataFrame, path: str | Path,
                          h3_col: str = "h3_res10") -> None:
    features = []
    for row in df.to_dict(orient="records"):
        cell = row[h3_col]
        features.append(h3_feature(cell, {k: v for k, v in row.items() if k != "geometry_geojson"}))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(json_safe(feature_collection(features)), indent=2) + "\n", encoding="utf-8")
