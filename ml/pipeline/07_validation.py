"""
Stage 07 — validation = our credibility.

  * Sensitivity: perturb the blend weights and the severity/vehicle tables by
    ±20% over ~40 configs; report top-20 overlap (expect 80–96%) and Spearman on
    the top-50 (expect ≥0.89). This is the answer to "why these weights?".
  * Persistence backtest: rank zones on Nov–Jan, test on Feb–Apr; report Spearman
    (expect ≈0.79) and % of top-quartile zones that persist (≈80%). Proves the
    hotspots are structural, not noise.
  * Forecaster metrics are produced in stage 05 and surfaced together here.
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

rng = np.random.default_rng(C.SENSITIVITY_RANDOM_STATE)


def _baseline_priority(ev, B, Cp):
    A_raw = ev.groupby("superzone_id", observed=True)["event_weight"].sum()
    A = U.percentile_norm(A_raw)
    w = C.PRIORITY_WEIGHTS
    return (w["A"] * A + w["B"] * B + w["C"] * Cp).rename("priority")


def _sensitivity(ev, z):
    # per-zone B and C are independent of the perturbed tables — reuse them
    B = z.set_index("superzone_id")["B"]
    Cp = z.set_index("superzone_id")["C"]

    base = _baseline_priority(ev, B, Cp).sort_values(ascending=False)
    base_rank = base.rank(ascending=False)
    base_top20 = set(base.head(20).index)
    base_top50 = list(base.head(50).index)

    sev_vals = sorted(ev["row_severity"].unique())
    veh_vals = sorted(ev["vehicle_wt"].unique())
    p = C.SENSITIVITY_PERTURB

    overlaps, rhos = [], []
    for _ in range(C.SENSITIVITY_N_CONFIGS):
        # perturb blend weights and renormalize
        wA = C.PRIORITY_WEIGHTS["A"] * (1 + rng.uniform(-p, p))
        wB = C.PRIORITY_WEIGHTS["B"] * (1 + rng.uniform(-p, p))
        wC = C.PRIORITY_WEIGHTS["C"] * (1 + rng.uniform(-p, p))
        s = wA + wB + wC
        wA, wB, wC = wA / s, wB / s, wC / s
        # perturb severity & vehicle tables
        sev_map = {v: v * (1 + rng.uniform(-p, p)) for v in sev_vals}
        veh_map = {v: v * (1 + rng.uniform(-p, p)) for v in veh_vals}
        ew = (ev["row_severity"].map(sev_map) *
              ev["vehicle_wt"].map(veh_map) * ev["confidence_mult"])
        A_raw = ew.groupby(ev["superzone_id"]).sum()
        A = U.percentile_norm(A_raw)
        pr = (wA * A + wB * B + wC * Cp).sort_values(ascending=False)

        top20 = set(pr.head(20).index)
        overlaps.append(len(top20 & base_top20) / 20)
        pr_rank = pr.rank(ascending=False)
        rho = spearmanr(base_rank.loc[base_top50], pr_rank.loc[base_top50]).statistic
        rhos.append(float(rho))

    return {
        "n_configs": C.SENSITIVITY_N_CONFIGS,
        "perturbation": p,
        "top20_overlap_min": round(float(np.min(overlaps)) * 100, 1),
        "top20_overlap_mean": round(float(np.mean(overlaps)) * 100, 1),
        "top20_overlap_max": round(float(np.max(overlaps)) * 100, 1),
        "top50_spearman_mean": round(float(np.mean(rhos)), 3),
        "top50_spearman_min": round(float(np.min(rhos)), 3),
    }


def _cii_sensitivity(z):
    """Stress the Carriageway Impact Index: perturb the J/R/D blend ±20% and report
    top-20 stability, plus how much the flow-impact lens *diverges* from strategic
    priority (the divergence is the point — a lens that just echoes priority adds
    nothing). The flow-impact components are precomputed per zone in stage 04."""
    base_raw = z.set_index("superzone_id")["flow_impact_raw"]
    base_sorted = base_raw.sort_values(ascending=False)
    base_top20 = set(base_sorted.head(20).index)
    base_rank = base_raw.rank(ascending=False)
    top50 = list(base_sorted.head(50).index)
    comp = z.set_index("superzone_id")[["cii_junction", "cii_road", "cii_demand",
                                        "pressure_raw"]]
    lo, hi = C.CII_CLIP
    p = C.SENSITIVITY_PERTURB

    overlaps, rhos = [], []
    for _ in range(C.SENSITIVITY_N_CONFIGS):
        wj = C.CII_WEIGHTS["junction"] * (1 + rng.uniform(-p, p))
        wr = C.CII_WEIGHTS["road_class"] * (1 + rng.uniform(-p, p))
        wd = C.CII_WEIGHTS["demand"] * (1 + rng.uniform(-p, p))
        s = wj + wr + wd
        wj, wr, wd = wj / s, wr / s, wd / s
        m = (wj * comp["cii_junction"] + wr * comp["cii_road"] + wd * comp["cii_demand"])
        mult = (lo + m * (hi - lo)).clip(lo, hi)
        raw = (comp["pressure_raw"] * mult).sort_values(ascending=False)
        overlaps.append(len(set(raw.head(20).index) & base_top20) / 20)
        rho = spearmanr(base_rank.loc[top50],
                        raw.rank(ascending=False).loc[top50]).statistic
        rhos.append(float(rho))

    pr_top50 = set(z.sort_values("priority", ascending=False).head(50)["superzone_id"])
    cii_top50 = set(base_sorted.head(50).index)
    return {
        "n_configs": C.SENSITIVITY_N_CONFIGS,
        "perturbation": p,
        "top20_overlap_min": round(float(np.min(overlaps)) * 100, 1),
        "top20_overlap_mean": round(float(np.mean(overlaps)) * 100, 1),
        "top50_spearman_mean": round(float(np.mean(rhos)), 3),
        "divergence_vs_priority_top50": len(cii_top50 - pr_top50),
        "note": ("Flow-Impact is a MODELED proxy from static road context "
                 "(junction tag, road class, metro/commercial proximity) — "
                 "NOT a measurement of congestion."),
    }


def _persistence(ev):
    tr = (ev[ev["month_ist"].isin(C.BACKTEST_TRAIN_MONTHS)]
          .groupby("superzone_id", observed=True)["event_weight"].sum())
    te = (ev[ev["month_ist"].isin(C.BACKTEST_TEST_MONTHS)]
          .groupby("superzone_id", observed=True)["event_weight"].sum())
    both = pd.concat([tr.rename("train"), te.rename("test")], axis=1).fillna(0)
    both = both[both["train"] > 0]                 # zones active in train window
    rho = float(spearmanr(both["train"], both["test"]).statistic)

    q_tr = both["train"].quantile(0.75)
    q_te = both["test"].quantile(0.75)
    top_tr = both["train"] >= q_tr
    persist = ((both["test"] >= q_te) & top_tr).sum() / max(top_tr.sum(), 1)
    return {
        "train_months": C.BACKTEST_TRAIN_MONTHS,
        "test_months": C.BACKTEST_TEST_MONTHS,
        "n_zones": int(len(both)),
        "spearman": round(rho, 3),
        "top_quartile_persistence_pct": round(float(persist) * 100, 1),
    }


def run():
    ev = pd.read_parquet(C.DATA_PROC / "events_clean.parquet")
    z = pd.read_parquet(C.DATA_PROC / "zone_scores.parquet")

    sens = _sensitivity(ev, z)
    cii = _cii_sensitivity(z)
    pers = _persistence(ev)
    try:
        import json
        fc = json.loads((C.DATA_PROC / "forecaster_metrics.json").read_text())
    except Exception:
        fc = {}

    out = {"sensitivity": sens, "cii": cii, "persistence": pers, "forecaster": fc}
    U.write_json(C.DATA_PROC / "validation.json", out)

    lines = ["ClearLane — validation report (stage 07)", "=" * 48, "",
             "SENSITIVITY (±20% on blend + severity/vehicle tables):"]
    lines += [f"  {k}: {v}" for k, v in sens.items()]
    lines += ["", "CARRIAGEWAY IMPACT INDEX (±20% on J/R/D blend; modeled proxy):"]
    lines += [f"  {k}: {v}" for k, v in cii.items()]
    lines += ["", "PERSISTENCE BACKTEST (train Nov–Jan, test Feb–Apr):"]
    lines += [f"  {k}: {v}" for k, v in pers.items()]
    lines += ["", "FORECASTER (held-out, real future-pressure target):"]
    lines += [f"  {k}: {v}" for k, v in fc.items() if k != "shap_importance"]
    (C.REPORTS / "validation.txt").write_text("\n".join(lines) + "\n")

    print(f"[07_validation] sensitivity top-20 overlap "
          f"{sens['top20_overlap_min']}–{sens['top20_overlap_max']}% "
          f"(expect 80–96%) · top-50 Spearman {sens['top50_spearman_mean']} (expect ≥0.89)")
    print(f"[07_validation] CII top-20 stability {cii['top20_overlap_mean']}% · "
          f"{cii['divergence_vs_priority_top50']}/50 flow-impact zones diverge from priority")
    print(f"[07_validation] persistence Spearman {pers['spearman']} "
          f"(target {C.SELF_CHECK_TARGETS['backtest_spearman']}) · "
          f"top-quartile persist {pers['top_quartile_persistence_pct']}%")
    return out


if __name__ == "__main__":
    run()
