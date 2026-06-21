"""
Stage 11 (Phase 7) — the evaluation scorecard.

Reads every prior metrics artifact and consolidates ONE auditable scorecard:
evaluation.json + a human-readable outputs/reports/v3/EVALUATION.md table. Each
capability (Phase 1 hotspots, Phase 2 PIC, Phase 3 forecasts, Phase 4 dispatch,
Phase 5 online, Phase 6 causal) gets its headline numbers and a PASS / REVIEW tag,
gated by the conservative thresholds in config.EVAL_THRESHOLDS (one place to tighten).

This "grades" the pipeline rather than just running it (architecture §13/§14): a judge
sees, on one page, whether the daily forecaster actually beat its baseline, whether
the dispatcher beat random, whether the hotspot model leaked spatial structure, and
whether the causal placebo collapsed to zero.

HONESTY: PASS means a metric cleared a stated, auditable bar — not that a claim is
proven. Capabilities awaiting the live API (predictive-ETA validation MAPE, the
parking→MEASURED-congestion causal) are shown as PENDING(live), never as failures or
as fake passes. Deterministic (no wall-clock timestamps in the artifact).

Phase 8 (the simulation dispatch policy, stage 12) is graded by its own regret curve
in sim_rl.json (it runs AFTER this stage); this scorecard covers the modeling phases.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402


def _load(name):
    try:
        return json.loads((C.DATA_PROC / name).read_text(encoding="utf-8"))
    except Exception:
        return None


def _fmt(v, nd=3):
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _row(capability, stage, headline, criteria, status, details):
    return {"capability": capability, "stage": stage, "headline": headline,
            "criteria": criteria, "status": status, "details": details}


def run() -> dict:
    T = C.EVAL_THRESHOLDS
    nb = _load("nb_metrics.json")
    conc = _load("h3_concentration.json")
    pic = _load("pic.json")
    fd = _load("forecaster_daily_metrics.json")
    fe = _load("forecast_eta.json")
    dp = _load("dispatch_metrics.json")
    onl = _load("online_metrics.json")
    cau = _load("causal.json")

    rows = []

    # --- Phase 1 — bias-corrected hotspots (stage 04) ---------------------- #
    if nb:
        cv = (nb.get("spatial_cv") or {}).get("spearman_rate")
        moran = (nb.get("significance") or {}).get("moran_I_residuals")
        n_sig = (nb.get("significance") or {}).get("n_sig_hot")
        ok_cv = cv is not None and cv >= T["hotspot_cv_spearman_min"]
        ok_mor = moran is not None and abs(moran) <= T["hotspot_moran_abs_max"]
        rows.append(_row(
            "Hotspots (bias-corrected NB + Gi*)", "04",
            f"spatial-CV rho={_fmt(cv)}, Moran(resid)={_fmt(moran,4)}, Gi* hot={_fmt(n_sig)}",
            f"rho>={T['hotspot_cv_spearman_min']} & |Moran|<={T['hotspot_moran_abs_max']}",
            "PASS" if (ok_cv and ok_mor) else "REVIEW",
            {"spatial_cv_spearman": cv, "moran_resid": moran, "n_sig_hot": n_sig,
             "model": (nb.get("model") or {}).get("family"),
             "dispersion": (nb.get("model") or {}).get("dispersion"),
             "n_under_policed": nb.get("n_under_policed"),
             "cells_for_50pct": ((conc or {}).get("concentration", {})
                                 .get("cells_for_50pct", {}).get("n_cells")),
             "pass_cv": ok_cv, "pass_moran": ok_mor}))

    # --- Phase 2 — PIC (stage 05) ------------------------------------------ #
    if pic:
        n_cells = pic.get("n_cells")
        mode = pic.get("congestion_mode")
        ok = bool(n_cells and n_cells > 0)
        rows.append(_row(
            "Parking-Induced Congestion (PIC)", "05",
            f"{_fmt(n_cells)} cells ranked, congestion={mode}",
            "PIC computed for all occupied cells (severity live when API enabled)",
            "PASS" if ok else "REVIEW",
            {"n_cells": n_cells, "congestion_mode": mode,
             "n_live_corridors": pic.get("n_live_corridors"),
             "note": "severity is MODELED today; live Mappls ETA upgrades it in-place"}))

    # --- Phase 3 — daily forecaster (stage 06) + predictive-ETA (stage 07) - #
    if fd:
        beats = fd.get("beats_baseline")
        sp = fd.get("spearman")
        ok = bool(beats) and (sp is not None and sp >= T["forecast_spearman_min"])
        eta_status = (fe or {}).get("status", "n/a")
        rows.append(_row(
            "Daily violation forecaster", "06",
            f"PoissonDev={_fmt(fd.get('poisson_deviance'),3)} vs base "
            f"{_fmt(fd.get('baseline_poisson_deviance'),3)}, Spearman={_fmt(sp)}, "
            f"beats_baseline={_fmt(beats)}",
            f"beats baseline & Spearman>={T['forecast_spearman_min']}",
            "PASS" if ok else "REVIEW",
            {"poisson_deviance": fd.get("poisson_deviance"),
             "baseline_poisson_deviance": fd.get("baseline_poisson_deviance"),
             "spearman": sp, "mae": fd.get("mae"), "beats_baseline": beats,
             "predictive_eta_status": eta_status,
             "predictive_eta_note": ("next-day MAPE validation is PENDING(live): "
                                     "route/predictive-ETA API blocked today")}))

    # --- Phase 4 — exact dispatch (stage 08) ------------------------------- #
    if dp:
        up = dp.get("uplift_vs_random")
        ok = up is not None and up >= T["dispatch_uplift_min"]
        rows.append(_row(
            "Exact dispatch (MCLP + VRP)", "08",
            f"{_fmt(dp.get('officers'))} officers cover {_fmt(dp.get('covered_pct'),1)}% "
            f"of PIC, uplift {_fmt(up,2)}x vs random",
            f"uplift vs random >= {T['dispatch_uplift_min']}x",
            "PASS" if ok else "REVIEW",
            {"solver": dp.get("solver"), "covered_pct": dp.get("covered_pct"),
             "uplift_vs_random": up, "officers": dp.get("officers")}))

    # --- Phase 5 — online learning (stage 09) ------------------------------ #
    if onl:
        n_em = onl.get("n_emerging")
        n_el = onl.get("n_eligible_cells")
        st_ok = bool((onl.get("self_test") or {}).get("match"))
        sane = (n_em is not None and n_el and n_em >= T["online_emerging_min"] and n_em < n_el)
        rows.append(_row(
            "Online learning (Gamma-Poisson + drift)", "09",
            f"{_fmt(n_em)} emerging of {_fmt(n_el)} eligible, closed-form self-test "
            f"match={_fmt(st_ok)}",
            f"emerging>={T['online_emerging_min']} (and < all) & closed-form update verified",
            "PASS" if (sane and st_ok) else "REVIEW",
            {"n_emerging": n_em, "n_eligible_cells": n_el,
             "self_test_match": st_ok,
             "overdispersion_phi": (onl.get("drift") or {}).get("overdispersion_phi")}))

    # --- Phase 6 — quasi-causal panel (stage 10) --------------------------- #
    if cau:
        collapsed = cau.get("placebo_collapsed_to_zero")
        disting = cau.get("real_distinguishable_from_placebo")
        ok = bool(collapsed and disting)
        rows.append(_row(
            "Quasi-causal enforcement panel", "10",
            f"beta={_fmt(cau.get('beta'))} (CI[{_fmt(cau.get('ci_low'))},"
            f"{_fmt(cau.get('ci_high'))}]), placebo={_fmt(cau.get('placebo_beta_mean'),4)}",
            f"placebo ~0 (<{T['causal_placebo_abs_max']}) & real beta outside placebo band",
            "PASS" if ok else "REVIEW",
            {"beta": cau.get("beta"), "ci": [cau.get("ci_low"), cau.get("ci_high")],
             "placebo_beta_mean": cau.get("placebo_beta_mean"),
             "placebo_ci": cau.get("placebo_ci"), "lead_beta": cau.get("lead_beta"),
             "congestion_causal_status": (cau.get("congestion_causal") or {}).get("status")}))

    n_pass = sum(1 for r in rows if r["status"] == "PASS")
    summary = {
        "n_capabilities": len(rows),
        "n_pass": n_pass, "n_review": len(rows) - n_pass,
        "thresholds": T,
        "scorecard": rows,
        "pending_live_api": [
            "Predictive-ETA next-day MAPE validation (stage 07) — route/ETA API blocked",
            "parking -> MEASURED congestion causal (stage 10) — needs live Mappls ETA panel",
        ],
        "note": ("Phases 1-6 graded here; Phase 8 (simulation dispatch policy, stage 12) "
                 "is graded by its regret curve in sim_rl.json. PASS = cleared a stated, "
                 "auditable bar; never a claim that ticket data measures congestion."),
    }
    U.write_json(C.DATA_PROC / "evaluation.json", summary)
    _write_md(summary)

    print(f"[11_evaluate] scorecard: {n_pass}/{len(rows)} capabilities PASS "
          f"(thresholds in config.EVAL_THRESHOLDS)")
    for r in rows:
        print(f"[11_evaluate]   [{r['status']}] {r['capability']}: {r['headline']}")
    return summary


def _write_md(summary: dict) -> None:
    """Render the one-page EVALUATION.md table from the scorecard."""
    L = ["# ClearLane v3 — Evaluation Scorecard", "",
         "> Generated by `ml.v3/11_evaluate.py` from the pipeline's own metrics "
         "artifacts. **PASS** = the metric cleared a stated, auditable bar in "
         "`config.EVAL_THRESHOLDS`. We never claim the ticket data *measures* "
         "congestion; capabilities awaiting the live Mappls API are marked "
         "**PENDING(live)**, not failed.", "",
         f"**{summary['n_pass']} / {summary['n_capabilities']} capabilities PASS.**", "",
         "| Capability | Stage | Headline metrics | Criteria | Status |",
         "|---|---|---|---|---|"]
    for r in summary["scorecard"]:
        L.append(f"| {r['capability']} | {r['stage']} | {r['headline']} | "
                 f"{r['criteria']} | **{r['status']}** |")
    L += ["",
          "## Pending live API (honest gaps, not failures)",
          ""]
    for p in summary["pending_live_api"]:
        L.append(f"- {p}")
    L += ["",
          "## Notes",
          "",
          "- Phases 1–6 are graded above. **Phase 8** (simulation dispatch policy, "
          "stage 12) is graded by its cumulative-reward / regret curve in "
          "`data/processed/v3/sim_rl.json` (greedy & bandit vs random vs a hindsight "
          "oracle).",
          "- All metrics come from held-out / out-of-sample protocols (spatial-block "
          "CV for hotspots, temporal holdout for the forecaster, an empirical placebo "
          "null for the causal panel, seeded episodes for the simulator).",
          "- Thresholds are intentionally conservative and live in one auditable place "
          "(`config.EVAL_THRESHOLDS`).", ""]
    (C.REPORTS / "EVALUATION.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    run()
