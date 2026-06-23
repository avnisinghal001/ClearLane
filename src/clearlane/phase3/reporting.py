"""Phase 3 report assembly and localized-anomaly aggregation across cells."""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from . import localized_anomaly as la


def compute_localized_anomalies(
    pic_df: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    """Add localized-slowdown columns using ring-1 monitored neighbours.

    pic_df must have h3_res10 and congestion_severity (per the same completed cycle).
    """
    min_neighbors = int(config["localized_anomaly"]["minimum_valid_monitored_neighbors"])
    sev_by_h3 = {
        str(r["h3_res10"]): (None if pd.isna(r.get("congestion_severity")) else float(r["congestion_severity"]))
        for _, r in pic_df.iterrows()
    }
    monitored = set(sev_by_h3.keys())
    rows = []
    for h3, current in sev_by_h3.items():
        neighbors = [n for n in la.ring1_neighbors(h3) if n in monitored]
        neighbor_sev = [sev_by_h3.get(n) for n in neighbors]
        res = la.compute_for_cell(current, neighbor_sev, minimum_valid_neighbors=min_neighbors)
        res["h3_res10"] = h3
        rows.append(res)
    anom = pd.DataFrame(rows).set_index("h3_res10")
    out = pic_df.copy()
    for col in anom.columns:
        out[col] = out["h3_res10"].map(anom[col])
    return out


def coverage_block(citywide_h3: int) -> dict[str, Any]:
    return {
        "citywide_historical_h3_cells": int(citywide_h3),
        "live_region": "WHITEFIELD_DEMO",
        "live_citywide_claimed": False,
    }


def congestion_summary(pic_df: pd.DataFrame) -> dict[str, Any]:
    sev = pd.to_numeric(pic_df.get("congestion_severity"), errors="coerce").dropna()
    labels = pic_df.get("congestion_label")
    counts = {
        "normal_count": 0,
        "light_congestion_count": 0,
        "moderate_count": 0,
        "moderate_congestion_count": 0,
        "high_count": 0,
        "high_congestion_count": 0,
        "severe_count": 0,
        "severe_congestion_count": 0,
    }
    if labels is not None:
        vc = labels.value_counts()
        counts = {
            "normal_count": int(vc.get("NORMAL", 0)),
            "light_congestion_count": int(vc.get("LIGHT_CONGESTION", 0)),
            "moderate_count": int(vc.get("MODERATE", 0) + vc.get("MODERATE_CONGESTION", 0)),
            "moderate_congestion_count": int(vc.get("MODERATE_CONGESTION", 0)),
            "high_count": int(vc.get("HIGH", 0) + vc.get("HIGH_CONGESTION", 0)),
            "high_congestion_count": int(vc.get("HIGH_CONGESTION", 0)),
            "severe_count": int(vc.get("SEVERE", 0) + vc.get("SEVERE_CONGESTION", 0)),
            "severe_congestion_count": int(vc.get("SEVERE_CONGESTION", 0)),
        }
    return {
        "cells_with_valid_severity": int(len(sev)),
        "mean_severity": float(sev.mean()) if len(sev) else None,
        "median_severity": float(sev.median()) if len(sev) else None,
        "maximum_severity": float(sev.max()) if len(sev) else None,
        **counts,
    }


def pic_summary(pic_df: pd.DataFrame) -> dict[str, Any]:
    computed = pic_df[pic_df.get("pic_status") == "COMPUTED"] if "pic_status" in pic_df else pic_df.iloc[0:0]
    scores = pd.to_numeric(computed.get("pic_score"), errors="coerce").dropna()
    top = None
    if len(computed):
        top_row = computed.sort_values("pic_rank").iloc[0]
        top = {
            "h3_res10": top_row["h3_res10"],
            "pic_score": float(top_row["pic_score"]),
            "congestion_severity": float(top_row["congestion_severity"]),
            "normalized_propensity": float(top_row["normalized_propensity"]),
        }
    return {
        "cells_ranked": int(len(computed)),
        "maximum_pic": float(scores.max()) if len(scores) else None,
        "mean_pic": float(scores.mean()) if len(scores) else None,
        "top_h3": top,
    }


def top_n_pic(pic_df: pd.DataFrame, n: int = 5) -> list[dict[str, Any]]:
    if "pic_status" not in pic_df:
        return []
    computed = pic_df[pic_df["pic_status"] == "COMPUTED"].sort_values("pic_rank").head(n)
    out = []
    for _, r in computed.iterrows():
        out.append(
            {
                "pic_rank": int(r["pic_rank"]),
                "h3_res10": r["h3_res10"],
                "pic_score": round(float(r["pic_score"]), 6),
                "congestion_severity": round(float(r["congestion_severity"]), 6),
                "congestion_label": r.get("congestion_label"),
                "normalized_propensity": round(float(r["normalized_propensity"]), 6),
            }
        )
    return out
