"""
ClearLane — one command runs the whole pipeline and prints a self-check table
against the §2 verified targets, flagging any metric off by >15%.

    python run_all.py            # full pipeline + self-check + demo bundle
    python run_all.py --no-demo  # skip copying artifacts into the demo folder
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402

warnings.filterwarnings("ignore")

STAGES = [
    "01_clean", "02_superzones", "03_scores", "04_advanced",
    "05_forecaster", "06_timing_gap", "07_validation", "08_payload",
]

# artifacts copied into the frontend demo fallback (must stay small)
DEMO_ARTIFACTS = [
    "map_payload.json", "zones_detail.json", "evidence_points.json",
    "emerging.json", "forecast.json", "typology.json", "timing_gap.json",
    "coverage_curve.json", "stations.json", "validation.json",
    "search_index.json", "briefings.json", "offender_stat.json",
    "replay_frames.json",
]


def _load(stage):
    path = C.PKG_DIR / f"{stage}.py"
    spec = importlib.util.spec_from_file_location(stage, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _self_check():
    import pandas as pd
    z = pd.read_parquet(C.DATA_PROC / "zone_scores.parquet")
    timing = json.loads((C.DATA_PROC / "timing_gap.json").read_text())
    cov = json.loads((C.DATA_PROC / "coverage_curve.json").read_text())
    val = json.loads((C.DATA_PROC / "validation.json").read_text())
    ev_n = len(pd.read_parquet(C.DATA_PROC / "events_clean.parquet"))

    def cov_at(k):
        return next((c["coverage_pct"] for c in cov if c["k"] == k), None)

    actual = {
        "clean_rows": ev_n,
        "superzones": int(len(z)),
        "P1": int((z["tier"] == "P1").sum()),
        "P2": int((z["tier"] == "P2").sum()),
        "P3": int((z["tier"] == "P3").sum()),
        "P4": int((z["tier"] == "P4").sum()),
        "chronic": int(z["chronic"].sum()),
        "evening_blind_spot": int(z["evening_blind_spot"].sum()),
        "emerging": int(z["emerging"].sum()),
        "evening_peak_share_pct": timing["evening_peak_share_pct"],
        "coverage_top20_pct": cov_at(20),
        "coverage_top50_pct": cov_at(50),
        "backtest_spearman": val["persistence"]["spearman"],
    }

    print("\n" + "=" * 64)
    print(" SELF-CHECK vs §2 verified targets  (flag if off by >15%)")
    print("=" * 64)
    print(f" {'metric':<24}{'target':>10}{'actual':>10}{'Δ%':>8}  status")
    print("-" * 64)
    n_flag = 0
    for k, tgt in C.SELF_CHECK_TARGETS.items():
        act = actual.get(k)
        if act is None or tgt == 0:
            continue
        dpct = 100 * (act - tgt) / tgt
        flag = abs(dpct) > C.SELF_CHECK_TOLERANCE * 100
        n_flag += flag
        status = "⚠ INVESTIGATE" if flag else "ok"
        print(f" {k:<24}{tgt:>10}{act:>10}{dpct:>+7.1f}%  {status}")
    print("-" * 64)
    print(f" {'ALL WITHIN ±15%' if n_flag == 0 else f'{n_flag} METRIC(S) FLAGGED'}")
    print("=" * 64 + "\n")
    return n_flag


def _bundle_demo():
    for name in DEMO_ARTIFACTS:
        src = C.DATA_PROC / name
        if src.exists():
            shutil.copy2(src, C.DEMO_DIR / name)
    print(f"[run_all] bundled {len(DEMO_ARTIFACTS)} artifacts -> {C.DEMO_DIR}")


def main():
    t0 = time.time()
    for stage in STAGES:
        ts = time.time()
        print(f"\n>>> {stage}")
        _load(stage).run()
        print(f"    ({time.time() - ts:.1f}s)")
    n_flag = _self_check()
    if "--no-demo" not in sys.argv:
        _bundle_demo()
    print(f"[run_all] DONE in {time.time() - t0:.1f}s")
    sys.exit(1 if n_flag else 0)


if __name__ == "__main__":
    main()
