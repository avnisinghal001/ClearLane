"""
Stage 10 (Phase 6) — honest quasi-causal enforcement panel (cell × month TWFE).

WHAT WE CAN AND CANNOT CLAIM
----------------------------
The headline causal question for this product — "does illegal parking CAUSE measured
congestion delay?" — requires a panel of LIVE Mappls ETA (CongestionSeverity) over
time, which the route/ETA API (blocked today) will supply in Phase 2 live. That
design (cell×slot fixed-effects of severity on parking intensity, + event study with
placebo) is wired to drop in HERE once the API is enabled. We do NOT fabricate a
parking→delay number from ticket data.

What the TICKET data CAN identify honestly is ENFORCEMENT RESPONSIVENESS: within a
cell, net of citywide monthly shocks, does heavier enforcement EXPOSURE this month
move the CHANGE in violations next month? That is a real, defensible observational
estimand on the data we have.

THE DESIGN (two-way fixed effects on a cell×month panel)
--------------------------------------------------------
    Δlog(viol)_{z,t→t+1} = α_z + γ_t + β · exposure_std_{z,t} + ε_{z,t}
      Δlog(viol)   = log1p(viol_{z,t+1}) − log1p(viol_{z,t})   (the "change next month")
      exposure_std = z-scored distinct (device×date) effort in cell z, month t
      α_z          = CELL fixed effect   (removes "this block is always busy / trending")
      γ_t          = MONTH fixed effect  (removes "the whole city ramped up in Jan")
Estimated by the within (cell-demeaned) estimator + month dummies; SEs cluster-robust
by cell. β < 0 ⇒ heavier enforcement precedes a drop next month (deterrence OR mean-
reversion — NOT separable without exogeneity; we say so). β > 0 ⇒ chronic escalation.

IS IT REAL, OR AN ARTEFACT? — PLACEBO + LEAD TESTS
--------------------------------------------------
  * PLACEBO: shuffle exposure ACROSS cells within each month (CAUSAL_PLACEBO_PERMUTATIONS
    times). This destroys the cell-level link but keeps every marginal → β must
    collapse to ≈ 0. We report the placebo mean and its 2.5–97.5% band; the real β is
    "distinguishable" iff it sits OUTSIDE that empirical-null band.
  * LEAD (parallel-trends proxy): regress the SAME change on NEXT month's exposure
    (a future regressor). A ≈ 0 lead supports no anticipation / reverse causation;
    a big lead would warn the design is confounded.

HONESTY: never call modeled congestion "measured"; never profile an officer (exposure
is aggregated device×date effort at the CELL level only). Deterministic (fixed seed).

Output: causal.json (design, β, CI, placebo, lead, n_obs, caveat, congestion_causal).
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402

try:
    import statsmodels.api as sm
    _HAS_SM = True
except Exception:                       # pragma: no cover
    _HAS_SM = False


_MONTHS = ["2023-11", "2023-12", "2024-01", "2024-02", "2024-03", "2024-04"]


def _build_panel(ev: pd.DataFrame) -> pd.DataFrame:
    """One row per (cell, month): violations + enforcement exposure (device×date)."""
    keep = ev["h3_r10"].notna()
    e = ev[keep].copy()
    e["dev_day"] = (e["device_id"].astype("string").fillna("NA") + "|"
                    + e["date_ist"].astype("string"))
    g = e.groupby(["h3_r10", "month_ist"], observed=True)
    panel = pd.DataFrame({"viol": g.size(), "exposure": g["dev_day"].nunique()}).reset_index()
    panel = panel.rename(columns={"month_ist": "month"})
    panel["mi"] = panel["month"].map({m: i for i, m in enumerate(_MONTHS)})
    return panel.dropna(subset=["mi"])


def _transitions(panel: pd.DataFrame) -> pd.DataFrame:
    """Cell t→t+1 transitions: Δlog viol as outcome, this-month exposure as cause,
    next-month exposure as the lead (placebo-of-time) regressor."""
    wide_v = panel.pivot(index="h3_r10", columns="mi", values="viol")
    wide_e = panel.pivot(index="h3_r10", columns="mi", values="exposure")
    rows = []
    months = sorted(panel["mi"].unique())
    for t in months[:-1]:
        if t + 1 not in wide_v.columns:
            continue
        v_t, v_t1 = wide_v.get(t), wide_v.get(t + 1)
        e_t = wide_e.get(t)
        e_t2 = wide_e.get(t + 2) if (t + 2) in wide_e.columns else None   # lead exposure
        sub = pd.DataFrame({
            "h3_r10": wide_v.index,
            "v_t": v_t.to_numpy(), "v_t1": v_t1.to_numpy(),
            "exp_t": e_t.to_numpy(),
            "exp_lead": (e_t2.to_numpy() if e_t2 is not None else np.nan),
            "src_month": t,
        }).dropna(subset=["v_t", "v_t1", "exp_t"])
        rows.append(sub)
    tr = pd.concat(rows, ignore_index=True)
    tr["dlogv"] = np.log1p(tr["v_t1"]) - np.log1p(tr["v_t"])
    return tr


def _within_cell_demean(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Subtract each cell's own mean (absorbs the cell fixed effect α_z)."""
    out = df.copy()
    grp = out.groupby("h3_r10")
    for c in cols:
        out[c] = out[c] - grp[c].transform("mean")
    return out


