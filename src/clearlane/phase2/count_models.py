from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CountModelFrame:
    y: pd.Series
    x: pd.DataFrame
    offset: pd.Series
    feature_columns: list[str]
    count_col: str
    exposure_col: str

    def spec(self) -> dict[str, Any]:
        return {
            "count_col": self.count_col,
            "exposure_col": self.exposure_col,
            "feature_columns": self.feature_columns,
            "uses_offset": True,
            "offset_expression": f"log({self.exposure_col})",
            "exposure_used_as_normal_feature": self.exposure_col in self.feature_columns,
            "log_exposure_used_as_normal_feature": f"log_{self.exposure_col}" in self.feature_columns,
        }


def overdispersion_report(df: pd.DataFrame,
                          count_col: str = "citation_count_production") -> dict[str, Any]:
    counts = df[count_col].astype(float)
    quantiles = counts.quantile([0.5, 0.75, 0.9, 0.95, 0.99]).to_dict() if len(counts) else {}
    mean = float(counts.mean()) if len(counts) else 0.0
    variance = float(counts.var(ddof=1)) if len(counts) > 1 else 0.0
    return {
        "status": "PASS",
        "population": "exposure_eligible_cells",
        "count_col": count_col,
        "cell_count": int(len(counts)),
        "mean": mean,
        "variance": variance,
        "variance_to_mean_ratio": float(variance / mean) if mean else None,
        "median": float(counts.median()) if len(counts) else 0.0,
        "stddev": float(counts.std(ddof=1)) if len(counts) > 1 else 0.0,
        "percentiles": {str(k): float(v) for k, v in quantiles.items()},
        "maximum": float(counts.max()) if len(counts) else 0.0,
        "overdispersed_relative_to_poisson": bool(variance > mean) if mean else None,
    }


def build_count_model_frame(
    df: pd.DataFrame,
    feature_columns: list[str],
    count_col: str = "citation_count_production",
    exposure_col: str = "device_days",
) -> CountModelFrame:
    required = [count_col, exposure_col, *feature_columns]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("Missing columns for count model: " + ", ".join(missing))
    if exposure_col in feature_columns or f"log_{exposure_col}" in feature_columns:
        raise ValueError("Exposure must be supplied as an offset, not as a normal feature.")

    work = df[df[exposure_col].astype(float) > 0].copy()
    y = work[count_col].astype(float)
    x = work[feature_columns].astype(float).copy()
    x.insert(0, "intercept", 1.0)
    offset = pd.Series(np.log(work[exposure_col].astype(float)), index=work.index, name=f"log_{exposure_col}")
    return CountModelFrame(
        y=y,
        x=x,
        offset=offset,
        feature_columns=feature_columns,
        count_col=count_col,
        exposure_col=exposure_col,
    )


def _spearman_without_scipy(a: pd.Series, b: pd.Series) -> float | None:
    if len(a) < 2:
        return None
    ar = a.astype(float).rank(method="average")
    br = b.astype(float).rank(method="average")
    value = ar.corr(br, method="pearson")
    return float(value) if pd.notna(value) else None


def _llf_bic(llf: float, k_params: int, nobs: int) -> float | None:
    if not np.isfinite(llf) or nobs <= 0:
        return None
    return float(-2.0 * llf + k_params * np.log(nobs))


def _poisson_deviance(y: pd.Series, mu: np.ndarray) -> float:
    y_arr = y.astype(float).to_numpy()
    mu_arr = np.clip(np.asarray(mu, dtype=float), 1e-12, None)
    terms = np.empty_like(mu_arr, dtype=float)
    positive = y_arr > 0
    terms[positive] = y_arr[positive] * np.log(y_arr[positive] / mu_arr[positive]) - (y_arr[positive] - mu_arr[positive])
    terms[~positive] = mu_arr[~positive]
    return float(2.0 * np.sum(terms))


def _predict_counts(result: Any, frame: CountModelFrame, model_type: str) -> np.ndarray:
    if model_type == "poisson_glm_offset":
        pred = result.predict(frame.x, offset=frame.offset)
    else:
        pred = result.predict(exog=frame.x, offset=frame.offset)
    return np.asarray(pred, dtype=float)


def _converged(result: Any) -> bool:
    if hasattr(result, "converged"):
        return bool(result.converged)
    retvals = getattr(result, "mle_retvals", {}) or {}
    if "converged" in retvals:
        return bool(retvals["converged"])
    return True


