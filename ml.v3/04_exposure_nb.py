"""
Stage 04 — exposure-corrected Negative-Binomial hotspot model + significance.

This is the intellectual core: find the REAL hotspots, not the POLICED ones.

THE MODEL (count regression with an exposure offset)
----------------------------------------------------
    citations_h ~ NegativeBinomial(mu_h)
    log(mu_h)   = beta0 + beta . X_h + log(exposure_h)
                                       ^^^^^^^^^^^^^^^^^  OFFSET (coef fixed = 1)

The offset turns a COUNT model into a RATE model: dividing by enforcement effort.
  * mu_h with offset  = expected ticket COUNT given how much the cell was patrolled.
  * predict with offset = 0 (exposure = 1) = expected rate PER UNIT of effort =
    the bias-corrected ViolationIntensity (what we rank on).

WHY NEGATIVE BINOMIAL, NOT POISSON
----------------------------------
Poisson assumes variance = mean. Ticket counts are wildly over-dispersed.
Example: a set of cells with mean ~35 but variance ~420 -> dispersion ratio ~12.
NB adds a dispersion parameter alpha to absorb that. We:
  1. fit Poisson (with offset), measure Pearson dispersion = sum((y-mu)^2/mu)/df,
  2. if dispersion > 1.2 -> estimate alpha by the Cameron-Trivedi NB2 auxiliary
     regression:  z = ((y-mu)^2 - y)/mu  regressed on mu through the origin;
     the slope IS alpha (e.g. alpha ~ 0.31),
  3. refit as NB(alpha) with the same offset.
Report effects as Incidence Rate Ratios IRR = exp(beta). Example: beta_junction =
0.41 -> IRR 1.51 -> cells at a named junction have ~1.51x the violation RATE,
holding exposure constant.

SIGNIFICANCE (is a hotspot real, or noise?)
-------------------------------------------
  * Getis-Ord Gi* (esda): each cell gets a z-score + pseudo p. z>0 & p<0.05 = a
    statistically real HOT cluster (vs random). z<1.96 = not significant.
  * Moran's I on the model RESIDUALS: should be ~0 if the model captured the
    spatial structure (a leakage / mis-specification check).

DATA SPLIT (no spatial leakage)
-------------------------------
Hotspot detection is cross-sectional (one row per cell), so we use SPATIAL-BLOCK
cross-validation: cells are grouped into coarse res-7 blocks (~1.2 km) and we
K-fold over BLOCKS, so a cell and its neighbours never sit in both train and test.
We report Poisson deviance, Spearman, and precision@K (top-K predicted vs observed).

Outputs: hotspots.json (per-cell rate + Gi* z/p), nb_metrics.json (alpha, IRRs,
Moran's I, spatial-CV scores).
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402

try:
    import statsmodels.api as sm
    _HAS_SM = True
except Exception:                       # pragma: no cover
    _HAS_SM = False

try:
    from sklearn.linear_model import PoissonRegressor
    from sklearn.model_selection import GroupKFold
    from sklearn.preprocessing import StandardScaler
    _HAS_SK = True
except Exception:                       # pragma: no cover
    _HAS_SK = False


# --------------------------------------------------------------------------- #
def _design(cells: pd.DataFrame):
    """Assemble X (context features), y (counts), exposure, all aligned.

    X is returned as a clean float64 numpy array (statsmodels + pandas 3.0 reject
    object-dtype frames), with the feature names tracked separately for the IRRs.
    """
    feats = [c for c in C.NB_FEATURES if c in cells.columns]
    Xdf = cells[feats].apply(pd.to_numeric, errors="coerce")
    X = np.ascontiguousarray(Xdf.to_numpy(dtype="float64"))
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    y = cells["count"].to_numpy("float64")
    exposure = cells["exposure"].clip(lower=C.EXPOSURE_MIN).to_numpy("float64")
    return X, y, exposure, feats


def _estimate_alpha(y, mu):
    """Cameron-Trivedi NB2 dispersion alpha via OLS-through-origin of the aux var.

    z_i = ((y_i - mu_i)^2 - y_i) / mu_i ;  alpha = sum(z*mu)/sum(mu^2).
    """
    z = ((y - mu) ** 2 - y) / np.where(mu > 0, mu, 1e-9)
    alpha = float(np.sum(z * mu) / np.sum(mu ** 2)) if np.sum(mu ** 2) > 0 else 0.0
    return max(alpha, C.NB_ALPHA_FLOOR)


def _fit_nb(X, y, exposure, feat_names):
    """Poisson -> dispersion test -> NB(alpha). Pure-numpy in/out (pandas-3.0 safe).

    Returns (bias_corrected_rate, fitted_counts, info). `rate` is predicted with the
    offset set to 0 (exposure = 1) = expected violations per unit of enforcement.
    """
    off = np.log(exposure)
    Xc = np.column_stack([np.ones(len(y)), X])          # prepend intercept column
    cols = ["const"] + list(feat_names)
    zero_off = np.zeros(len(y))

    pois = sm.GLM(y, Xc, family=sm.families.Poisson(), offset=off).fit(maxiter=C.NB_MAXITER)
    mu = np.clip(np.asarray(pois.mu, float), 1e-9, None)
    dispersion = float(np.sum((y - mu) ** 2 / mu) / pois.df_resid)

    if dispersion > C.DISPERSION_NB_THRESHOLD:
        alpha = _estimate_alpha(y, mu)
        model = sm.GLM(y, Xc, family=sm.families.NegativeBinomial(alpha=alpha),
                       offset=off).fit(maxiter=C.NB_MAXITER)
        family = "NegativeBinomial"
    else:                                # not over-dispersed -> Poisson is fine
        alpha, model, family = 0.0, pois, "Poisson"

    rate = np.asarray(model.predict(Xc, offset=zero_off), float)     # exposure = 1
    fitted = np.asarray(model.predict(Xc, offset=off), float)        # with exposure
    irr = {n: round(float(np.exp(b)), 3) for n, b in zip(cols, model.params)}
    info = {"family": family, "dispersion": round(dispersion, 2),
            "alpha": round(alpha, 4), "n_features": int(X.shape[1]), "irr": irr}
    # carry the fitted object + coefficient vector so run() can PERSIST the model
    # (the offset is log(exposure); predict at offset 0 == bias-corrected rate).
    info["_model"] = model
    info["_coef"] = {"feature_names": cols,
                     "params": [float(b) for b in model.params],
                     "offset": "log(exposure)", "alpha": alpha, "family": family}
    return rate, fitted, info


def _fit_rate_sklearn(Xtr, ytr, etr, Xte):
    """Fallback / CV learner: PoissonRegressor on rate = y/exposure, weighted by
    exposure (the standard offset trick). Returns predicted RATE on Xte."""
    sc = StandardScaler().fit(Xtr)
    m = PoissonRegressor(alpha=1e-3, max_iter=500)
    m.fit(sc.transform(Xtr), ytr / np.clip(etr, 1, None), sample_weight=np.clip(etr, 1, None))
    return np.clip(m.predict(sc.transform(Xte)), 1e-9, None)


def _spatial_cv(X, y, exposure, blocks):
    """Spatial-block K-fold: group by coarse res-7 block so neighbours don't leak.

    Reports Poisson deviance, Spearman(pred rate, observed rate), precision@K.
    """
    if not _HAS_SK:
        return {"skipped": "scikit-learn not installed"}
    Xv = np.asarray(X, float)
    rate_obs = y / np.clip(exposure, 1, None)
    uniq_blocks = pd.Series(blocks).nunique()
    n_splits = int(min(C.CV_FOLDS, uniq_blocks))
    if n_splits < 2:
        return {"skipped": "too few spatial blocks"}
    gkf = GroupKFold(n_splits=n_splits)
    devs, rhos, prec = [], [], {k: [] for k in C.PRECISION_AT_K}
    for tr, te in gkf.split(Xv, y, groups=blocks):
        pred = _fit_rate_sklearn(Xv[tr], y[tr], exposure[tr], Xv[te])
        # Poisson deviance on the held-out COUNTS (pred count = rate × exposure)
        mu = np.clip(pred * exposure[te], 1e-9, None)
        yte = y[te]
        dev = 2 * np.sum(np.where(yte > 0, yte * np.log(yte / mu), 0.0) - (yte - mu))
        devs.append(dev / len(te))
        rhos.append(float(spearmanr(pred, rate_obs[te]).statistic))
        order_pred = np.argsort(pred)[::-1]
        order_obs = np.argsort(rate_obs[te])[::-1]
        for k in C.PRECISION_AT_K:
            kk = min(k, len(te))
            prec[k].append(len(set(order_pred[:kk]) & set(order_obs[:kk])) / kk)
    return {"n_splits": n_splits,
            "mean_poisson_deviance": round(float(np.mean(devs)), 3),
            "spearman_rate": round(float(np.nanmean(rhos)), 3),
            "precision_at_k": {f"top{k}": round(float(np.mean(v)), 3)
                               for k, v in prec.items()}}


def _gistar_moran(cells, rate, resid):
    """Getis-Ord Gi* (on rate) + Moran's I (on residuals) via esda/libpysal."""
    out = {"available": False}
    try:
        from libpysal.weights import W, KNN
        from esda.getisord import G_Local
        from esda.moran import Moran
    except Exception as e:                # pragma: no cover
        cells["gistar_z"] = np.nan
        cells["gistar_p"] = np.nan
        cells["sig_hot"] = False
        out["note"] = f"esda/libpysal not installed ({type(e).__name__}); skipped"
        return out

    # Build weights in EXACTLY cells.index order so the result arrays (which esda
    # returns in w.id_order) line up positionally with `cells` for both paths:
    #   * dict W  -> id_order == insertion order == cells.index,
    #   * KNN     -> id_order == 0..n-1 == coords row order == cells.index.
    ids = list(cells.index)
    id_set = set(ids)
    adj = json.loads((C.DATA_PROC / "h3_adjacency.json").read_text())
    neighbors = {c: [n for n in adj.get(c, []) if n in id_set] for c in ids}
    # libpysal prints an "island" line per neighbourless cell — capture that spam
    # (and any warnings) so the stage output stays clean.
    import contextlib
    import io
    import warnings as _w
    sink = io.StringIO()
    wtype = "H3-adjacency"
    with _w.catch_warnings(), contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        _w.simplefilter("ignore")
        try:
            w = W(neighbors, silence_warnings=True)
            if len(ids) < 3 or max(w.cardinalities.values()) == 0:
                raise ValueError("degenerate adjacency")
        except Exception:                 # fallback: KNN on centroids (hex ~6)
            w = KNN.from_array(cells[["lat", "lon"]].to_numpy(),
                               k=min(C.GISTAR_KNN_K, len(ids) - 1),
                               silence_warnings=True)
            wtype = "KNN-fallback"
        w.transform = "r"

        y = np.asarray(rate, float)                  # cells order == w.id_order
        lg = G_Local(y, w, star=C.GISTAR_STAR, permutations=C.GISTAR_PERMUTATIONS,
                     seed=C.CV_RANDOM_STATE)
        moran = Moran(np.asarray(resid, float), w, permutations=C.GISTAR_PERMUTATIONS)

    cells["gistar_z"] = np.asarray(lg.Zs, float)
    cells["gistar_p"] = np.asarray(lg.p_sim, float)
    cells["sig_hot"] = (cells["gistar_z"] > 0) & (cells["gistar_p"] < C.SIG_P)
    return {"available": True, "n_sig_hot": int(cells["sig_hot"].sum()),
            "moran_I_residuals": round(float(moran.I), 4),
            "moran_p_residuals": round(float(moran.p_sim), 4),
            "weights": wtype}


