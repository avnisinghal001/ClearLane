from __future__ import annotations

import pandas as pd
import pytest
import numpy as np

from clearlane.phase2.count_models import (
    build_count_model_frame,
    fit_negative_binomial_offset,
    fit_poisson_offset,
    model_comparison,
    overdispersion_report,
    validate_model_report,
)


def test_count_model_uses_log_device_days_offset_not_feature():
    df = pd.DataFrame({
        "citation_count_production": [10, 5, 3],
        "device_days": [5, 5, 2],
        "unique_devices": [3, 2, 1],
    })
    frame = build_count_model_frame(df, ["unique_devices"])
    spec = frame.spec()
    assert spec["uses_offset"] is True
    assert spec["offset_expression"] == "log(device_days)"
    assert spec["exposure_used_as_normal_feature"] is False
    assert "device_days" not in frame.x.columns


def test_count_model_rejects_exposure_as_normal_feature():
    df = pd.DataFrame({
        "citation_count_production": [10],
        "device_days": [5],
    })
    with pytest.raises(ValueError):
        build_count_model_frame(df, ["device_days"])


def test_negative_binomial_estimates_positive_alpha_and_converges():
    pytest.importorskip("statsmodels")
    rng = np.random.default_rng(42)
    n = 120
    device_days = rng.integers(1, 20, n)
    unique_devices = np.clip((device_days * rng.uniform(0.4, 1.0, n)).astype(int), 1, None)
    mu = np.exp(0.2 + 0.08 * unique_devices + np.log(device_days))
    alpha = 0.8
    y = rng.negative_binomial(1 / alpha, 1 / (1 + alpha * mu))
    df = pd.DataFrame({
        "citation_count_production": y,
        "device_days": device_days,
        "unique_devices": unique_devices,
    })
    frame = build_count_model_frame(df, ["unique_devices"])
    _, report = fit_negative_binomial_offset(frame)
    assert report["model"] == "negative_binomial"
    assert report["alpha_estimation_method"].startswith("statsmodels.discrete")
    assert report["estimated_alpha"] > 0
    assert report["alpha_is_finite"] is True
    assert report["alpha_is_positive"] is True
    assert report["offset_passed_separately"] is True
    assert report["converged"] is True
    assert validate_model_report(report) == []


def test_model_comparison_uses_llf_based_bic():
    pytest.importorskip("statsmodels")
    rng = np.random.default_rng(7)
    n = 80
    device_days = rng.integers(1, 15, n)
    unique_devices = np.clip((device_days * rng.uniform(0.3, 1.0, n)).astype(int), 1, None)
    mu = np.exp(0.1 + 0.05 * unique_devices + np.log(device_days))
    y = rng.poisson(mu)
    df = pd.DataFrame({
        "citation_count_production": y,
        "device_days": device_days,
        "unique_devices": unique_devices,
    })
    frame = build_count_model_frame(df, ["unique_devices"])
    _, poisson = fit_poisson_offset(frame)
    _, nb = fit_negative_binomial_offset(frame)
    comparison = model_comparison(poisson, nb, overdispersion_report(df))
    assert comparison["status"] in {"PASS", "FAIL"}
    assert "llf-based bic" in comparison["bic_policy"].lower()
    assert comparison["poisson_bic_llf"] is not None
    assert comparison["negative_binomial_bic_llf"] is not None


def test_model_validation_fails_invalid_alpha_and_predictions():
    report = {
        "model": "negative_binomial",
        "model_type": "negative_binomial_discrete_offset",
        "offset_passed_separately": True,
        "model_spec": {"exposure_used_as_normal_feature": False},
        "converged": True,
        "prediction_finite": False,
        "prediction_nonnegative": True,
        "alpha_is_finite": False,
        "alpha_is_positive": False,
    }
    failures = validate_model_report(report)
    assert "Negative-Binomial alpha is not finite and positive." in failures
    assert any("non-finite predictions" in failure for failure in failures)