def _iterations(result: Any) -> int | None:
    retvals = getattr(result, "mle_retvals", {}) or {}
    for key in ("iterations", "fcalls", "gcalls"):
        if key in retvals and retvals[key] is not None:
            return int(retvals[key])
    fit_history = getattr(result, "fit_history", {}) or {}
    if "iteration" in fit_history:
        return int(fit_history["iteration"])
    return None


def _model_summary(
    result: Any,
    model_type: str,
    frame: CountModelFrame,
    captured_warnings: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pred_counts = _predict_counts(result, frame, model_type)
    exposure = np.exp(frame.offset.astype(float).to_numpy())
    pred_rates = pred_counts / exposure
    observed_rates = frame.y.astype(float).to_numpy() / exposure
    finite_predictions = bool(np.isfinite(pred_counts).all() and np.isfinite(pred_rates).all())
    nonnegative_predictions = bool((pred_counts >= 0).all() and (pred_rates >= 0).all())
    nobs = int(len(frame.y))
    llf = float(getattr(result, "llf", np.nan))
    k_params = int(len(getattr(result, "params", [])))
    converged = _converged(result)
    status = "PASS" if converged and finite_predictions and nonnegative_predictions else "FAIL"
    report = {
        "status": status,
        "model_type": model_type,
        "nobs": nobs,
        "log_likelihood": llf,
        "aic": float(result.aic) if getattr(result, "aic", None) is not None else None,
        "bic_llf": _llf_bic(llf, k_params, nobs),
        "bic_formula": "-2 * log_likelihood + k_params * log(nobs)",
        "deviance": _poisson_deviance(frame.y, pred_counts),
        "deviance_formula": "2 * sum(y * log(y / predicted_count) - (y - predicted_count)); zero-count term uses predicted_count",
        "pearson_dispersion": float(np.sum(((frame.y.astype(float).to_numpy() - pred_counts) ** 2) / np.clip(pred_counts, 1e-12, None)) / max(nobs - k_params, 1)),
        "mae": float(np.mean(np.abs(frame.y.astype(float).to_numpy() - pred_counts))),
        "rmse": float(np.sqrt(np.mean((frame.y.astype(float).to_numpy() - pred_counts) ** 2))),
        "spearman_observed_vs_predicted_rate": _spearman_without_scipy(pd.Series(observed_rates), pd.Series(pred_rates)),
        "converged": converged,
        "iterations": _iterations(result),
        "prediction_finite": finite_predictions,
        "prediction_nonnegative": nonnegative_predictions,
        "predicted_count_min": float(np.min(pred_counts)) if len(pred_counts) else None,
        "predicted_rate_min": float(np.min(pred_rates)) if len(pred_rates) else None,
        "params": {str(k): float(v) for k, v in result.params.items()},
        "model_spec": frame.spec(),
        "offset_column": frame.exposure_col,
        "offset_passed_separately": True,
        "warnings": captured_warnings or [],
    }
    if extra:
        report.update(extra)
    return report


def validate_model_report(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if not report.get("offset_passed_separately"):
        failures.append(f"{report.get('model_type')} did not pass exposure as a separate offset.")
    if report.get("model_spec", {}).get("exposure_used_as_normal_feature"):
        failures.append(f"{report.get('model_type')} used exposure as a normal feature.")
    if not report.get("converged", False):
        failures.append(f"{report.get('model_type')} did not converge.")
    if not report.get("prediction_finite", False):
        failures.append(f"{report.get('model_type')} produced non-finite predictions.")
    if not report.get("prediction_nonnegative", False):
        failures.append(f"{report.get('model_type')} produced negative predictions.")
    if report.get("model") == "negative_binomial":
        if not report.get("alpha_is_finite") or not report.get("alpha_is_positive"):
            failures.append("Negative-Binomial alpha is not finite and positive.")
    return failures


def fit_poisson_offset(frame: CountModelFrame) -> tuple[Any, dict[str, Any]]:
    try:
        import statsmodels.api as sm  # type: ignore
    except ImportError as exc:
        raise RuntimeError("statsmodels is required to fit the Phase 2 Poisson model.") from exc
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = sm.GLM(frame.y, frame.x, family=sm.families.Poisson(), offset=frame.offset)
        result = model.fit()
    return result, _model_summary(
        result,
        "poisson_glm_offset",
        frame,
        [str(w.message) for w in caught],
        {"model": "poisson", "parameterization": "poisson_log_link"},
    )


def fit_negative_binomial_offset(frame: CountModelFrame, maxiter: int = 200) -> tuple[Any, dict[str, Any]]:
    try:
        from statsmodels.discrete.discrete_model import NegativeBinomial  # type: ignore
    except ImportError as exc:
        raise RuntimeError("statsmodels is required to fit the Phase 2 negative-binomial model.") from exc
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = NegativeBinomial(frame.y, frame.x, offset=frame.offset, loglike_method="nb2")
        result = model.fit(method="bfgs", maxiter=maxiter, disp=0)

    alpha = float(result.params.get("alpha", np.nan))
    alpha_is_finite = bool(np.isfinite(alpha))
    alpha_is_positive = bool(alpha > 0)
    extra = {
        "model": "negative_binomial",
        "parameterization": "NB2 variance = mu + alpha * mu^2",
        "alpha_estimation_method": "statsmodels.discrete.discrete_model.NegativeBinomial maximum likelihood with offset",
        "estimated_alpha": alpha,
        "alpha_is_finite": alpha_is_finite,
        "alpha_is_positive": alpha_is_positive,
    }
    report = _model_summary(
        result,
        "negative_binomial_discrete_offset",
        frame,
        [str(w.message) for w in caught],
        extra,
    )
    if not alpha_is_finite or not alpha_is_positive:
        report["status"] = "FAIL"
        report["warnings"].append("NEGATIVE_BINOMIAL_ALPHA_INVALID")
    if not report["converged"]:
        report["warnings"].append("NEGATIVE_BINOMIAL_NOT_CONVERGED")
    return result, report


def model_comparison(poisson_report: dict[str, Any],
                     nb_report: dict[str, Any],
                     dispersion_report: dict[str, Any]) -> dict[str, Any]:
    poisson_aic = poisson_report.get("aic")
    nb_aic = nb_report.get("aic")
    poisson_bic = poisson_report.get("bic_llf")
    nb_bic = nb_report.get("bic_llf")
    if poisson_report.get("status") != "PASS" or nb_report.get("status") != "PASS":
        conclusion = "MODEL_COMPARISON_FAILED"
    elif poisson_aic is None or nb_aic is None or poisson_bic is None or nb_bic is None:
        conclusion = "MODEL_COMPARISON_FAILED"
    elif (
        nb_aic < poisson_aic
        and nb_bic < poisson_bic
        and nb_report.get("pearson_dispersion", float("inf")) <= poisson_report.get("pearson_dispersion", 0)
    ):
        conclusion = "NEGATIVE_BINOMIAL_PREFERRED"
    elif poisson_report.get("pearson_dispersion", float("inf")) <= 1.5 and poisson_aic <= nb_aic * 1.02:
        conclusion = "POISSON_ADEQUATE"
    else:
        conclusion = "INCONCLUSIVE"
    return {
        "status": "FAIL" if conclusion == "MODEL_COMPARISON_FAILED" else "PASS",
        "poisson_aic": poisson_aic,
        "poisson_bic_llf": poisson_bic,
        "poisson_log_likelihood": poisson_report.get("log_likelihood"),
        "poisson_deviance": poisson_report.get("deviance"),
        "poisson_pearson_dispersion": poisson_report.get("pearson_dispersion"),
        "poisson_mae": poisson_report.get("mae"),
        "poisson_rmse": poisson_report.get("rmse"),
        "poisson_spearman_rate": poisson_report.get("spearman_observed_vs_predicted_rate"),
        "poisson_converged": poisson_report.get("converged"),
        "negative_binomial_aic": nb_aic,
        "negative_binomial_bic_llf": nb_bic,
        "negative_binomial_log_likelihood": nb_report.get("log_likelihood"),
        "negative_binomial_deviance": nb_report.get("deviance"),
        "negative_binomial_pearson_dispersion": nb_report.get("pearson_dispersion"),
        "negative_binomial_mae": nb_report.get("mae"),
        "negative_binomial_rmse": nb_report.get("rmse"),
        "negative_binomial_spearman_rate": nb_report.get("spearman_observed_vs_predicted_rate"),
        "negative_binomial_converged": nb_report.get("converged"),
        "estimated_alpha": nb_report.get("estimated_alpha"),
        "variance_to_mean_ratio": dispersion_report.get("variance_to_mean_ratio"),
        "conclusion": conclusion,
        "preferred_model": conclusion,
        "offset_policy": "device_days used only through log(device_days) offset",
        "bic_policy": "LLF-based BIC computed explicitly; statsmodels GLM deviance BIC is not used.",
    }
