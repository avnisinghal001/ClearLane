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


def gamma_interval(shape: float, rate: float, confidence: float) -> tuple[float | None, float | None]:
    try:
        from scipy.stats import gamma  # type: ignore
    except ImportError:
        return None, None
    alpha = 1.0 - confidence
    return (
        float(gamma.ppf(alpha / 2.0, a=shape, scale=1.0 / rate)),
        float(gamma.ppf(1.0 - alpha / 2.0, a=shape, scale=1.0 / rate)),
    )


def fit_gamma_poisson(
    df: pd.DataFrame,
    h3_col: str = "h3_res10",
    count_col: str = "citation_count_production",
    exposure_col: str = "device_days",
    eligible_col: str = "eligible_for_corrected_ranking",
    prior_strength: float = 10.0,
    credible_interval: float = 0.95,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = [h3_col, count_col, exposure_col, eligible_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("Missing columns for Gamma-Poisson correction: " + ", ".join(missing))

    out = df.copy()
    eligible = out[eligible_col].fillna(False).astype(bool) & (out[exposure_col] > 0)
    if not eligible.any():
        raise ValueError("No exposure-eligible cells are available for Gamma-Poisson correction.")

    global_rate = float(out.loc[eligible, count_col].sum() / out.loc[eligible, exposure_col].sum())
    prior_shape = global_rate * float(prior_strength)
    prior_rate = float(prior_strength)
    out["gp_prior_shape"] = prior_shape
    out["gp_prior_rate"] = prior_rate
    out["gp_posterior_shape"] = prior_shape + out[count_col].astype(float)
    out["gp_posterior_rate"] = prior_rate + out[exposure_col].astype(float)
    out["gp_posterior_mean"] = out["gp_posterior_shape"] / out["gp_posterior_rate"]

    intervals = [
        gamma_interval(shape, rate, credible_interval)
        for shape, rate in zip(out["gp_posterior_shape"], out["gp_posterior_rate"], strict=False)
    ]
    out["gp_ci_lower"] = [lo for lo, _ in intervals]
    out["gp_ci_upper"] = [hi for _, hi in intervals]
    max_mean = float(out.loc[eligible, "gp_posterior_mean"].max()) if eligible.any() else 0.0
    out["normalized_propensity"] = out["gp_posterior_mean"] / max_mean if max_mean > 0 else 0.0

    out["corrected_rank"] = pd.NA
    eligible_sorted = out.loc[eligible].sort_values(
        ["gp_posterior_mean", exposure_col, h3_col],
        ascending=[False, False, True],
    )
    ranks = pd.Series(range(1, len(eligible_sorted) + 1), index=eligible_sorted.index)
    out.loc[eligible_sorted.index, "corrected_rank"] = ranks
    out["corrected_percentile"] = pd.NA
    if len(eligible_sorted):
        out.loc[eligible_sorted.index, "corrected_percentile"] = 1.0 - ((ranks - 1) / len(eligible_sorted))

    valid_intervals = validate_gamma_poisson_output(out, eligible_col=eligible_col)
    report = {
        "status": "PASS",
        "eligible_cell_count": int(eligible.sum()),
        "global_rate_per_device_day": global_rate,
        "prior_strength": float(prior_strength),
        "prior_shape": prior_shape,
        "prior_rate": prior_rate,
        "credible_interval": credible_interval,
        "interval_method": "scipy.stats.gamma.ppf" if out["gp_ci_lower"].notna().any() else "not_available",
        **valid_intervals,
    }
    if valid_intervals["failure_count"]:
        report["status"] = "FAIL"
    return out, report


def validate_gamma_poisson_output(df: pd.DataFrame,
                                  eligible_col: str = "eligible_for_corrected_ranking") -> dict[str, Any]:
    eligible = df[eligible_col].fillna(False).astype(bool) if eligible_col in df else pd.Series(True, index=df.index)
    checked = df.loc[eligible].copy()
    failures: list[str] = []
    if checked["gp_posterior_mean"].isna().any() or (checked["gp_posterior_mean"] < 0).any():
        failures.append("Posterior means must be finite and nonnegative for eligible cells.")
    if checked["normalized_propensity"].isna().any() or (checked["normalized_propensity"] < 0).any() or (checked["normalized_propensity"] > 1).any():
        failures.append("normalized_propensity must be in [0,1].")
    interval_cols = ["gp_ci_lower", "gp_ci_upper"]
    if checked[interval_cols].notna().all().all():
        if (checked["gp_ci_lower"] < 0).any():
            failures.append("Gamma credible interval lower bound must be >= 0.")
        if (checked["gp_ci_lower"] > checked["gp_posterior_mean"]).any():
            failures.append("Gamma credible interval lower bound exceeds posterior mean.")
        if (checked["gp_posterior_mean"] > checked["gp_ci_upper"]).any():
            failures.append("Gamma posterior mean exceeds credible interval upper bound.")
    return {
        "failure_count": len(failures),
        "failures": failures,
        "intervals_valid": len(failures) == 0,
        "normalized_propensity_min": float(checked["normalized_propensity"].min()) if len(checked) else None,
        "normalized_propensity_max": float(checked["normalized_propensity"].max()) if len(checked) else None,
    }


def gamma_poisson_spot_check(
    df: pd.DataFrame,
    sample_size: int = 10,
    seed: int = 42,
    h3_col: str = "h3_res10",
    count_col: str = "citation_count_production",
    exposure_col: str = "device_days",
    eligible_col: str = "eligible_for_corrected_ranking",
) -> dict[str, Any]:
    eligible = df[df[eligible_col].fillna(False).astype(bool)].copy()
    if eligible.empty:
        return {"status": "FAIL", "failures": ["No eligible cells for Gamma-Poisson spot check."]}
    sample = eligible.sample(n=min(sample_size, len(eligible)), random_state=seed)
    failures = []
    for _, row in sample.iterrows():
        expected_shape = row["gp_prior_shape"] + row[count_col]
        expected_rate = row["gp_prior_rate"] + row[exposure_col]
        expected_mean = expected_shape / expected_rate
        if abs(float(row["gp_posterior_shape"]) - float(expected_shape)) > 1e-9:
            failures.append(f"{row[h3_col]} posterior_shape mismatch")
        if abs(float(row["gp_posterior_rate"]) - float(expected_rate)) > 1e-9:
            failures.append(f"{row[h3_col]} posterior_rate mismatch")
        if abs(float(row["gp_posterior_mean"]) - float(expected_mean)) > 1e-9:
            failures.append(f"{row[h3_col]} posterior_mean mismatch")
    return {
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "checked_cell_count": int(len(sample)),
        "seed": int(seed),
    }


def prior_sensitivity(
    df: pd.DataFrame,
    prior_strengths: list[float],
    top_k: int = 50,
    base_prior_strength: float | None = None,
) -> dict[str, Any]:
    if not prior_strengths:
        return {"status": "PASS", "comparisons": []}
    base_strength = base_prior_strength if base_prior_strength is not None else prior_strengths[0]
    base, _ = fit_gamma_poisson(df, prior_strength=base_strength)
    base_ranks = base.set_index("h3_res10")["corrected_rank"].dropna().astype(float)
    base_top = set(base_ranks.sort_values().head(top_k).index)

    comparisons = []
    for strength in prior_strengths:
        current, _ = fit_gamma_poisson(df, prior_strength=strength)
        current_ranks = current.set_index("h3_res10")["corrected_rank"].dropna().astype(float)
        common = base_ranks.index.intersection(current_ranks.index)
        spearman = _spearman_without_scipy(base_ranks.loc[common], current_ranks.loc[common])
        current_top = set(current_ranks.sort_values().head(top_k).index)
        comparisons.append({
            "prior_strength": float(strength),
            "top_k": int(top_k),
            "top_k_overlap": len(base_top & current_top),
            "top_k_overlap_rate": len(base_top & current_top) / max(1, len(base_top)),
            "spearman_rank_correlation": spearman,
        })
    return {
        "status": "PASS",
        "base_prior_strength": float(base_strength),
        "comparisons": comparisons,
    }