def _twfe_beta(tr: pd.DataFrame, xcol: str, beta_only: bool = False) -> dict:
    """Two-way FE β of `xcol` on dlogv: cell FE via within-demean, month FE via
    dummies, SE cluster-robust by cell. `beta_only` skips the cluster SE (fast OLS=
    lstsq point estimate, used inside the placebo loop). Returns beta, se, CI, n."""
    d = tr.dropna(subset=[xcol, "dlogv"]).copy()
    if len(d) < 30 or d["h3_r10"].nunique() < 5:
        return {"beta": None, "note": "insufficient panel"}
    # month-transition dummies (drop first) for γ_t
    md = pd.get_dummies(d["src_month"].astype(int), prefix="m", drop_first=True).astype(float)
    cols = [xcol] + list(md.columns)
    design = pd.concat([d[["h3_r10", "dlogv"]].reset_index(drop=True),
                        d[[xcol]].reset_index(drop=True), md.reset_index(drop=True)], axis=1)
    dem = _within_cell_demean(design, ["dlogv"] + cols)        # absorb α_z
    X = dem[cols].to_numpy(float)
    y = dem["dlogv"].to_numpy(float)
    if beta_only or not _HAS_SM:
        beta = float(np.linalg.lstsq(X, y, rcond=None)[0][0])
        return {"beta": round(beta, 5)}
    model = sm.OLS(y, X).fit(cov_type="cluster",
                             cov_kwds={"groups": design["h3_r10"].to_numpy()})
    b, se = float(model.params[0]), float(model.bse[0])
    return {"beta": round(b, 5), "se": round(se, 5),
            "ci_low": round(b - 1.96 * se, 5), "ci_high": round(b + 1.96 * se, 5),
            "n_obs": int(len(d)), "n_cells": int(d["h3_r10"].nunique())}