def run() -> dict:
    cells = pd.read_parquet(C.DATA_PROC / "cell_features.parquet").set_index("h3_r10")
    X, y, exposure, feats = _design(cells)

    rate = fitted = info = None
    if _HAS_SM:
        try:
            rate, fitted, info = _fit_nb(X, y, exposure, feats)
        except Exception as e:            # tiny/degenerate data, separation, etc.
            print(f"[04_exposure_nb] statsmodels GLM failed ({type(e).__name__}: {e}); "
                  "falling back to sklearn Poisson rate")
    if rate is None:                      # sklearn fallback (or no statsmodels)
        rate = _fit_rate_sklearn(X, y, exposure, X)
        fitted = rate * exposure
        info = {"family": "PoissonRegressor(sklearn fallback)",
                "dispersion": None, "alpha": None, "n_features": int(X.shape[1]),
                "irr": {}}
        if _HAS_SK:                       # keep a persistable scaler+model pair
            _sc = StandardScaler().fit(X)
            _m = PoissonRegressor(alpha=1e-3, max_iter=500)
            _m.fit(_sc.transform(X), y / np.clip(exposure, 1, None),
                   sample_weight=np.clip(exposure, 1, None))
            info["_model"] = {"kind": "sklearn_poisson", "scaler": _sc, "model": _m,
                              "feature_names": list(feats)}

    cells["bias_rate"] = rate                                   # per unit exposure
    cells["intensity"] = U.percentile_norm(pd.Series(rate, index=cells.index))
    resid = y - fitted
    cells["resid"] = resid

    # rank divergence: naive raw-count rank vs bias-corrected rank. A big positive
    # number = a cell far MORE important than its ticket count suggests (under-
    # policed). This is the "found a hidden hotspot" signal.
    cells["rank_naive"] = cells["count"].rank(ascending=False, method="min").astype(int)
    cells["rank_bias"] = pd.Series(rate, index=cells.index).rank(
        ascending=False, method="min").astype(int)
    cells["rank_divergence"] = cells["rank_naive"] - cells["rank_bias"]

    sig = _gistar_moran(cells, rate, resid)
    cv = _spatial_cv(X, y, exposure, cells["block"].to_numpy())

    # --- persist hotspots.json (map-ready) -------------------------------- #
    hs = cells.reset_index()
    keep = ["h3_r10", "lat", "lon", "police_station", "count", "exposure",
            "raw_rate", "bias_rate", "intensity", "rank_naive", "rank_bias",
            "rank_divergence", "gistar_z", "gistar_p", "sig_hot", "road_class"]
    keep = [k for k in keep if k in hs.columns]
    U.write_json(C.DATA_PROC / "hotspots.json", {
        "n_cells": int(len(hs)),
        "model": info["family"],
        "cells": hs[keep].sort_values("intensity", ascending=False)
                  .head(500).to_dict(orient="records"),
    })

    # top IRRs for the report (most influential context drivers)
    irr_sorted = sorted(info.get("irr", {}).items(),
                        key=lambda kv: -abs(np.log(max(kv[1], 1e-6))))[:8]
    metrics = {"model": {k: v for k, v in info.items() if not k.startswith("_")},
               "significance": sig, "spatial_cv": cv,
               "n_cells": int(len(cells)),
               "top_irr": dict(irr_sorted),
               "n_under_policed": int((cells["rank_divergence"] > 100).sum())}
    U.write_json(C.DATA_PROC / "nb_metrics.json", metrics)

    # --- PERSIST the fitted hotspot model (real file + manifest entry) ------ #
    try:
        import models_io as MIO            # noqa: E402 (pipeline-local helper)
        nb_obj = info.get("_model")
        if nb_obj is not None:
            try:                            # statsmodels GLMResults pickle (full model)
                MIO.save_joblib(nb_obj, "nb_model.pkl")
            except Exception as e:          # pragma: no cover - fall back to coefficients
                print(f"[04_exposure_nb] full-model pickle failed ({type(e).__name__}); "
                      "saving coefficient vector instead")
                MIO.save_pickle(info.get("_coef", {}), "nb_model.pkl")
            MIO.register(
                "hotspot_nb", model_type=info["family"], file="nb_model.pkl",
                features=feats,
                metrics={"family": info["family"], "dispersion": info.get("dispersion"),
                         "alpha": info.get("alpha"),
                         "spatial_cv_spearman": cv.get("spearman_rate"),
                         "moran_I_residuals": sig.get("moran_I_residuals"),
                         "n_sig_hot": sig.get("n_sig_hot"),
                         "n_under_policed": metrics["n_under_policed"]},
                params={"offset": "log(exposure)", "n_features": info["n_features"]},
                notes=("Exposure-corrected count GLM; predict at offset 0 (exposure=1) "
                       "= bias-corrected violation RATE (the intensity we rank on). "
                       "Predicts violation propensity, never congestion."))
            print(f"[04_exposure_nb] persisted nb_model.pkl ({info['family']}) -> models/")
    except Exception as e:                  # pragma: no cover - persistence is best-effort
        print(f"[04_exposure_nb] model persistence skipped: {type(e).__name__}: {e}")
    (C.REPORTS / "nb_metrics.txt").write_text(
        json.dumps(U.json_safe(metrics), indent=2), encoding="utf-8")

    cells.reset_index().to_parquet(C.DATA_PROC / "hotspots.parquet", index=False)

    print(f"[04_exposure_nb] {info['family']} disp={info.get('dispersion')} "
          f"alpha={info.get('alpha')} · "
          f"Gi* sig_hot={sig.get('n_sig_hot')} Moran(resid)={sig.get('moran_I_residuals')}")
    print(f"[04_exposure_nb] spatial-CV spearman={cv.get('spearman_rate')} "
          f"prec@k={cv.get('precision_at_k')} · "
          f"under-policed cells={metrics['n_under_policed']}")
    if irr_sorted:
        print("[04_exposure_nb] top IRRs: " +
              ", ".join(f"{k}={v}" for k, v in irr_sorted[:4]))
    return metrics


if __name__ == "__main__":
    run()
