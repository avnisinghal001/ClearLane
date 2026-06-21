"""
Stage 06 (Phase 3a) — daily violation-propensity forecaster.

Predicts the expected NUMBER of parking violations per cell per day, as a function
of DAY-OF-WEEK + calendar + recent history + static cell context. This is the
honest, dataset-grounded forecast: we predict violation PROPENSITY, NOT traffic,
and only at DATE granularity (the ticket hour is an upload artifact, §5).

PANEL: one row per (active cell × date). Active = cells with >= config
.FORECAST_DAILY_MIN_CELL_COUNT tickets. Features:
  calendar : dow(0-6), is_weekend, month, day-of-month, is_holiday
  history  : lag1, lag7 (same cell, 1 & 7 days ago), roll7 (mean of prior 7 days)
             -> computed with shifts so NO future leakage
  context  : intensity, road_class_wt, junction_share, repeat_share, veh_footprint
TARGET: that day's count.  MODEL: LightGBM objective=poisson.

SPLIT: TEMPORAL — the last config.FORECAST_DAILY_TEST_DAYS dates are the holdout
(train strictly before). We report Poisson deviance / MAE / Spearman on the holdout
and beat a per-cell-mean BASELINE (proof the model learns day-of-week structure).

OUTPUT: forecast_daily.json (per-cell 7-value day-of-week expected curve + peak day)
and forecaster_daily_metrics.json.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402

try:
    import lightgbm as lgb
    _HAS_LGB = True
except Exception:                       # pragma: no cover
    from sklearn.ensemble import HistGradientBoostingRegressor
    _HAS_LGB = False

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_STATIC = ["intensity", "road_class_wt", "junction_share", "repeat_share",
           "veh_footprint_mean"]
_FEATURES = ["dow", "is_weekend", "month", "dom", "is_holiday",
             "lag1", "lag7", "roll7"] + _STATIC


def _poisson_deviance(y, mu):
    y = np.asarray(y, float); mu = np.clip(np.asarray(mu, float), 1e-9, None)
    ratio = np.where(y > 0, y / mu, 1.0)        # avoid log(0) -> NaN warning
    term = np.where(y > 0, y * np.log(ratio), 0.0) - (y - mu)
    return float(2 * np.sum(term) / len(y))


def _build_panel(ev, cells):
    active = cells.index[cells["count"] >= C.FORECAST_DAILY_MIN_CELL_COUNT]
    evx = ev[ev["h3_r10"].isin(active)].copy()
    evx["date"] = pd.to_datetime(evx["date_ist"])
    daily = (evx.groupby(["h3_r10", "date"]).size().rename("count").reset_index())

    dates = pd.date_range(evx["date"].min(), evx["date"].max(), freq="D")
    # full (cell × date) grid so zero-days are explicit (Poisson needs the zeros).
    grid = pd.MultiIndex.from_product([active, dates], names=["h3_r10", "date"])
    panel = (daily.set_index(["h3_r10", "date"]).reindex(grid, fill_value=0)
             .reset_index().sort_values(["h3_r10", "date"]))

    # calendar features
    panel["dow"] = panel["date"].dt.dayofweek
    panel["is_weekend"] = (panel["dow"] >= 5).astype(int)
    panel["month"] = panel["date"].dt.month
    panel["dom"] = panel["date"].dt.day
    hol = {pd.Timestamp(d) for d in C.FORECAST_HOLIDAYS}
    panel["is_holiday"] = panel["date"].isin(hol).astype(int)

    # lag/rolling history (per cell, shifted -> no leakage)
    g = panel.groupby("h3_r10")["count"]
    panel["lag1"] = g.shift(1)
    panel["lag7"] = g.shift(7)
    panel["roll7"] = g.shift(1).rolling(7, min_periods=1).mean().reset_index(level=0, drop=True)
    for c in ("lag1", "lag7", "roll7"):
        panel[c] = panel[c].fillna(0.0)

    # static cell context
    st = cells.reindex(active)[_STATIC].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    panel = panel.merge(st, left_on="h3_r10", right_index=True, how="left")
    return panel, dates


def run() -> dict:
    ev = pd.read_parquet(C.DATA_PROC / "events_h3.parquet")
    cells = pd.read_parquet(C.DATA_PROC / "hotspots.parquet").set_index("h3_r10")

    panel, dates = _build_panel(ev, cells)
    cutoff = dates.max() - pd.Timedelta(days=C.FORECAST_DAILY_TEST_DAYS)
    tr = panel[panel["date"] <= cutoff]
    te = panel[panel["date"] > cutoff]

    Xtr, ytr = tr[_FEATURES].to_numpy(float), tr["count"].to_numpy(float)
    Xte, yte = te[_FEATURES].to_numpy(float), te["count"].to_numpy(float)

    if _HAS_LGB:
        model = lgb.LGBMRegressor(random_state=42, verbose=-1, **C.FORECAST_DAILY_LGBM)
        model.fit(Xtr, ytr)
        model_name = "LightGBM(poisson)"
    else:                                # pragma: no cover
        model = HistGradientBoostingRegressor(loss="poisson", random_state=42)
        model.fit(Xtr, ytr); model_name = "HistGBR(poisson)"
    pred_te = np.clip(model.predict(Xte), 1e-9, None)

    # naive baseline: each cell's mean daily count from TRAIN only.
    cell_mean = tr.groupby("h3_r10")["count"].mean()
    base_te = te["h3_r10"].map(cell_mean).fillna(tr["count"].mean()).to_numpy(float)

    metrics = {
        "model": model_name, "n_active_cells": int(panel["h3_r10"].nunique()),
        "panel_rows": int(len(panel)), "train_rows": int(len(tr)), "test_rows": int(len(te)),
        "test_window_days": C.FORECAST_DAILY_TEST_DAYS,
        "poisson_deviance": round(_poisson_deviance(yte, pred_te), 4),
        "baseline_poisson_deviance": round(_poisson_deviance(yte, base_te), 4),
        "mae": round(float(np.mean(np.abs(yte - pred_te))), 4),
        "baseline_mae": round(float(np.mean(np.abs(yte - base_te))), 4),
        "spearman": round(float(spearmanr(pred_te, yte).statistic), 4),
        "features": _FEATURES,
    }
    metrics["beats_baseline"] = bool(metrics["poisson_deviance"] < metrics["baseline_poisson_deviance"])

    # --- day-of-week expected curve per cell (predict on the full panel) --- #
    panel["pred"] = np.clip(model.predict(panel[_FEATURES].to_numpy(float)), 0, None)
    dow_curve = (panel.groupby(["h3_r10", "dow"])["pred"].mean()
                 .unstack(fill_value=0.0).reindex(columns=range(7), fill_value=0.0))
    rows = []
    meta = cells.reindex(dow_curve.index)
    for cid, r in dow_curve.iterrows():
        curve = [round(float(r[d]), 3) for d in range(7)]
        rows.append({"h3_r10": cid,
                     "lat": float(meta.loc[cid, "lat"]), "lon": float(meta.loc[cid, "lon"]),
                     "police_station": (None if pd.isna(meta.loc[cid, "police_station"])
                                        else str(meta.loc[cid, "police_station"])),
                     "dow_curve": curve, "peak_dow": _DOW[int(np.argmax(curve))],
                     "weekly_expected": round(float(sum(curve)), 2)})
    rows.sort(key=lambda x: -x["weekly_expected"])
    U.write_json(C.DATA_PROC / "forecast_daily.json",
                 {"dow_order": _DOW, "n_cells": len(rows), "cells": rows[:300]})
    U.write_json(C.DATA_PROC / "forecaster_daily_metrics.json", metrics)
    (C.REPORTS / "forecaster_daily_metrics.txt").write_text(
        "\n".join(f"{k}: {v}" for k, v in metrics.items()) + "\n", encoding="utf-8")

    print(f"[06_forecast_daily] {model_name} poissonDev={metrics['poisson_deviance']} "
          f"(baseline {metrics['baseline_poisson_deviance']}) "
          f"MAE={metrics['mae']} Spearman={metrics['spearman']} "
          f"beats_baseline={metrics['beats_baseline']}")
    # city day-of-week shape (sanity: Sun highest, Mon lowest per EDA)
    city = panel.groupby("dow")["count"].sum().reindex(range(7))
    print("[06_forecast_daily] city dow totals: " +
          ", ".join(f"{_DOW[d]}={int(city[d]):,}" for d in range(7)))
    return metrics


if __name__ == "__main__":
    run()
