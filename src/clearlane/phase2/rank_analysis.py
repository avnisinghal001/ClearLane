from __future__ import annotations

from typing import Any

import pandas as pd


def _spearman_without_scipy(a: pd.Series, b: pd.Series) -> float | None:
    if len(a) < 2:
        return None
    ar = a.astype(float).rank(method="average")
    br = b.astype(float).rank(method="average")
    value = ar.corr(br, method="pearson")
    return float(value) if pd.notna(value) else None


def rank_turnover(raw_ranked: pd.DataFrame, corrected_ranked: pd.DataFrame,
                  h3_col: str = "h3_res10", top_k_values: list[int] | None = None) -> dict[str, Any]:
    top_k_values = top_k_values or [10, 25, 50, 100]
    raw = raw_ranked.dropna(subset=["raw_rank"]).set_index(h3_col)["raw_rank"].astype(int)
    corrected = corrected_ranked.dropna(subset=["corrected_rank"]).set_index(h3_col)["corrected_rank"].astype(int)
    rows = []
    for k in top_k_values:
        raw_top = set(raw[raw <= k].index)
        corrected_top = set(corrected[corrected <= k].index)
        overlap = len(raw_top & corrected_top)
        union = len(raw_top | corrected_top)
        rows.append({
            "top_k": int(k),
            "raw_top_k_count": len(raw_top),
            "corrected_top_k_count": len(corrected_top),
            "overlap_count": overlap,
            "overlap_percentage": 100.0 * overlap / max(1, int(k)),
            "turnover_count": int(k) - overlap,
            "turnover_percentage": 100.0 * (1.0 - (overlap / max(1, int(k)))),
            "jaccard_similarity": overlap / union if union else None,
            "entered_after_correction": sorted(corrected_top - raw_top),
            "removed_after_correction": sorted(raw_top - corrected_top),
        })
    common = raw.index.intersection(corrected.index)
    return {
        "status": "PASS",
        "comparisons": rows,
        "spearman_raw_vs_corrected": _spearman_without_scipy(raw.loc[common], corrected.loc[common]),
    }


def rank_by_column(df: pd.DataFrame, score_col: str, rank_col: str,
                   h3_col: str = "h3_res10", ascending: bool = False) -> pd.DataFrame:
    required = [h3_col, score_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("Missing columns for ranking: " + ", ".join(missing))
    out = df.copy()
    ranked = out.dropna(subset=[score_col]).sort_values([score_col, h3_col], ascending=[ascending, True])
    out[rank_col] = pd.NA
    out.loc[ranked.index, rank_col] = range(1, len(ranked) + 1)
    return out
