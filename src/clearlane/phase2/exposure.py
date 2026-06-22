from __future__ import annotations

from typing import Any

import pandas as pd


def _truthy(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.fillna(False).map(lambda x: str(x).strip().lower() in {"true", "1", "yes"})


def compute_exposure(mapping: pd.DataFrame, h3_col: str = "h3_res10",
                     minimum_device_days: int = 5) -> pd.DataFrame:
    required = [h3_col, "device_id", "created_by_id", "created_date"]
    missing = [c for c in required if c not in mapping.columns]
    if missing:
        raise ValueError("Missing columns for exposure calculation: " + ", ".join(missing))

    work = mapping.copy()
    if "record_usable_for_exposure_analysis" in work.columns:
        usable = _truthy(work["record_usable_for_exposure_analysis"])
        work = work[usable].copy()
    work["created_date"] = pd.to_datetime(work["created_date"], errors="coerce").dt.date.astype("string")

    device_days = (
        work[[h3_col, "device_id", "created_date"]]
        .dropna()
        .drop_duplicates()
        .groupby(h3_col)
        .size()
        .rename("device_days")
    )
    officer_days = (
        work[[h3_col, "created_by_id", "created_date"]]
        .dropna()
        .drop_duplicates()
        .groupby(h3_col)
        .size()
        .rename("officer_days")
    )
    unique_devices = work.groupby(h3_col)["device_id"].nunique(dropna=True).rename("unique_devices_exposure")
    unique_officers = work.groupby(h3_col)["created_by_id"].nunique(dropna=True).rename("unique_officers_exposure")
    active_dates = work.groupby(h3_col)["created_date"].nunique(dropna=True).rename("active_dates")
    citation_count = work.groupby(h3_col).size().rename("citation_count_exposure_rows")

    out = pd.concat([device_days, officer_days, unique_devices, unique_officers, active_dates, citation_count], axis=1).fillna(0)
    for col in ["device_days", "officer_days", "unique_devices_exposure", "unique_officers_exposure", "active_dates", "citation_count_exposure_rows"]:
        out[col] = out[col].astype(int)
    out["eligible_for_corrected_ranking"] = out["device_days"] >= int(minimum_device_days)
    out["minimum_device_days"] = int(minimum_device_days)
    return out.reset_index()


def exposure_invariant_report(exposure: pd.DataFrame,
                              aggregates: pd.DataFrame,
                              h3_col: str = "h3_res10") -> dict[str, Any]:
    merged = exposure.merge(aggregates[[h3_col, "citation_count_production"]], on=h3_col, how="left")
    failures: list[str] = []
    if (merged["device_days"] <= 0).any():
        failures.append("device_days must be positive for every exposure row.")
    if (merged["device_days"] > merged["citation_count_production"]).any():
        failures.append("device_days cannot exceed citation_count_production.")
    if (merged["officer_days"] > merged["citation_count_production"]).any():
        failures.append("officer_days cannot exceed citation_count_production.")
    if (merged["unique_devices_exposure"] > merged["device_days"]).any():
        failures.append("unique_devices_exposure cannot exceed device_days.")
    if (merged["unique_officers_exposure"] > merged["officer_days"]).any():
        failures.append("unique_officers_exposure cannot exceed officer_days.")
    if "active_dates" in merged and (merged["active_dates"] > merged["device_days"]).any():
        failures.append("active_dates cannot exceed device_days.")
    return {
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "failure_count": len(failures),
        "cell_count": int(len(exposure)),
        "eligible_cell_count": int(exposure["eligible_for_corrected_ranking"].sum()),
        "ineligible_cell_count": int((~exposure["eligible_for_corrected_ranking"]).sum()),
        "invariants_checked": [
            "device_days > 0 for exposure rows",
            "device_days <= citation_count",
            "officer_days <= citation_count",
            "unique_devices <= device_days",
            "unique_officers <= officer_days",
            "active_dates <= device_days",
        ],
    }


def attach_exposure(aggregates: pd.DataFrame, exposure: pd.DataFrame,
                    h3_col: str = "h3_res10") -> pd.DataFrame:
    merged = aggregates.merge(exposure, on=h3_col, how="left")
    numeric = ["device_days", "officer_days", "unique_devices_exposure", "unique_officers_exposure", "active_dates"]
    for col in numeric:
        if col in merged:
            merged[col] = merged[col].fillna(0).astype(int)
    if "eligible_for_corrected_ranking" in merged:
        merged["eligible_for_corrected_ranking"] = merged["eligible_for_corrected_ranking"].fillna(False).astype(bool)
    return merged


def independent_exposure_check(mapping: pd.DataFrame, exposure: pd.DataFrame,
                               h3_col: str = "h3_res10",
                               minimum_device_days: int = 5) -> dict[str, Any]:
    recomputed = compute_exposure(mapping, h3_col=h3_col, minimum_device_days=minimum_device_days)
    cols = [
        h3_col,
        "device_days",
        "officer_days",
        "unique_devices_exposure",
        "unique_officers_exposure",
        "active_dates",
        "eligible_for_corrected_ranking",
    ]
    left = recomputed[cols].sort_values(h3_col).reset_index(drop=True)
    right = exposure[cols].sort_values(h3_col).reset_index(drop=True)
    failures: list[str] = []
    if len(left) != len(right):
        failures.append(f"Exposure row count mismatch: recomputed={len(left)}, output={len(right)}")
    else:
        for col in cols:
            if not left[col].equals(right[col]):
                failures.append(f"Exposure column mismatch: {col}")
    return {
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "failure_count": len(failures),
        "checked_columns": cols,
        "minimum_device_days": int(minimum_device_days),
    }
