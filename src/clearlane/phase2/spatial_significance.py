from __future__ import annotations

from typing import Any
import warnings

import numpy as np
import pandas as pd

from .spatial_weights import connected_components


def benjamini_hochberg(p_values: list[float | None] | pd.Series,
                       alpha: float = 0.05) -> pd.DataFrame:
    raw = pd.Series(p_values, dtype="float64")
    valid = raw.dropna()
    adjusted = pd.Series(np.nan, index=raw.index, dtype="float64")
    rejected = pd.Series(False, index=raw.index, dtype="bool")
    if valid.empty:
        return pd.DataFrame({"p_value": raw, "q_value": adjusted, "reject": rejected})

    order = valid.sort_values().index
    m = float(len(valid))
    running = 1.0
    for rank, idx in reversed(list(enumerate(order, start=1))):
        q = min(running, float(valid.loc[idx]) * m / rank)
        running = q
        adjusted.loc[idx] = min(q, 1.0)
    rejected.loc[adjusted.index] = adjusted.fillna(1.0) <= alpha
    return pd.DataFrame({"p_value": raw, "q_value": adjusted, "reject": rejected})


def hotspot_label(z_score: float | None, q_value: float | None) -> str:
    if z_score is None or q_value is None or pd.isna(z_score) or pd.isna(q_value):
        return "NOT_TESTED"
    if z_score <= 0:
        return "NOT_HOT"
    if q_value <= 0.01:
        return "HOT_99"
    if q_value <= 0.05:
        return "HOT_95"
    if q_value <= 0.10:
        return "HOT_90"
    return "NOT_SIGNIFICANT"


def classify_gistar(z_score: float | None, q_value: float | None,
                    alpha: float = 0.05) -> str:
    if z_score is None or q_value is None or pd.isna(z_score) or pd.isna(q_value):
        return "not_tested"
    if q_value > alpha:
        return "not_significant"
    return "hotspot" if z_score > 0 else "coldspot"


def _component_weights(component: list[str],
                       neighbor_map: dict[str, list[str]]) -> tuple[Any, list[str]]:
    from libpysal.weights import W  # type: ignore

    index = {cell: i for i, cell in enumerate(component)}
    neighbors = {
        index[cell]: [index[n] for n in neighbor_map[cell] if n in index]
        for cell in component
    }
    weights = {i: [1.0] * len(ns) for i, ns in neighbors.items()}
    return W(neighbors, weights, silence_warnings=True), component


