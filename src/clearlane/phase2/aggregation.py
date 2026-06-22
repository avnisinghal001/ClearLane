from __future__ import annotations

import math
from typing import Any

import pandas as pd


def mode_or_null(series: pd.Series) -> Any:
    clean = series.dropna()
    if clean.empty:
        return None
    counts = clean.astype(str).value_counts()
    return counts.sort_values(ascending=False).index[0]


def entropy(series: pd.Series) -> float:
    clean = series.dropna().astype(str)
    if clean.empty:
        return 0.0
    probs = clean.value_counts(normalize=True)
    return float(-(probs * probs.map(lambda p: math.log(p, 2))).sum())


def aggregate_h3(mapping: pd.DataFrame, h3_col: str = "h3_res10") -> pd.DataFrame:
    if h3_col not in mapping.columns:
        raise ValueError(f"{h3_col} is required for H3 aggregation.")

    rows = []
    for cell, group in mapping.groupby(h3_col, dropna=False):
        created_dates = pd.to_datetime(group["created_date"], errors="coerce") if "created_date" in group else pd.Series(dtype="datetime64[ns]")
        count = int(len(group))
        approved = int(group["is_approved"].fillna(False).astype(bool).sum()) if "is_approved" in group else 0
        rejected = int(group["is_rejected"].fillna(False).astype(bool).sum()) if "is_rejected" in group else 0
        quality_weighted_count = None
        if "quality_weight_candidate" in group:
            quality_weighted_count = float(pd.to_numeric(group["quality_weight_candidate"], errors="coerce").fillna(1.0).sum())
        rows.append({
            h3_col: cell,
            "citation_count": count,
            "citation_count_production": count,
            "quality_weighted_citation_count": quality_weighted_count,
            "first_created_date": created_dates.min().date().isoformat() if not created_dates.dropna().empty else None,
            "last_created_date": created_dates.max().date().isoformat() if not created_dates.dropna().empty else None,
            "unique_devices": int(group["device_id"].nunique(dropna=True)) if "device_id" in group else 0,
            "unique_officers": int(group["created_by_id"].nunique(dropna=True)) if "created_by_id" in group else 0,
            "unique_vehicles": int(group["vehicle_number_normalized"].nunique(dropna=True)) if "vehicle_number_normalized" in group else 0,
            "approved_count": approved,
            "rejected_count": rejected,
            "approval_rate": float(approved / count) if count else 0.0,
            "rejection_rate": float(rejected / count) if count else 0.0,
            "mode_police_station": mode_or_null(group["police_station_normalized"]) if "police_station_normalized" in group else None,
            "mode_junction": mode_or_null(group["junction_name_normalized"]) if "junction_name_normalized" in group else None,
            "mode_violation_label": mode_or_null(group["primary_violation_label"]) if "primary_violation_label" in group else None,
            "mode_vehicle_type": mode_or_null(group["vehicle_type_normalized"]) if "vehicle_type_normalized" in group else None,
            "violation_label_entropy": entropy(group["primary_violation_label"]) if "primary_violation_label" in group else 0.0,
            "vehicle_type_entropy": entropy(group["vehicle_type_normalized"]) if "vehicle_type_normalized" in group else 0.0,
        })
    return pd.DataFrame(rows)


def count_distribution_report(aggregates: pd.DataFrame,
                              count_col: str = "citation_count_production",
                              population: str = "production_observed_h3_cells") -> dict[str, Any]:
    counts = aggregates[count_col].astype(float)
    mean = float(counts.mean()) if len(counts) else 0.0
    variance = float(counts.var(ddof=1)) if len(counts) > 1 else 0.0
    quantiles = counts.quantile([0.5, 0.75, 0.9, 0.95, 0.99]).to_dict() if len(counts) else {}
    return {
        "status": "PASS",
        "population": population,
        "cell_count": int(len(counts)),
        "mean_count": mean,
        "variance_count": variance,
        "variance_to_mean_ratio": float(variance / mean) if mean else None,
        "median_count": float(counts.median()) if len(counts) else 0.0,
        "stddev_count": float(counts.std(ddof=1)) if len(counts) > 1 else 0.0,
        "percentiles": {str(k): float(v) for k, v in quantiles.items()},
        "maximum_count": float(counts.max()) if len(counts) else 0.0,
        "positive_observation_limitation": (
            "Input contains observed citation locations only; zero-citation H3 cells "
            "outside the observed support are not inferred."
        ),
    }
