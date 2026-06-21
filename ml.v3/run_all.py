"""
ClearLane v3 — run the OFFLINE pipeline (Phase 0+1) and print a self-check.

    python ml.v3/run_all.py            # 01_clean -> 02_h3_bin -> 03_features -> 04_exposure_nb
    python ml.v3/run_all.py --only 04_exposure_nb   # re-run a single stage

Phase 1 produces the bias-corrected hotspot science. The live layer (Phase 2+:
collector, PIC, online learning, dispatch) plugs in later — see
`docs/ML_ARCHITECTURE.v3.md` §18.

Self-check: we HARD-gate only `clean_rows` (the one fully-verified number) within
±15% and exit non-zero if it drifts; every other Phase-1 number is printed as INFO
(we don't pre-commit exact targets for brand-new H3 artifacts).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402

warnings.filterwarnings("ignore")
for _s in (sys.stdout, sys.stderr):       # UTF-8 so Unicode prints don't crash on Windows
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

STAGES = ["01_clean", "02_h3_bin", "03_features", "04_exposure_nb",   # Phase 1
          "05_pic",                                                   # Phase 2
          "06_forecast_daily", "07_forecast_eta",                     # Phase 3
          "08_dispatch",                                              # Phase 4
          "09_online",                                                # Phase 5 (online learning)
          "10_causal",                                                # Phase 6 (quasi-causal panel)
          "11_evaluate",                                              # Phase 7 (scorecard)
          "12_sim_rl",                                                # Phase 8 (sim dispatch policy)
          "13_hourly_congestion"]                                     # Phase 9 (hourly congestion overlay)


def _load(stage):
    path = C.PKG_DIR / f"{stage}.py"
    spec = importlib.util.spec_from_file_location(stage, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _self_check() -> int:
    import pandas as pd
    ev_n = len(pd.read_parquet(C.DATA_PROC / "events_clean.parquet"))
    conc = json.loads((C.DATA_PROC / "h3_concentration.json").read_text())
    nb = json.loads((C.DATA_PROC / "nb_metrics.json").read_text())

    print("\n" + "=" * 66)
    print(" SELF-CHECK (HARD gate: clean_rows ±15%; rest = INFO)")
    print("=" * 66)
    tgt = C.SELF_CHECK_TARGETS["clean_rows"]
    dpct = 100 * (ev_n - tgt) / tgt
    flag = abs(dpct) > C.SELF_CHECK_TOLERANCE * 100
    print(f" clean_rows           target {tgt:>9,}  actual {ev_n:>9,}  "
          f"{dpct:+.1f}%  {'⚠ INVESTIGATE' if flag else 'ok'}")
    print("-" * 66)
    c50 = conc["concentration"]["cells_for_50pct"]
    cv = nb.get("spatial_cv", {})
    print(" INFO (Phase-1 model health):")
    print(f"   occupied H3 cells           : {conc['n_occupied_cells']:,}")
    print(f"   cells holding 50% of tickets : {c50['n_cells']:,} "
          f"({c50['pct_of_all_cells']}% of cells)")
    print(f"   model / dispersion / alpha   : {nb['model']['family']} / "
          f"{nb['model'].get('dispersion')} / {nb['model'].get('alpha')}")
    print(f"   Gi* significant hot cells    : {nb['significance'].get('n_sig_hot')}")
    print(f"   Moran's I on residuals       : {nb['significance'].get('moran_I_residuals')}"
          " (≈0 desired)")
    print(f"   spatial-CV Spearman          : {cv.get('spearman_rate')}")
    print(f"   spatial-CV precision@k       : {cv.get('precision_at_k')}")
    print(f"   under-policed (hidden) cells : {nb.get('n_under_policed')}")

    def _load(name):
        try:
            return json.loads((C.DATA_PROC / name).read_text())
        except Exception:
            return None
    pic = _load("pic.json"); fd = _load("forecaster_daily_metrics.json")
    fe = _load("forecast_eta.json"); dp = _load("dispatch_metrics.json")
    if pic:
        print(" INFO (Phase 2 — PIC):")
        print(f"   congestion mode / live corr  : {pic.get('congestion_mode')} / "
              f"{pic.get('n_live_corridors')}")
    if fd:
        print(" INFO (Phase 3 — forecasts):")
        print(f"   daily forecaster dev/baseline: {fd.get('poisson_deviance')} / "
              f"{fd.get('baseline_poisson_deviance')}  beats_baseline={fd.get('beats_baseline')}")
        print(f"   daily Spearman / MAE         : {fd.get('spearman')} / {fd.get('mae')}")
    if fe:
        print(f"   predictive-ETA (tomorrow)    : {fe.get('status')} "
              f"({fe.get('n_corridors')} corridors)")
    if dp:
        print(" INFO (Phase 4 — dispatch):")
        print(f"   {dp.get('solver')}: {dp.get('officers')} officers cover "
              f"{dp.get('covered_pct')}% of PIC")
        print(f"   uplift vs random placement   : {dp.get('uplift_vs_random')}×")

    onl = _load("online_metrics.json"); cau = _load("causal.json")
    sim = _load("sim_rl.json"); evl = _load("evaluation.json")
    if onl:
        st = onl.get("self_test", {})
        print(" INFO (Phase 5 — online learning):")
        print(f"   Gamma-Poisson emerging cells : {onl.get('n_emerging')} / "
              f"{onl.get('n_eligible_cells')} eligible "
              f"(φ={onl.get('drift', {}).get('overdispersion_phi')})")
        print(f"   closed-form update self-test : E[λ] {st.get('e_lambda_before')}→"
              f"{st.get('e_lambda_after')} match={st.get('match')}")
    if cau:
        print(" INFO (Phase 6 — quasi-causal enforcement panel):")
        print(f"   exposure→Δviol(t+1) β        : {cau.get('beta')} "
              f"CI[{cau.get('ci_low')}, {cau.get('ci_high')}]")
        print(f"   placebo β (≈0 desired)       : {cau.get('placebo_beta_mean')}  "
              f"distinguishable={cau.get('real_distinguishable_from_placebo')}")
    if sim:
        fr = sim.get("final_cumulative_reward", {}); acc = sim.get("acceptance", {})
        print(" INFO (Phase 8 — sim dispatch policy):")
        print(f"   reward random/greedy/linucb  : {fr.get('random')} / {fr.get('greedy')}"
              f" / {fr.get('linucb')} (oracle {fr.get('oracle')})")
        print(f"   linucb uplift vs random      : {acc.get('linucb_uplift_vs_random')}×"
              f"  beats_greedy={acc.get('linucb_beats_greedy')}")
    if evl:
        print(" INFO (Phase 7 — evaluation scorecard):")
        print(f"   capabilities PASS            : {evl.get('n_pass')}/"
              f"{evl.get('n_capabilities')}  → outputs/reports/v3/EVALUATION.md")
    print("=" * 66 + "\n")
    return int(flag)


def main():
    t0 = time.time()
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    for stage in STAGES:
        if only and stage != only:
            continue
        ts = time.time()
        print(f"\n>>> {stage}")
        _load(stage).run()
        print(f"    ({time.time() - ts:.1f}s)")
    n_flag = 0 if only else _self_check()
    print(f"[run_all] DONE in {time.time() - t0:.1f}s")
    sys.exit(1 if n_flag else 0)


if __name__ == "__main__":
    main()
