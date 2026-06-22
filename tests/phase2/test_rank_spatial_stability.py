from __future__ import annotations

import pandas as pd
import pytest
import numpy as np
import yaml
from pathlib import Path

from clearlane.phase2.h3_assignment import latlng_to_cell
from clearlane.phase2.spatial_weights import grid_disk
from clearlane.phase2.rank_analysis import rank_turnover
from clearlane.phase2.spatial_significance import benjamini_hochberg, classify_gistar, compute_gistar
from clearlane.phase2.spatial_weights import component_table, neighbor_report
from clearlane.phase2.stability import assign_stability_folds


def test_rank_turnover_reports_entered_and_removed_cells():
    raw = pd.DataFrame({"h3_res10": ["a", "b", "c"], "raw_rank": [1, 2, 3]})
    corrected = pd.DataFrame({"h3_res10": ["b", "c", "a"], "corrected_rank": [1, 2, 3]})
    report = rank_turnover(raw, corrected, top_k_values=[1, 2])
    assert report["comparisons"][0]["entered_after_correction"] == ["b"]
    assert report["comparisons"][0]["removed_after_correction"] == ["a"]


def test_benjamini_hochberg_and_gistar_classification():
    adjusted = benjamini_hochberg([0.001, 0.02, 0.9], alpha=0.05)
    assert bool(adjusted.loc[0, "reject"]) is True
    assert classify_gistar(3.0, adjusted.loc[0, "q_value"]) == "hotspot"
    assert classify_gistar(None, None) == "not_tested"


def test_stability_folds_are_deterministic(sample_phase2_df):
    a = assign_stability_folds(sample_phase2_df, folds=5, seed=42)
    b = assign_stability_folds(sample_phase2_df, folds=5, seed=42)
    assert list(a["stability_fold"]) == list(b["stability_fold"])


def test_spatial_components_report_islands_and_disconnected_components():
    pytest.importorskip("h3")
    a = latlng_to_cell(12.9716, 77.5946, 10)
    b = sorted(grid_disk(a, 1) - {a})[0]
    c = latlng_to_cell(13.05, 77.75, 10)
    d = sorted(grid_disk(c, 1) - {c})[0]
    island = latlng_to_cell(12.8, 77.35, 10)
    report = neighbor_report([a, b, c, d, island], minimum_present_neighbors=1)
    assert report["status"] == "WARN"
    assert report["number_of_components"] == 3
    assert report["isolated_cell_count"] == 1
    table = component_table([a, b, c, d, island], minimum_present_neighbors=1)
    assert "spatial_component_id" in table.columns


def test_gistar_does_not_fabricate_pvalues_for_isolated_or_too_small_components():
    pytest.importorskip("esda")
    df = pd.DataFrame({
        "h3_res10": ["a", "b", "island"],
        "gp_posterior_mean": [10.0, 9.0, 100.0],
        "present_neighbor_count": [1, 1, 0],
    })
    neighbors = {"a": ["b"], "b": ["a"], "island": []}
    out, report = compute_gistar(df, neighbors, minimum_component_size=3, permutations=0)
    assert report["tested_cell_count"] == 0
    assert out.set_index("h3_res10").loc["island", "spatial_test_status"] == "INSUFFICIENT_NEIGHBORS"
    assert pd.isna(out.set_index("h3_res10").loc["island", "gistar_p_value"])


def test_gistar_connected_fixture_is_reproducible():
    pytest.importorskip("esda")
    df = pd.DataFrame({
        "h3_res10": ["a", "b", "c", "d"],
        "gp_posterior_mean": [10.0, 11.0, 1.0, 1.5],
        "present_neighbor_count": [1, 2, 2, 1],
    })
    neighbors = {"a": ["b"], "b": ["a", "c"], "c": ["b", "d"], "d": ["c"]}
    a, report_a = compute_gistar(df, neighbors, minimum_component_size=3, permutations=0, seed=42)
    b, report_b = compute_gistar(df, neighbors, minimum_component_size=3, permutations=0, seed=42)
    assert report_a["tested_cell_count"] == 4
    assert list(a["gistar_z_score"]) == list(b["gistar_z_score"])
    assert report_a["permutations"] == report_b["permutations"] == 0


def test_gistar_reported_permutations_match_actual_esda_call(monkeypatch):
    pytest.importorskip("esda")
    calls = []

    class FakeGLocal:
        def __init__(self, y, w, transform, permutations, star, keep_simulations, n_jobs, seed, island_weight):
            calls.append({
                "permutations": permutations,
                "seed": seed,
                "transform": transform,
                "star": star,
                "island_weight": island_weight,
                "n": len(y),
            })
            self.Zs = np.array([2.0] * len(y))
            self.p_norm = np.array([0.5] * len(y))
            self.p_sim = np.array([0.01] * len(y))

    monkeypatch.setattr("esda.getisord.G_Local", FakeGLocal)
    config_path = Path(__file__).resolve().parents[2] / "configs" / "phase2.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    permutations = config["spatial_significance"]["permutations"]
    seed = config["spatial_significance"]["random_seed"]

    df = pd.DataFrame({
        "h3_res10": ["a", "b", "c"],
        "gp_posterior_mean": [10.0, 11.0, 2.0],
        "present_neighbor_count": [1, 2, 1],
    })
    neighbors = {"a": ["b"], "b": ["a", "c"], "c": ["b"]}
    out, report = compute_gistar(
        df,
        neighbors,
        minimum_component_size=3,
        permutations=permutations,
        seed=seed,
        weight_transform="B",
        include_self=True,
    )

    assert calls
    assert calls[0]["permutations"] == 999
    assert calls[0]["seed"] == 42
    assert report["permutations"] == calls[0]["permutations"]
    assert report["permutation_inference"] is True
    assert report["p_value_source"] == "permutation_p_sim"
    assert out["gistar_p_value"].dropna().eq(0.01).all()
