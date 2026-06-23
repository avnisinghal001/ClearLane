from __future__ import annotations

import pandas as pd

from clearlane.phase2.gamma_poisson import fit_gamma_poisson, prior_sensitivity


def test_gamma_poisson_posterior_uses_count_and_device_days():
    df = pd.DataFrame({
        "h3_res10": ["a", "b", "c"],
        "citation_count_production": [10, 2, 1],
        "device_days": [5, 5, 1],
        "eligible_for_corrected_ranking": [True, True, False],
    })
    out, report = fit_gamma_poisson(df, prior_strength=2.0)
    global_rate = (10 + 2) / (5 + 5)
    expected_mean_a = ((global_rate * 2.0) + 10) / (2.0 + 5)
    assert report["global_rate_per_device_day"] == global_rate
    assert out.set_index("h3_res10").loc["a", "gp_posterior_mean"] == expected_mean_a
    assert pd.isna(out.set_index("h3_res10").loc["c", "corrected_rank"])


def test_prior_sensitivity_reports_overlap():
    df = pd.DataFrame({
        "h3_res10": ["a", "b", "c"],
        "citation_count_production": [10, 2, 1],
        "device_days": [5, 5, 5],
        "eligible_for_corrected_ranking": [True, True, True],
    })
    report = prior_sensitivity(df, [2.0, 5.0], top_k=2, base_prior_strength=2.0)
    assert report["status"] == "PASS"
    assert report["comparisons"][0]["top_k_overlap"] == 2
