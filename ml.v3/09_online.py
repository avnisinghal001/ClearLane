"""
Stage 09 (Phase 5) — online learning: Gamma-Poisson per-cell rate + drift alarm.

WHY ONLINE / CLOSED-FORM
------------------------
Each cell keeps a running "betting line" on its DAILY violation rate λ_h as a Gamma
posterior. Gamma is conjugate to the Poisson, so a new day of data updates the
posterior by ADDING TWO NUMBERS — no refitting, ever:

    prior      λ_h ~ Gamma(s0, r0)
    observe    y tickets over n days
    posterior  λ_h ~ Gamma(s0 + Σy, r0 + n)
    estimate   E[λ_h] = (s0 + Σy) / (r0 + n)            # mean daily rate
               Var     = (s0 + Σy) / (r0 + n)^2          # uncertainty, for free
               90% CI  = Gamma.ppf([.05, .95], a=shape, scale=1/rate)

WORKED EXAMPLE: a cell with 906 tickets over the 151-day record under a weak
Gamma(1,1) prior → shape=907, rate=152, E[λ]=5.96 tickets/day. Observing one more
12-ticket day → shape=919, rate=153, E[λ]=6.01: the line moved purely by adding 12
and 1. The stage SELF-TESTS this closed-form shift to machine precision.

EMERGING-HOTSPOT DRIFT (honest, scale-free)
-------------------------------------------
We learn a BASELINE posterior from all-but-the-last RECENT_DAYS days, then ask: is
the recent window's rate surprising under that baseline? Under the baseline Gamma
posterior the recent mean rate has predictive mean E_b[λ] and predictive sd
sqrt(E_b/recent_days + Var_b) (Poisson sampling + posterior uncertainty). The drift
z = (recent_rate − E_b)/sd is the standardised surprise; a cell is "emerging" iff it
is both statistically (z > k) and materially (recent_rate > ratio·E_b) above its own
baseline. This is the Bayesian-predictive form of "recent > E[λ] + k·sqrt(Var)"
(scale-free, uses the model's own uncertainty) — the closed-form cousin of a
Page-Hinkley / ADWIN stream alarm, with no extra dependency.

HONESTY: λ is expected VIOLATIONS per day (a real, observed quantity), never
congestion. All state is per CELL — never per officer. Deterministic.

Output: online_state.json (per cell: shape, rate, e_lambda, ci, drift z, emerging)
+ online_metrics.json (n cells, n_emerging, prior, the closed-form self-test).
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import gamma as gamma_dist

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402


def _posterior(sum_y, n_days):
    """Closed-form Gamma posterior from the weak prior. Vectorised over cells."""
    shape = C.ONLINE_PRIOR_SHAPE + np.asarray(sum_y, dtype=float)      # s0 + Σy
    rate = np.full_like(shape, C.ONLINE_PRIOR_RATE + n_days)           # r0 + n (per cell)
    e_lambda = shape / rate
    var = shape / rate ** 2
    return shape, rate, e_lambda, var


def _self_test(shape, rate, y_new):
    """Demonstrate the update is closed-form: adding ONE day of `y_new` tickets
    shifts E[λ] by exactly (r·y_new − s)/(r·(r+1)). Returns before/after + match."""
    e_before = shape / rate
    s2, r2 = shape + y_new, rate + 1.0
    e_after = s2 / r2
    delta_actual = e_after - e_before
    delta_closed_form = (rate * y_new - shape) / (rate * (rate + 1.0))   # algebra of the above
    return {
        "y_new_one_day": float(y_new),
        "e_lambda_before": round(float(e_before), 6),
        "e_lambda_after": round(float(e_after), 6),
        "delta_actual": float(delta_actual),
        "delta_closed_form": float(delta_closed_form),
        "match": bool(abs(delta_actual - delta_closed_form) < 1e-9),
    }


def run() -> dict:
    ev = pd.read_parquet(C.DATA_PROC / "events_h3.parquet")
    cells = pd.read_parquet(C.DATA_PROC / "hotspots.parquet").set_index("h3_r10")
    ev["date"] = pd.to_datetime(ev["date_ist"])

    # full contiguous calendar window (zero-days count → honest daily denominator)
    d_min, d_max = ev["date"].min(), ev["date"].max()
    n_days = int((d_max - d_min).days) + 1
    recent_days = int(C.ONLINE_RECENT_DAYS)
    baseline_days = n_days - recent_days
    cutoff = d_max - pd.Timedelta(days=recent_days - 1)        # recent = last RECENT_DAYS

    # per-cell ticket totals (all / recent), aligned to every occupied cell.
    total = ev.groupby("h3_r10").size().reindex(cells.index, fill_value=0).astype(float)
    recent = (ev[ev["date"] >= cutoff].groupby("h3_r10").size()
              .reindex(cells.index, fill_value=0).astype(float))
    baseline = (total - recent).clip(lower=0)

    # --- full posterior (the served "current rate estimate") --------------- #
    shape, rate, e_lambda, var = _posterior(total.to_numpy(), n_days)
    ci_low = gamma_dist.ppf((1 - C.ONLINE_CI) / 2, a=shape, scale=1.0 / rate)
    ci_high = gamma_dist.ppf(1 - (1 - C.ONLINE_CI) / 2, a=shape, scale=1.0 / rate)

    eligible = total.to_numpy() >= C.ONLINE_MIN_CELL_COUNT

    # Daily counts are heavily OVER-DISPERSED (stage 04 measured dispersion ~9 → NB,
    # not Poisson). A pure-Poisson predictive SD would cry wolf, so estimate the
    # pooled daily over-dispersion phi (Pearson var/mean, zero-days included) on the
    # eligible cells' baseline series and widen the interval by it. Honest + cheap.
    base_dates = pd.date_range(d_min, cutoff - pd.Timedelta(days=1), freq="D")
    elig_ids = list(cells.index[eligible])
    phi = 1.0
    if elig_ids and len(base_dates):
        be = ev[(ev["date"] < cutoff) & (ev["h3_r10"].isin(set(elig_ids)))]
        daily = (be.groupby(["h3_r10", "date"]).size()
                 .reindex(pd.MultiIndex.from_product([elig_ids, base_dates],
                          names=["h3_r10", "date"]), fill_value=0))
        gg = daily.groupby(level=0)
        mu_c, var_c = gg.mean(), gg.var(ddof=0)
        disp = (var_c / mu_c.where(mu_c > 0)).replace([np.inf, -np.inf], np.nan).dropna()
        phi = float(max(np.nanmedian(disp), 1.0)) if len(disp) else 1.0

    # --- baseline posterior + predictive drift z on the recent window ------ #
    # DE-TREND by the citywide recent/baseline ratio so "emerging" means a cell
    # rising FASTER THAN THE CITY — not just riding a global enforcement uptick
    # (the same honesty move as month fixed-effects: remove the common shock).
    s_b, r_b, e_b, var_b = _posterior(baseline.to_numpy(), baseline_days)
    recent_rate = recent.to_numpy() / recent_days
    trend = ((recent.sum() / recent_days) / max(baseline.sum() / baseline_days, 1e-9))
    expected_recent = e_b * trend                              # "if it just tracked the city"
    # predictive sd of the recent MEAN rate = over-dispersed sampling + posterior unc.
    pred_sd = np.sqrt(phi * expected_recent / recent_days + var_b * trend ** 2)
    drift_z = (recent_rate - expected_recent) / np.where(pred_sd > 0, pred_sd, np.inf)

    emerging = (eligible & (drift_z > C.ONLINE_DRIFT_K)
                & (recent_rate > C.ONLINE_EMERGING_MIN_RATIO * np.maximum(expected_recent, 1e-9)))

    # --- closed-form self-test on the busiest cell ------------------------- #
    sample_pos = int(np.argmax(total.to_numpy()))
    st = _self_test(float(shape[sample_pos]), float(rate[sample_pos]),
                    y_new=float(int(round(e_lambda[sample_pos] * 2))))
    st["sample_cell"] = str(cells.index[sample_pos])

    # --- assemble per-cell state ------------------------------------------- #
    state = pd.DataFrame({
        "h3_r10": cells.index,
        "lat": cells["lat"].to_numpy(), "lon": cells["lon"].to_numpy(),
        "police_station": cells["police_station"].to_numpy(),
        "count": total.to_numpy().astype(int),
        "shape": np.round(shape, 3), "rate": np.round(rate, 3),
        "e_lambda": np.round(e_lambda, 4),
        "ci_low": np.round(ci_low, 4), "ci_high": np.round(ci_high, 4),
        "recent_rate": np.round(recent_rate, 4),
        "baseline_e_lambda": np.round(e_b, 4),
        "expected_recent": np.round(expected_recent, 4),       # baseline × citywide trend
        "drift_z": np.round(drift_z, 3), "emerging": emerging,
    })
    state["police_station"] = state["police_station"].where(state["police_station"].notna(), None)

    n_eligible = int(eligible.sum())
    n_emerging = int(emerging.sum())
    metrics = {
        "n_cells": int(len(state)),
        "n_eligible_cells": n_eligible,
        "n_emerging": n_emerging,
        "emerging_share_of_eligible": round(n_emerging / n_eligible, 4) if n_eligible else 0.0,
        "window": {"n_days": n_days, "baseline_days": baseline_days,
                   "recent_days": recent_days, "recent_from": cutoff.date().isoformat(),
                   "recent_to": d_max.date().isoformat()},
        "prior": {"shape_s0": C.ONLINE_PRIOR_SHAPE, "rate_r0": C.ONLINE_PRIOR_RATE},
        "drift": {"k_sigma": C.ONLINE_DRIFT_K, "min_ratio": C.ONLINE_EMERGING_MIN_RATIO,
                  "min_cell_count": C.ONLINE_MIN_CELL_COUNT,
                  "citywide_trend": round(float(trend), 4),
                  "overdispersion_phi": round(float(phi), 3),
                  "test": ("Gamma-Poisson posterior-predictive z, de-trended by the "
                           "citywide recent/baseline ratio (excess over the common shock), "
                           "with daily over-dispersion phi folded into the predictive SD")},
        "self_test": st,
        "note": ("Per-cell Gamma-Poisson conjugate rate (closed-form online update) + "
                 "emerging-hotspot drift alarm. λ is expected VIOLATIONS/day, never "
                 "congestion; state is cell-level only, never per officer."),
    }

    # top emerging + a compact full-state dump for the dashboard / stage 12.
    top_emerging = (state[state["emerging"]].sort_values("drift_z", ascending=False)
                    .head(60).to_dict(orient="records"))
    U.write_json(C.DATA_PROC / "online_state.json",
                 {"metrics": metrics, "n_emerging": n_emerging,
                  "emerging_cells": top_emerging,
                  "cells": state.sort_values("e_lambda", ascending=False)
                            .head(800).to_dict(orient="records")})
    U.write_json(C.DATA_PROC / "online_metrics.json", metrics)
    state.to_parquet(C.DATA_PROC / "online_state.parquet", index=False)
    (C.REPORTS / "online_metrics.txt").write_text(
        "\n".join(f"{k}: {v}" for k, v in metrics.items()) + "\n", encoding="utf-8")

    print(f"[09_online] Gamma-Poisson on {len(state):,} cells | prior Gamma"
          f"({C.ONLINE_PRIOR_SHAPE},{C.ONLINE_PRIOR_RATE}) | {n_days}-day record")
    print(f"[09_online] emerging hotspots (last {recent_days}d): {n_emerging} "
          f"of {n_eligible} eligible ({metrics['emerging_share_of_eligible']*100:.1f}%)")
    print(f"[09_online] self-test cell {st['sample_cell']}: E[lam] {st['e_lambda_before']}"
          f"->{st['e_lambda_after']} on +1 day of {int(st['y_new_one_day'])} "
          f"(closed-form match={st['match']})")
    return metrics


if __name__ == "__main__":
    run()
