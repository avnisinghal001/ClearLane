from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd


def stability_fold(value: object, folds: int = 5, seed: int = 42) -> int:
    text = f"{seed}|{value}"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % int(folds)


def assign_stability_folds(df: pd.DataFrame, id_col: str = "record_id_normalized",
                           folds: int = 5, seed: int = 42) -> pd.DataFrame:
    if id_col not in df.columns:
        raise ValueError(f"{id_col} is required for deterministic stability folds.")
    out = df.copy()
    out["stability_fold"] = [stability_fold(v, folds=folds, seed=seed) for v in out[id_col]]
    return out


def stability_report(rank_tables: dict[str, pd.DataFrame],
                     h3_col: str = "h3_res10",
                     rank_col: str = "corrected_rank",
                     top_k_values: list[int] | None = None) -> dict[str, Any]:
    top_k_values = top_k_values or [25, 50, 100]
    rows = []
    labels = sorted(rank_tables)
    for k in top_k_values:
        sets = [
            set(rank_tables[label].dropna(subset=[rank_col]).query(f"{rank_col} <= @k")[h3_col])
            for label in labels
        ]
        intersection = set.intersection(*sets) if sets else set()
        union = set.union(*sets) if sets else set()
        rows.append({
            "top_k": int(k),
            "fold_count": len(labels),
            "intersection_count": len(intersection),
            "union_count": len(union),
            "jaccard_all_folds": len(intersection) / len(union) if union else None,
        })
    return {"status": "PASS", "folds": labels, "top_k_stability": rows}
