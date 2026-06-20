"""
Stage 05 — next-month obstruction forecaster (the legitimate ML centerpiece).

  Features : each zone's Nov-Jan signals (pressure, recurrence, mix, repeat share,
             exposure, trend, typology, junction) PLUS Mappls context from stage
             04b (POI distances/counts, station reachability) and the auxiliary
             offence-code severity.
  Target   : that zone's Feb-Mar TICKET COUNT — a real, observed future COUNT.
             Modelled with a POISSON objective (count data). NOT congestion.
  Models   : sklearn PoissonRegressor (GLM baseline) -> LightGBM `objective=poisson`
             (main) -> CatBoost Poisson (challenger, if installed).
  Holdout  : temporal design (features Nov-Jan -> target Feb-Mar) + a spatial
             (zone) hold-out for generalization metrics.
  Report   : Poisson deviance, R2, Spearman, top-K precision. SHAP reason codes.

forecast_pressure is derived from the predicted count x the zone's weight/ticket
so the downstream payload + UI keep working unchanged.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import mean_poisson_deviance
from sklearn.model_selection import KFold, train_test_split
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402

try:
    import lightgbm as lgb
    _HAS_LGB = True
except Exception:                       # pragma: no cover
    from sklearn.ensemble import GradientBoostingRegressor
    _HAS_LGB = False

try:                                    # optional challenger
    from catboost import CatBoostRegressor
    _HAS_CAT = True
except Exception:                       # pragma: no cover
    _HAS_CAT = False


def _feature_frame(ev, z):
    feat_ev = ev[ev["month_ist"].isin(C.FORECAST_FEATURE_MONTHS)]
    g = feat_ev.groupby("superzone_id", observed=True)
    f = pd.DataFrame(index=z["superzone_id"])
    f["feat_pressure"] = g["event_weight"].sum().reindex(f.index).fillna(0)
    f["feat_tickets"] = g["id"].count().reindex(f.index).fillna(0)
    f["feat_active_days"] = g["date_ist"].nunique().reindex(f.index).fillna(0)
    f["feat_months"] = g["month_ist"].nunique().reindex(f.index).fillna(0)
    f["feat_veh_footprint"] = g["vehicle_wt"].mean().reindex(f.index).fillna(0)
    f["feat_severity"] = g["row_severity"].mean().reindex(f.index).fillna(0)
    f["feat_offence_sev"] = g["offence_severity_aux"].mean().reindex(f.index).fillna(0)
    f["feat_officers"] = g["created_by_id"].nunique().reindex(f.index).fillna(0)
    mp = (feat_ev.groupby(["superzone_id", "month_ist"], observed=True)["event_weight"]
          .sum().unstack(fill_value=0))
    for m in C.FORECAST_FEATURE_MONTHS:
        if m not in mp.columns:
            mp[m] = 0.0
    mp = mp[C.FORECAST_FEATURE_MONTHS]
    xidx = np.arange(len(C.FORECAST_FEATURE_MONTHS))
    f["feat_trend"] = mp.apply(
        lambda r: float(np.polyfit(xidx, r.values, 1)[0]) if r.sum() > 0 else 0.0,
        axis=1).reindex(f.index).fillna(0)
    zi = z.set_index("superzone_id")
    # repeat-vehicle share computed IN-WINDOW (Nov-Jan only) — the zone_scores
    # repeat_share spans all months incl. the Feb-Mar target, which would leak.
    f["feat_repeat_share"] = _window_repeat_share(feat_ev).reindex(f.index).fillna(0)
    f["feat_junction"] = zi["junction_anchored"].reindex(f.index).fillna(False).astype(int)
    f["feat_cluster"] = zi["cluster"].reindex(f.index).fillna(-1).astype(int)

    # --- Mappls context features from stage 04b (offline -> neutral defaults) #
    try:
        zf = pd.read_parquet(C.DATA_PROC / "zone_features.parquet").set_index("superzone_id")
        num = [c for c in zf.columns if c.startswith("poi_") or c == "reach_km"]
        for c in num:
            f[f"ctx_{c}"] = pd.to_numeric(zf[c], errors="coerce").reindex(f.index)
        # fill: distances -> far sentinel, counts/reach -> 0/median
        for c in num:
            col = f"ctx_{c}"
            if c.endswith("_m"):
                f[col] = f[col].fillna(C.MAPPLS_POI_FAR_M)
            else:
                f[col] = f[col].fillna(0)
    except Exception:
        pass
    return f


def _window_repeat_share(feat_ev):
    """Per-zone repeat-vehicle share using ONLY the feature-window events (no
    target-period leakage). Mirrors stage-04 repeat logic but in-window."""
    veh = feat_ev.groupby("vehicle_number", observed=True)["id"].count()
    repeat_global = set(veh[veh >= C.REPEAT_GLOBAL_MIN].index)
    vz = (feat_ev.groupby(["superzone_id", "vehicle_number"], observed=True)["id"]
          .count().rename("n").reset_index())
    vz["is_repeat"] = (vz["n"] >= C.REPEAT_ZONE_MIN) | vz["vehicle_number"].isin(repeat_global)
    vz["rep_n"] = vz["n"] * vz["is_repeat"]
    agg = vz.groupby("superzone_id", observed=True).agg(
        zt=("n", "sum"), rt=("rep_n", "sum"))
    return (agg["rt"] / agg["zt"].replace(0, np.nan)).fillna(0)


def _weight_per_ticket(f):
    wpt = f["feat_pressure"] / f["feat_tickets"].replace(0, np.nan)
    return wpt.fillna(wpt.median() if wpt.notna().any() else 0.3)


def _r2(y, p):
    ss_res = float(np.sum((y - p) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return 1 - ss_res / ss_tot if ss_tot > 0 else 0.0


def _cv_metrics(X, y, params, n_splits, seed):
    """K-fold CV for an honest generalization estimate (mean +/- std). Uses a fixed
    tree count (the early-stopped best) so folds are comparable and fast."""
    if not _HAS_LGB or len(X) < n_splits * 3:
        return {}
    r2s, rhos, devs = [], [], []
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for tr, te in kf.split(X):
        m = lgb.LGBMRegressor(random_state=seed, verbose=-1, **params)
        m.fit(X[tr], y[tr])
        p = np.clip(m.predict(X[te]), 1e-6, None)
        r2s.append(_r2(y[te], p))
        rhos.append(float(spearmanr(y[te], p).statistic))
        devs.append(float(mean_poisson_deviance(y[te], p)))
    return {"cv_folds": n_splits,
            "cv_r2_mean": round(float(np.mean(r2s)), 3),
            "cv_r2_std": round(float(np.std(r2s)), 3),
            "cv_spearman_mean": round(float(np.nanmean(rhos)), 3),
            "cv_poisson_deviance_mean": round(float(np.mean(devs)), 3)}


def run():
    ev = pd.read_parquet(C.DATA_PROC / "events_clean.parquet")
    z = pd.read_parquet(C.DATA_PROC / "zone_scores.parquet")

    f = _feature_frame(ev, z)
    feat_names = list(f.columns)
    X = f.values.astype(float)

    # target = Feb-Mar TICKET COUNT (a real observed future count -> Poisson)
    tgt_ev = ev[ev["month_ist"].isin(C.FORECAST_TARGET_MONTHS)]
    y = (tgt_ev.groupby("superzone_id", observed=True)["id"].count()
         .reindex(f.index).fillna(0).values.astype(float))

    # spatial holdout: train/test; a val slice is carved from train for early
    # stopping. K-fold CV (below) gives the honest mean+/-std generalization.
    Xtr_full, Xte, ytr_full, yte = train_test_split(
        X, y, test_size=C.FORECAST_TEST_FRAC, random_state=C.FORECAST_RANDOM_STATE)

    # ---- GLM baseline (interpretable benchmark) -------------------------- #
    sc = StandardScaler().fit(Xtr_full)
    glm = PoissonRegressor(alpha=1e-3, max_iter=500).fit(sc.transform(Xtr_full), ytr_full)
    glm_pred = np.clip(glm.predict(sc.transform(Xte)), 1e-6, None)
    glm_dev = float(mean_poisson_deviance(yte, glm_pred))

    # ---- main model: LightGBM Poisson (regularized + early-stopped) ------ #
    params = dict(C.FORECAST_LGBM_PARAMS)
    best_iter, Xtr, Xval, ytr, yval = None, None, None, None, None
    if _HAS_LGB:
        Xtr, Xval, ytr, yval = train_test_split(
            Xtr_full, ytr_full, test_size=C.FORECAST_VAL_FRAC,
            random_state=C.FORECAST_RANDOM_STATE)
        model = lgb.LGBMRegressor(random_state=C.FORECAST_RANDOM_STATE, verbose=-1, **params)
        model.fit(Xtr, ytr, eval_set=[(Xval, yval)], eval_metric="poisson",
                  callbacks=[lgb.early_stopping(C.FORECAST_EARLY_STOPPING, verbose=False)])
        best_iter = int(model.best_iteration_ or params["n_estimators"])
        model_name = "LightGBM(poisson)"
    else:                                    # pragma: no cover
        from sklearn.ensemble import GradientBoostingRegressor
        model = GradientBoostingRegressor(random_state=C.FORECAST_RANDOM_STATE)
        model.fit(Xtr_full, ytr_full)
        model_name = "GradientBoosting"

    pred_te = np.clip(model.predict(Xte), 1e-6, None)
    pred_tr = np.clip(model.predict(Xtr_full), 1e-6, None)
    poisson_dev = float(mean_poisson_deviance(yte, pred_te))
    train_dev = float(mean_poisson_deviance(ytr_full, pred_tr))
    r2 = _r2(yte, pred_te)
    train_r2 = _r2(ytr_full, pred_tr)
    rho = float(spearmanr(yte, pred_te).statistic)
    topk_prec = {}
    for k in (10, 20, 50):
        kk = min(k, len(yte))
        topk_prec[f"top{kk}"] = round(
            len(set(np.argsort(pred_te)[-kk:]) & set(np.argsort(yte)[-kk:])) / kk, 3)

    # ---- K-fold CV: honest generalization estimate (mean +/- std) -------- #
    cv_params = dict(params)
    if best_iter:
        cv_params["n_estimators"] = best_iter      # early-stopped count, comparable
    cv = _cv_metrics(X, y, cv_params, C.FORECAST_CV_FOLDS, C.FORECAST_RANDOM_STATE)
    overfit_gap = round(train_r2 - cv.get("cv_r2_mean", r2), 3)

    # ---- CatBoost Poisson challenger (regularized + early-stopped) ------- #
    challenger = {}
    if _HAS_CAT and C.FORECAST_CATBOOST:
        try:                                 # pragma: no cover
            cb = CatBoostRegressor(random_seed=C.FORECAST_RANDOM_STATE,
                                   **dict(C.FORECAST_CATBOOST_PARAMS))
            if _HAS_LGB:
                cb.fit(Xtr, ytr, eval_set=(Xval, yval), use_best_model=True)
            else:
                cb.fit(Xtr_full, ytr_full)
            cb_pred = np.clip(cb.predict(Xte), 1e-6, None)
            challenger = {"model": "CatBoost(Poisson)",
                          "poisson_deviance": round(float(mean_poisson_deviance(yte, cb_pred)), 3),
                          "spearman": round(float(spearmanr(yte, cb_pred).statistic), 3),
                          "best_iteration": int(getattr(cb, "best_iteration_", 0) or 0)}
        except Exception as e:
            challenger = {"model": "CatBoost", "skipped": type(e).__name__}

    # ---- full-zone predictions -> count + derived pressure --------------- #
    full_count = np.clip(model.predict(X), 0, None)
    wpt = _weight_per_ticket(f).values
    z = z.set_index("superzone_id")
    z["forecast_count"] = pd.Series(full_count, index=f.index)
    z["forecast_pressure"] = pd.Series(full_count * wpt, index=f.index)
    z["forecast_score"] = U.percentile_norm(z["forecast_pressure"])
    feat_window_months = len(C.FORECAST_FEATURE_MONTHS)
    tgt_window_months = len(C.FORECAST_TARGET_MONTHS)
    expected_flat = f["feat_pressure"].values * (tgt_window_months / feat_window_months)
    z["forecast_rising"] = z["forecast_pressure"].values > expected_flat * 1.10
    z = z.reset_index()
    z.to_parquet(C.DATA_PROC / "zone_scores.parquet", index=False)

    # ---- SHAP (fallback to gain importance) ------------------------------ #
    shap_summary, shap_method = {}, ""
    try:
        import shap
        sv = shap.TreeExplainer(model).shap_values(Xte)
        mean_abs = np.abs(sv).mean(axis=0)
        shap_summary = dict(sorted(
            {n: round(float(v), 4) for n, v in zip(feat_names, mean_abs)}.items(),
            key=lambda kv: -kv[1]))
        shap_method = "shap_tree_explainer"
    except Exception as e:                   # pragma: no cover
        imp = getattr(model, "feature_importances_", np.ones(len(feat_names)))
        imp = imp / (imp.sum() or 1)
        shap_summary = {n: round(float(v), 4) for n, v in
                        sorted(zip(feat_names, imp), key=lambda kv: -kv[1])}
        shap_method = f"gain_importance_fallback ({type(e).__name__})"

    gap_flag = overfit_gap > C.FORECAST_OVERFIT_GAP
    metrics = {
        "model": model_name,
        "objective": "poisson" if (_HAS_LGB and C.FORECAST_POISSON) else "regression",
        "target": "Feb-Mar ticket COUNT (real observed future count)",
        "holdout": "spatial zone split (Nov-Jan features -> Feb-Mar target) + 5-fold CV",
        "n_zones": int(len(X)), "n_features": len(feat_names),
        "train_size": int(len(Xtr_full)), "test_size": int(len(Xte)),
        "best_iteration": best_iter,
        "poisson_deviance": round(poisson_dev, 3),
        "train_poisson_deviance": round(train_dev, 3),
        "r2": round(r2, 3), "train_r2": round(train_r2, 3),
        "overfit_gap_r2": overfit_gap, "overfit_flag": bool(gap_flag),
        "spearman": round(rho, 3),
        "topk_precision": topk_prec,
        "cv": cv,
        "glm_baseline": {"model": "PoissonRegressor(GLM)",
                         "poisson_deviance": round(glm_dev, 3)},
        "challenger": challenger,
        "leakage_controls": ("repeat_share recomputed in-window (Nov-Jan); all "
                             "aggregations exclude the Feb-Mar target months"),
        "regularization": {k: params.get(k) for k in
                           ("reg_alpha", "reg_lambda", "min_child_samples",
                            "subsample", "colsample_bytree", "num_leaves")},
        "mappls_features": [n for n in feat_names if n.startswith("ctx_")],
        "feature_importance_method": shap_method,
        "shap_importance": shap_summary,
        "forecast_rising_zones": int(z["forecast_rising"].sum()),
    }
    U.write_json(C.DATA_PROC / "forecaster_metrics.json", metrics)
    (C.REPORTS / "forecaster_metrics.txt").write_text(
        "\n".join(f"{k}: {v}" for k, v in metrics.items()) + "\n")

    print(f"[05_forecaster] {model_name} test R2={r2:.3f} (train {train_r2:.3f}) "
          f"CV R2={cv.get('cv_r2_mean')}±{cv.get('cv_r2_std')} gap={overfit_gap}"
          + ("  [OVERFIT?]" if gap_flag else "")
          + f" · poissonDev={poisson_dev:.2f} (GLM {glm_dev:.2f}) Spearman={rho:.3f}")
    print(f"[05_forecaster] best_iter={best_iter} topK={topk_prec} "
          f"drivers={list(shap_summary)[:4]} rising={metrics['forecast_rising_zones']}"
          + (f" · challenger {challenger.get('model')} "
             f"dev={challenger.get('poisson_deviance')}" if challenger else ""))
    return metrics


if __name__ == "__main__":
    run()
