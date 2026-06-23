from __future__ import annotations

from typing import Any

import pandas as pd


def station_summary(mapping: pd.DataFrame, h3_col: str = "h3_res10") -> pd.DataFrame:
    if "police_station_normalized" not in mapping.columns:
        raise ValueError("police_station_normalized is required for station summaries.")
    rows = []
    for station, group in mapping.groupby("police_station_normalized", dropna=False):
        top_cells = (
            group[h3_col].value_counts()
            .head(10)
            .rename_axis(h3_col)
            .reset_index(name="citation_count")
            .to_dict(orient="records")
        )
        rows.append({
            "police_station_normalized": station,
            "citation_count": int(len(group)),
            "unique_h3_cells": int(group[h3_col].nunique()),
            "unique_devices": int(group["device_id"].nunique(dropna=True)) if "device_id" in group else 0,
            "top_h3_cells": top_cells,
        })
    return pd.DataFrame(rows).sort_values("citation_count", ascending=False).reset_index(drop=True)


def station_report(summary: pd.DataFrame) -> dict[str, Any]:
    return {
        "status": "PASS",
        "station_count": int(len(summary)),
        "top_stations": summary.head(10).to_dict(orient="records"),
    }
