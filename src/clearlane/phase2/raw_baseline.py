from __future__ import annotations

from typing import Any

import pandas as pd


def rank_raw_hotspots(df: pd.DataFrame,
                      h3_col: str = "h3_res10",
                      count_col: str = "citation_count_production",
                      exposure_col: str = "device_days") -> pd.DataFrame:
    required = [h3_col, count_col, exposure_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("Missing columns for raw ranking: " + ", ".join(missing))

    out = df.copy()
    out["raw_rate_per_device_day"] = out[count_col] / out[exposure_col].where(out[exposure_col] > 0)
    out = out.sort_values([count_col, exposure_col, h3_col], ascending=[False, False, True]).reset_index(drop=True)
    out["raw_rank"] = range(1, len(out) + 1)
    out["raw_percentile"] = 1.0 - ((out["raw_rank"] - 1) / len(out)) if len(out) else pd.Series(dtype=float)
    rate_ranked = out.dropna(subset=["raw_rate_per_device_day"]).sort_values(
        ["raw_rate_per_device_day", count_col, h3_col],
        ascending=[False, False, True],
    )
    out["raw_rate_rank"] = pd.NA
    out.loc[rate_ranked.index, "raw_rate_rank"] = range(1, len(rate_ranked) + 1)
    return out


def concentration_report(ranked: pd.DataFrame,
                         count_col: str = "citation_count_production",
                         percentiles: list[float] | None = None) -> dict[str, Any]:
    percentiles = percentiles or [0.01, 0.05, 0.10]
    total = float(ranked[count_col].sum()) if len(ranked) else 0.0
    rows: list[dict[str, Any]] = []
    for pct in percentiles:
        n = max(1, int(round(len(ranked) * pct))) if len(ranked) else 0
        top_count = float(ranked.head(n)[count_col].sum()) if n else 0.0
        rows.append({
            "top_percentile": pct,
            "cell_count": n,
            "citation_count": top_count,
            "citation_share": float(top_count / total) if total else 0.0,
        })
    return {
        "status": "PASS",
        "total_cells": int(len(ranked)),
        "total_citations": int(total),
        "concentration": rows,
        "ranking_policy": "citation_count desc, device_days desc, h3 id asc",
    }
