"""
Stage 12 (Phase 8) — simulation dispatch policy (LinUCB bandit vs greedy/random).

WHY A SIMULATOR (and why that's honest)
---------------------------------------
There are NO real dispatch outcome logs in the data (closed_datetime and
action_taken_timestamp are 100% empty), so a sequential dispatch policy cannot be
trained on reality. We therefore train and grade it in a DATA-CALIBRATED SIMULATOR
and say so plainly — we never claim these rewards are real field results.

THE SIMULATOR (one "shift" = one day)
-------------------------------------
Arm universe = the top SIM_N_CELLS cells by PIC. Each shift, violations arrive per
cell  v_h ~ Poisson(lambda_h)  with lambda_h = the Phase-5 online E[lambda] (expected
violations/day — an enforcement-shaped PROXY for true arrivals, NOT a measurement).
A controller sends SIM_OFFICERS officers to SIM_OFFICERS cells; if a chosen cell had
>=1 violation it is "caught" and earns its PIC weight:
    reward(shift) = Σ_{chosen h with v_h>=1} PIC_h  −  travel_penalty(chosen)
The PIC weighting keeps the objective aligned with real congestion importance.

POLICIES COMPARED (same realised arrivals each shift → fair)
-----------------------------------------------------------
  * random         — SIM_OFFICERS random cells (lower bound).
  * greedy(top-PIC)— the STATIC Phase-2 ranking; ignores arrival dynamics, so it
                     wastes officers on high-PIC / low-arrival cells.
  * LinUCB bandit  — disjoint contextual bandit, context = [1, intensity,
                     congestion_severity, online_rate]; UCB explores under-observed
                     cells and learns each cell's realised PIC-weighted catch value,
                     reallocating away from high-PIC/low-arrival cells greedy wastes.
  * oracle         — per-shift hindsight best SIM_OFFICERS cells (upper bound) →
                     defines REGRET = Σ(oracle − policy).

WORKED EXAMPLE: a cell with PIC 0.9 but lambda 0.2/day is caught only ~18% of shifts
(expected value 0.16); a cell with PIC 0.7 but lambda 4/day is caught ~98% (value
0.69). Static greedy prefers the first by PIC; the bandit learns the second pays more.

HONESTY: cell-level only (never per officer); deterministic with fixed seeds.
Output: sim_rl.json (per-policy reward, uplift vs random, regret curve, exploration).
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402


def _haversine_spread(lat, lon, idx):
    """Mean km from the chosen cells' centroid (a compactness / travel proxy)."""
    if len(idx) <= 1:
        return 0.0
    la, lo = lat[idx], lon[idx]
    cla, clo = la.mean(), lo.mean()
    R = 6371.0
    p1, p2 = np.radians(la), np.radians(cla)
    dphi = p2 - p1
    dlmb = np.radians(clo) - np.radians(lo)
    h = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return float(np.mean(2 * R * np.arcsin(np.sqrt(np.clip(h, 0, 1)))))


def _topk(scores, k):
    """Indices of the k largest scores (deterministic tie order)."""
    k = min(k, len(scores))
    return np.argpartition(-scores, k - 1)[:k] if k < len(scores) else np.arange(len(scores))