def compute_gistar(
    df: pd.DataFrame,
    neighbor_map: dict[str, list[str]],
    h3_col: str = "h3_res10",
    value_col: str = "gp_posterior_mean",
    alpha: float = 0.05,
    minimum_component_size: int = 3,
    permutations: int = 0,
    seed: int = 42,
    weight_transform: str = "B",
    include_self: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    try:
        from esda.getisord import G_Local  # type: ignore
    except ImportError as exc:
        raise RuntimeError("esda and libpysal are required for Gi* spatial significance.") from exc

    result = df.copy()
    for col in ["gistar_z_score", "gistar_p_value", "gistar_q_value"]:
        result[col] = np.nan
    result["gistar_class"] = "not_tested"
    result["spatial_hotspot_label"] = "NOT_TESTED"
    if "spatial_test_status" not in result.columns:
        result["spatial_test_status"] = "PENDING"
    if "present_neighbor_count" not in result.columns:
        result["present_neighbor_count"] = result[h3_col].map(lambda cell: len(neighbor_map.get(str(cell), [])))

    value_by_cell = result.set_index(h3_col)[value_col].dropna().astype(float)
    components = connected_components(neighbor_map)
    component_rows: list[dict[str, Any]] = []
    tested_parts: list[pd.DataFrame] = []
    captured_warnings: list[str] = []
    configured_permutations = int(permutations)
    p_value_source = "permutation_p_sim" if configured_permutations > 0 else "analytical_p_norm"

    for component_id, component in enumerate(components, start=1):
        present_component = [cell for cell in component if cell in value_by_cell.index]
        if not present_component:
            continue
        if len(present_component) < minimum_component_size:
            result.loc[result[h3_col].isin(present_component), "spatial_test_status"] = "COMPONENT_TOO_SMALL"
            component_rows.append({
                "spatial_component_id": component_id,
                "component_size": len(present_component),
                "status": "COMPONENT_TOO_SMALL",
            })
            continue
        valid_cells = [cell for cell in present_component if any(n in present_component for n in neighbor_map.get(cell, []))]
        invalid_cells = sorted(set(present_component) - set(valid_cells))
        if invalid_cells:
            result.loc[result[h3_col].isin(invalid_cells), "spatial_test_status"] = "INSUFFICIENT_NEIGHBORS"
        if len(valid_cells) < minimum_component_size:
            result.loc[result[h3_col].isin(valid_cells), "spatial_test_status"] = "COMPONENT_TOO_SMALL"
            component_rows.append({
                "spatial_component_id": component_id,
                "component_size": len(present_component),
                "status": "COMPONENT_TOO_SMALL",
            })
            continue

        w, ordered_cells = _component_weights(valid_cells, neighbor_map)
        values = value_by_cell.loc[ordered_cells].to_numpy()
        if len(np.unique(values)) < 2 or float(np.nanstd(values)) == 0.0:
            result.loc[result[h3_col].isin(ordered_cells), "spatial_test_status"] = "COMPONENT_CONSTANT_VALUE"
            component_rows.append({
                "spatial_component_id": component_id,
                "component_size": len(ordered_cells),
                "status": "COMPONENT_CONSTANT_VALUE",
            })
            continue
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                glocal = G_Local(
                    values,
                    w,
                    transform=weight_transform,
                    permutations=configured_permutations,
                    star=include_self,
                    keep_simulations=False,
                    n_jobs=1,
                    seed=int(seed),
                    island_weight=0,
                )
            component_warnings = [str(w.message) for w in caught]
            tested = pd.DataFrame({
                h3_col: ordered_cells,
                "gistar_z_score": glocal.Zs,
                "gistar_p_value": glocal.p_norm if configured_permutations == 0 else glocal.p_sim,
            })
            finite = np.isfinite(tested["gistar_z_score"].astype(float)) & np.isfinite(tested["gistar_p_value"].astype(float))
            if not bool(finite.all()):
                failed_cells = tested.loc[~finite, h3_col].tolist()
                result.loc[result[h3_col].isin(failed_cells), "spatial_test_status"] = "SPATIAL_STAT_FAILED"
                tested = tested.loc[finite].copy()
            if tested.empty:
                component_rows.append({
                    "spatial_component_id": component_id,
                    "component_size": len(ordered_cells),
                    "status": "SPATIAL_STAT_FAILED",
                    "captured_warnings": component_warnings,
                })
                continue
            if component_warnings:
                captured_warnings.extend(component_warnings)
            tested_parts.append(tested)
            result.loc[result[h3_col].isin(tested[h3_col]), "spatial_test_status"] = "TESTED"
            component_rows.append({
                "spatial_component_id": component_id,
                "component_size": len(tested),
                "status": "TESTED" if len(tested) == len(ordered_cells) else "PARTIALLY_TESTED",
                "failed_cell_count": int(len(ordered_cells) - len(tested)),
                "permutations_used": configured_permutations,
                "p_value_source": p_value_source,
            })
        except Exception as exc:
            result.loc[result[h3_col].isin(valid_cells), "spatial_test_status"] = "SPATIAL_STAT_FAILED"
            component_rows.append({
                "spatial_component_id": component_id,
                "component_size": len(valid_cells),
                "status": "SPATIAL_STAT_FAILED",
                "error": f"{type(exc).__name__}: {exc}",
            })

    tested_all = pd.concat(tested_parts, ignore_index=True) if tested_parts else pd.DataFrame(columns=[h3_col, "gistar_z_score", "gistar_p_value"])
    if not tested_all.empty:
        adjusted = benjamini_hochberg(tested_all["gistar_p_value"], alpha=alpha)
        tested_all["gistar_q_value"] = adjusted["q_value"].to_numpy()
        tested_all["gistar_class"] = [
            classify_gistar(z, q, alpha)
            for z, q in zip(tested_all["gistar_z_score"], tested_all["gistar_q_value"], strict=False)
        ]
        tested_all["spatial_hotspot_label"] = [
            hotspot_label(z, q)
            for z, q in zip(tested_all["gistar_z_score"], tested_all["gistar_q_value"], strict=False)
        ]
        result = result.drop(columns=["gistar_z_score", "gistar_p_value", "gistar_q_value", "gistar_class", "spatial_hotspot_label"])
        result = result.merge(tested_all, on=h3_col, how="left")
        result["gistar_class"] = result["gistar_class"].fillna("not_tested")
        result["spatial_hotspot_label"] = result["spatial_hotspot_label"].fillna("NOT_TESTED")

    result.loc[result["present_neighbor_count"].fillna(0) <= 0, "spatial_test_status"] = "INSUFFICIENT_NEIGHBORS"
    report_warnings = []
    if len(components) > 1:
        report_warnings.append("SPATIAL_GRAPH_DISCONNECTED")
    if (result["spatial_test_status"] == "INSUFFICIENT_NEIGHBORS").any():
        report_warnings.append("SPATIAL_ISLANDS_PRESENT")
    label_counts = result["spatial_hotspot_label"].value_counts(dropna=False).to_dict()
    report = {
        "status": "WARN" if report_warnings else "PASS",
        "method": "per_connected_component_gistar",
        "tested_cell_count": int((result["spatial_test_status"] == "TESTED").sum()),
        "not_tested_cell_count": int((result["spatial_test_status"] != "TESTED").sum()),
        "component_count": len(components),
        "minimum_component_size": int(minimum_component_size),
        "alpha": alpha,
        "p_adjustment": "benjamini_hochberg_valid_tested_cells_only",
        "raw_and_adjusted_p_values_retained": True,
        "weight_transform": weight_transform,
        "include_self_for_gistar": include_self,
        "permutations": configured_permutations,
        "permutation_inference": configured_permutations > 0,
        "p_value_source": p_value_source,
        "method_detail": (
            "Getis-Ord Gi* is computed separately within each valid connected component. "
            "Permutation p-values from esda.G_Local.p_sim are used when permutations > 0; "
            "analytical normal p-values are used only when permutations == 0."
        ),
        "random_seed": int(seed),
        "island_weight": 0,
        "no_fake_p_values_for_isolated_cells": True,
        "component_results": component_rows,
        "hotspot_label_counts": {str(k): int(v) for k, v in label_counts.items()},
        "captured_library_warnings": captured_warnings,
        "warnings": report_warnings,
    }
    return result, report


def local_moran_disabled_report(enabled: bool = False) -> dict[str, Any]:
    return {
        "status": "NOT_APPLICABLE" if not enabled else "MISSING",
        "enabled": bool(enabled),
        "reason": "Local Moran's I is disabled in configs/phase2.yaml." if not enabled else "Local Moran's I was enabled but not run.",
    }
