from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .aggregation import aggregate_h3
from .exposure import attach_exposure, compute_exposure
from .gamma_poisson import fit_gamma_poisson


def _spearman_without_scipy(a: pd.Series, b: pd.Series) -> float | None:
    if len(a) < 2:
        return None
    ar = a.astype(float).rank(method="average")
    br = b.astype(float).rank(method="average")
    value = ar.corr(br, method="pearson")
    return float(value) if pd.notna(value) else None


def _rank_mapping(mapping: pd.DataFrame, minimum_device_days: int,
                  prior_strength: float) -> pd.DataFrame:
    aggregates = aggregate_h3(mapping)
    exposure = compute_exposure(mapping, minimum_device_days=minimum_device_days)
    hot = attach_exposure(aggregates, exposure)
    hot, _ = fit_gamma_poisson(hot, prior_strength=prior_strength)
    return hot


def monthly_stability_report(
    mapping: pd.DataFrame,
    minimum_device_days: int,
    prior_strength: float,
    top_k_values: list[int],
) -> dict[str, Any]:
    work = mapping.copy()
    work["created_month"] = pd.to_datetime(work["created_date"], errors="coerce").dt.to_period("M").astype(str)
    months = sorted(m for m in work["created_month"].dropna().unique() if m != "NaT")
    monthly_tables: dict[str, pd.DataFrame] = {}
    month_rows = []
    for month in months:
        subset = work[work["created_month"] == month].copy()
        ranked = _rank_mapping(subset, minimum_device_days, prior_strength)
        monthly_tables[month] = ranked
        month_rows.append({
            "month": month,
            "ticket_rows": int(len(subset)),
            "h3_cells": int(ranked["h3_res10"].nunique()),
            "eligible_cells": int(ranked["eligible_for_corrected_ranking"].sum()),
            "global_rate_per_device_day": float(
                ranked.loc[ranked["eligible_for_corrected_ranking"], "citation_count_production"].sum()
                / ranked.loc[ranked["eligible_for_corrected_ranking"], "device_days"].sum()
            ) if ranked["eligible_for_corrected_ranking"].any() else None,
        })

    comparisons = []
    for k in top_k_values:
        sets = []
        for month, ranked in monthly_tables.items():
            ranks = ranked.dropna(subset=["corrected_rank"]).set_index("h3_res10")["corrected_rank"].astype(int)
            top = set(ranks[ranks <= k].index)
            sets.append(top)
        intersection = set.intersection(*sets) if sets else set()
        union = set.union(*sets) if sets else set()
        comparisons.append({
            "top_k": int(k),
            "month_count": len(months),
            "intersection_count": len(intersection),
            "union_count": len(union),
            "jaccard_all_months": len(intersection) / len(union) if union else None,
        })
    return {
        "status": "PASS",
        "method": "recompute_counts_exposure_prior_and_posterior_per_month_from_ticket_mapping",
        "month_count": len(months),
        "months": month_rows,
        "top_k_stability": comparisons,
        "temporal_leakage_prevention": "Each month computes its own exposure and empirical prior from that month's ticket-level records only.",
    }


def _precision_recall_ndcg(selected: list[str], relevant: list[str],
                           relevance_scores: pd.Series) -> dict[str, float | None]:
    if not selected:
        return {"precision": None, "recall": None, "ndcg": None}
    relevant_set = set(relevant)
    hits = [1 if cell in relevant_set else 0 for cell in selected]
    precision = sum(hits) / len(selected)
    recall = sum(hits) / max(1, len(relevant_set))
    gains = np.array([float(relevance_scores.get(cell, 0.0)) for cell in selected])
    discounts = 1.0 / np.log2(np.arange(2, len(gains) + 2))
    dcg = float(np.sum(gains * discounts))
    ideal = np.sort(relevance_scores.to_numpy())[::-1][:len(gains)]
    idcg = float(np.sum(ideal * discounts[:len(ideal)]))
    return {"precision": precision, "recall": recall, "ndcg": dcg / idcg if idcg else None}


def chronological_holdout_validation(
    mapping: pd.DataFrame,
    minimum_device_days: int,
    prior_strength: float,
    top_k_values: list[int],
    train_fraction: float = 0.70,
) -> dict[str, Any]:
    work = mapping.copy()
    work["created_date_parsed"] = pd.to_datetime(work["created_date"], errors="coerce")
    dates = sorted(work["created_date_parsed"].dropna().dt.date.unique())
    if len(dates) < 2:
        return {"status": "FAIL", "reason": "Not enough dates for chronological holdout."}
    split_idx = max(1, min(len(dates) - 1, int(len(dates) * train_fraction)))
    split_date = dates[split_idx]
    train = work[work["created_date_parsed"].dt.date < split_date].drop(columns=["created_date_parsed"]).copy()
    test = work[work["created_date_parsed"].dt.date >= split_date].drop(columns=["created_date_parsed"]).copy()
    train_hot = _rank_mapping(train, minimum_device_days, prior_strength)
    test_hot = _rank_mapping(test, minimum_device_days, prior_strength)

    train_ranks = train_hot.dropna(subset=["corrected_rank"]).set_index("h3_res10")["corrected_rank"].astype(int)
    test_counts = test_hot.set_index("h3_res10")["citation_count_production"].astype(float)
    common = train_ranks.index.intersection(test_counts.index)
    spearman = _spearman_without_scipy(train_ranks.loc[common], -test_counts.loc[common]) if len(common) > 1 else None
    rows = []
    for k in top_k_values:
        selected = list(train_ranks.sort_values().head(k).index)
        relevant = list(test_counts.sort_values(ascending=False).head(k).index)
        metrics = _precision_recall_ndcg(selected, relevant, test_counts)
        rows.append({"top_k": int(k), **metrics})
    return {
        "status": "PASS",
        "method": "chronological_ticket_level_split",
        "train_fraction": float(train_fraction),
        "split_date": split_date.isoformat(),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_date_max_exclusive": split_date.isoformat(),
        "test_date_min_inclusive": split_date.isoformat(),
        "spearman_train_rank_vs_later_activity": spearman,
        "top_k_metrics": rows,
        "coverage": len(common) / max(1, len(train_ranks)),
        "temporal_leakage_prevention": "Priors and rankings are fitted on the early period before comparing with later observed activity.",
    }