def run() -> dict:
    ev = pd.read_parquet(C.DATA_PROC / "events_h3.parquet")
    panel = _build_panel(ev)

    # keep cells with enough history to enter the panel (≥ MIN tickets total)
    tot = panel.groupby("h3_r10")["viol"].sum()
    keep_cells = set(tot[tot >= C.CAUSAL_MIN_CELL_COUNT].index)
    panel = panel[panel["h3_r10"].isin(keep_cells)]

    tr = _transitions(panel)
    # standardise exposure (per-SD β is interpretable & scale-free)
    mu, sd = tr["exp_t"].mean(), tr["exp_t"].std(ddof=0)
    tr["exp_std"] = (tr["exp_t"] - mu) / (sd if sd > 0 else 1.0)
    tr["exp_lead_std"] = (tr["exp_lead"] - mu) / (sd if sd > 0 else 1.0)

    real = _twfe_beta(tr, "exp_std")
    lead = _twfe_beta(tr, "exp_lead_std")

    # --- placebo: shuffle exposure across cells WITHIN each month ----------- #
    rng = np.random.default_rng(C.CAUSAL_SEED)
    placebo_betas = []
    for _ in range(C.CAUSAL_PLACEBO_PERMUTATIONS):
        shuffled = tr.copy()
        shuffled["exp_std"] = (tr.groupby("src_month")["exp_std"]
                               .transform(lambda s: rng.permutation(s.to_numpy())))
        b = _twfe_beta(shuffled, "exp_std", beta_only=True).get("beta")
        if b is not None:
            placebo_betas.append(b)
    placebo_betas = np.asarray(placebo_betas, float)
    pb_mean = float(np.mean(placebo_betas)) if len(placebo_betas) else None
    pb_lo, pb_hi = (float(np.percentile(placebo_betas, 2.5)),
                    float(np.percentile(placebo_betas, 97.5))) if len(placebo_betas) else (None, None)

    real_b = real.get("beta")
    distinguishable = bool(real_b is not None and pb_lo is not None
                           and (real_b < pb_lo or real_b > pb_hi)
                           and abs(pb_mean) < C.CAUSAL_PLACEBO_ABS_MAX)

    out = {
        "design": ("cell×month two-way fixed-effects panel: Δlog(violations)_{t→t+1} "
                   "~ β·exposure_std_t + cell FE + month FE; SE cluster-robust by cell"),
        "estimand": "enforcement responsiveness (exposure_t → change in violations_{t+1})",
        "n_obs": real.get("n_obs"), "n_cells": real.get("n_cells"),
        "n_months": int(panel["mi"].nunique()),
        "beta": real_b, "se": real.get("se"),
        "ci_low": real.get("ci_low"), "ci_high": real.get("ci_high"),
        "beta_interpretation": ("change in log next-month violations per +1 SD of this-"
                                "month enforcement exposure, within cell, net of month shocks"),
        "placebo_beta_mean": round(pb_mean, 5) if pb_mean is not None else None,
        "placebo_ci": [round(pb_lo, 5), round(pb_hi, 5)] if pb_lo is not None else None,
        "placebo_permutations": int(len(placebo_betas)),
        "placebo_collapsed_to_zero": bool(pb_mean is not None and abs(pb_mean) < C.CAUSAL_PLACEBO_ABS_MAX),
        "real_distinguishable_from_placebo": distinguishable,
        "lead_beta": lead.get("beta"),
        "lead_note": ("effect of NEXT month's exposure on this transition's change; "
                      "≈0 supports parallel pre-trends / no anticipation"),
        "parallel_trends_note": ("only ~5 monthly transitions exist (Nov 2023–Apr 2024; "
                                 "Apr partial), so formal pre-trend testing is limited — "
                                 "we report a lead-exposure placebo as the trend diagnostic"),
        "caveat": ("Estimated from TICKET data: this is enforcement→future-violation "
                   "responsiveness, NOT parking→congestion. β<0 mixes deterrence with "
                   "mean-reversion and is not a clean causal effect without exogeneity."),
        "congestion_causal": {
            "status": "requires_live_eta_panel",
            "plan": ("cell×slot fixed-effects of MEASURED CongestionSeverity (live Mappls "
                     "ETA) on parking intensity + event study around enforcement clearances, "
                     "with placebo dates — drops in here once the route/ETA API is enabled"),
            "today": "route/ETA API blocked (product not enabled / quota); not faked",
        },
    }
    U.write_json(C.DATA_PROC / "causal.json", out)
    (C.REPORTS / "causal.txt").write_text(
        "\n".join(f"{k}: {v}" for k, v in out.items()) + "\n", encoding="utf-8")

    print(f"[10_causal] TWFE enforcement-responsiveness beta={real_b} "
          f"CI=[{real.get('ci_low')},{real.get('ci_high')}] "
          f"on {real.get('n_obs')} cell-months ({real.get('n_cells')} cells)")
    print(f"[10_causal] placebo beta_mean={out['placebo_beta_mean']} "
          f"band={out['placebo_ci']} -> real distinguishable={distinguishable}")
    print(f"[10_causal] lead(next-month exposure) beta={lead.get('beta')} (~0 desired) | "
          f"congestion-causal: {out['congestion_causal']['status']}")
    return out


if __name__ == "__main__":
    run()