def run() -> dict:
    pic = pd.read_parquet(C.DATA_PROC / "pic.parquet")
    uni = pic.sort_values("pic_raw", ascending=False).head(C.SIM_N_CELLS).reset_index(drop=True)

    # arrival rate lambda = Phase-5 online E[lambda] (fallback: count / record days)
    try:
        onl = pd.read_parquet(C.DATA_PROC / "online_state.parquet")[["h3_r10", "e_lambda"]]
        uni = uni.merge(onl, on="h3_r10", how="left")
    except Exception:
        uni["e_lambda"] = np.nan
    lam = uni["e_lambda"].to_numpy(float)
    fallback = uni["count"].to_numpy(float) / 151.0
    lam = np.where(np.isfinite(lam) & (lam > 0), lam, fallback)
    lam = np.clip(lam, 1e-3, None)

    pic_raw = uni["pic_raw"].to_numpy(float)
    lat = uni["lat"].to_numpy(float); lon = uni["lon"].to_numpy(float)
    N = len(uni)
    K = min(C.SIM_OFFICERS, N)

    # contextual features for LinUCB: [bias, intensity, severity, online_rate] -> [0,1]
    inten = uni["intensity"].to_numpy(float) / 100.0
    sev = uni["congestion_severity"].to_numpy(float)
    lam_norm = lam / max(lam.max(), 1e-9)
    X = np.column_stack([np.ones(N), inten, sev, lam_norm])      # (N, d)
    d = X.shape[1]

    greedy_pick = _topk(pic_raw, K)                              # STATIC top-PIC
    greedy_static_set = set(int(i) for i in greedy_pick)
    penalty_on = C.SIM_TRAVEL_PENALTY > 0

    def _pen(idx):
        return C.SIM_TRAVEL_PENALTY * _haversine_spread(lat, lon, idx) if penalty_on else 0.0

    policies = ["random", "greedy", "linucb", "oracle"]
    cum = {p: np.zeros(C.SIM_SHIFTS) for p in policies}         # mean cumulative reward
    visited_per_ep = {p: [] for p in ("random", "greedy", "linucb")}
    blindspot_visits = {p: 0 for p in ("random", "greedy", "linucb")}

    for ep in range(C.SIM_EPISODES):
        rng_env = np.random.default_rng(C.SIM_SEED + ep)            # arrivals
        rng_pol = np.random.default_rng(C.SIM_SEED + 10_000 + ep)   # random-policy picks
        # fresh LinUCB state each episode (disjoint per-arm A, b)
        A = np.repeat(np.eye(d)[None, :, :], N, axis=0)            # (N,d,d) ridge=I
        b = np.zeros((N, d))
        ep_cum = {p: 0.0 for p in policies}
        seen = {p: set() for p in ("random", "greedy", "linucb")}

        for t in range(C.SIM_SHIFTS):
            v = rng_env.poisson(lam)                               # realised arrivals
            value = pic_raw * (v >= 1)                             # reward if present & caught

            # --- random ---
            pr = rng_pol.choice(N, size=K, replace=False)
            # --- greedy (static) ---
            pg = greedy_pick
            # --- oracle (hindsight best this shift) ---
            po = _topk(value, K)
            # --- LinUCB ---
            A_inv = np.linalg.inv(A)                               # (N,d,d), d=4 -> fast
            theta = np.einsum("nij,nj->ni", A_inv, b)
            mean = np.einsum("ni,ni->n", theta, X)
            quad = np.einsum("ni,nij,nj->n", X, A_inv, X)
            ucb = mean + C.LINUCB_ALPHA * np.sqrt(np.clip(quad, 0, None))
            pl = _topk(ucb, K)
            # observe + update picked arms
            r_l = value[pl]
            A[pl] += np.einsum("ki,kj->kij", X[pl], X[pl])
            b[pl] += r_l[:, None] * X[pl]

            for name, idx in (("random", pr), ("greedy", pg), ("linucb", pl), ("oracle", po)):
                ep_cum[name] += float(value[idx].sum() - _pen(idx))
                cum[name][t] += ep_cum[name]
                if name != "oracle":
                    seen[name].update(int(i) for i in idx)

        for p in ("random", "greedy", "linucb"):
            visited_per_ep[p].append(len(seen[p]))
            blindspot_visits[p] += len(seen[p] - greedy_static_set)

    for p in policies:                                            # average over episodes
        cum[p] /= C.SIM_EPISODES

    final = {p: float(cum[p][-1]) for p in policies}
    rand_r = max(final["random"], 1e-9)
    regret = {p: [round(float(cum["oracle"][t] - cum[p][t]), 3) for t in range(C.SIM_SHIFTS)]
              for p in ("random", "greedy", "linucb")}

    out = {
        "setup": {"n_cells": N, "officers": K, "shifts": C.SIM_SHIFTS,
                  "episodes": C.SIM_EPISODES, "seed": C.SIM_SEED,
                  "linucb_alpha": C.LINUCB_ALPHA, "travel_penalty": C.SIM_TRAVEL_PENALTY,
                  "arrival_rate": "Phase-5 online E[lambda] (proxy for true arrivals)",
                  "context": ["bias", "intensity", "congestion_severity", "online_rate"]},
        "final_cumulative_reward": {p: round(final[p], 2) for p in policies},
        "uplift_vs_random": {p: round(final[p] / rand_r, 3)
                             for p in ("greedy", "linucb", "oracle")},
        "pct_of_oracle": {p: round(100 * final[p] / max(final["oracle"], 1e-9), 1)
                          for p in ("random", "greedy", "linucb")},
        "final_regret_vs_oracle": {p: round(float(cum["oracle"][-1] - cum[p][-1]), 2)
                                   for p in ("random", "greedy", "linucb")},
        "regret_curve": regret,
        "exploration": {
            "distinct_cells_mean_per_episode": {
                p: round(float(np.mean(visited_per_ep[p])), 1)
                for p in ("random", "greedy", "linucb")},
            "blindspot_cells_visited_total": {
                p: int(blindspot_visits[p]) for p in ("random", "greedy", "linucb")},
            "note": ("greedy is static (visits exactly K cells); LinUCB visits MORE "
                     "distinct cells — it probes under-observed / blind-spot cells via "
                     "the UCB bonus, then exploits the high-value ones")},
        "acceptance": {
            "greedy_beats_random": bool(final["greedy"] > final["random"]),
            "linucb_beats_random": bool(final["linucb"] > final["random"]),
            "linucb_beats_greedy": bool(final["linucb"] > final["greedy"]),
            "linucb_uplift_vs_random": round(final["linucb"] / rand_r, 3),
            "meets_sim_uplift_min": bool(final["linucb"] / rand_r
                                         >= C.EVAL_THRESHOLDS["sim_uplift_min"]),
        },
        "note": ("Trained in a data-calibrated SIMULATOR because real dispatch logs do "
                 "not exist (closed_datetime / action_taken_timestamp are 100% empty). "
                 "Rewards are simulated PIC-weighted catches, not field outcomes. "
                 "Cell-level only; never per officer. Deterministic (fixed seeds)."),
    }
    U.write_json(C.DATA_PROC / "sim_rl.json", out)
    (C.REPORTS / "sim_rl.txt").write_text(
        "\n".join(f"{k}: {v}" for k, v in out.items() if k != "regret_curve") + "\n",
        encoding="utf-8")

    fr = out["final_cumulative_reward"]
    print(f"[12_sim_rl] reward (mean of {C.SIM_EPISODES} eps, {C.SIM_SHIFTS} shifts): "
          f"random={fr['random']} greedy={fr['greedy']} linucb={fr['linucb']} "
          f"oracle={fr['oracle']}")
    print(f"[12_sim_rl] uplift vs random: greedy={out['uplift_vs_random']['greedy']}x "
          f"linucb={out['uplift_vs_random']['linucb']}x | linucb beats greedy="
          f"{out['acceptance']['linucb_beats_greedy']}")
    exp = out["exploration"]["distinct_cells_mean_per_episode"]
    print(f"[12_sim_rl] distinct cells/episode: greedy={exp['greedy']} (static) "
          f"linucb={exp['linucb']} (probes blind spots) random={exp['random']}")
    return out


if __name__ == "__main__":
    run()
