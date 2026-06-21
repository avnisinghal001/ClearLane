"""
Stage 08 (Phase 4) — exact dispatch optimisation.

Given the live PIC ranking (stage 05), decide WHERE to send a fixed number of
officers and IN WHAT ORDER:

  Tier 1 — coverage (MCLP).  Choose <= DISPATCH_OFFICERS patrol cells from the
      top-PIC candidates to MAXIMISE covered PIC, where a candidate "covers" a
      demand cell within DISPATCH_COVER_RADIUS_KM (offline proxy for a 15-min
      isochrone; Mappls isochrone when the API is enabled). Solved EXACTLY with
      PuLP/CBC (Church & ReVelle Maximal Covering Location Problem); greedy
      submodular fallback if the solver is unavailable.

  Tier 2 — route (VRP/TSP).  Order each station's assigned stops by nearest-
      neighbour from the station centroid (Mappls trip-optimization when live).

  Value check — compare MCLP covered PIC vs the average of random officer
      placements (DISPATCH_SIM_TRIALS) -> the uplift the optimiser buys.

Stations are located at the centroid of their own tickets (no station coordinates
exist in the data). Output: dispatch_plan.json + dispatch_metrics.json.
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
    import pulp
    _HAS_PULP = True
except Exception:                       # pragma: no cover
    _HAS_PULP = False


def _haversine_matrix(a_lat, a_lon, b_lat, b_lon):
    """Pairwise haversine (km) between point sets A (rows) and B (cols)."""
    R = 6371.0
    p1 = np.radians(a_lat)[:, None]; p2 = np.radians(b_lat)[None, :]
    dphi = p2 - p1
    dlmb = np.radians(b_lon)[None, :] - np.radians(a_lon)[:, None]
    h = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def _stations(ev):
    g = ev.groupby("police_station", observed=True)
    st = pd.DataFrame({"lat": g["latitude"].mean(), "lon": g["longitude"].mean(),
                       "tickets": g.size()})
    return st[st["tickets"] >= C.DISPATCH_MIN_STATION_TICKETS].copy()


def _mclp(cand, demand, covers_idx, officers):
    """Exact MCLP via PuLP; returns chosen candidate positional indices."""
    pic = demand["pic_raw"].to_numpy(float)
    prob = pulp.LpProblem("MCLP", pulp.LpMaximize)
    x = [pulp.LpVariable(f"x{j}", cat="Binary") for j in range(len(cand))]
    y = [pulp.LpVariable(f"y{h}", cat="Binary") for h in range(len(demand))]
    prob += pulp.lpSum(pic[h] * y[h] for h in range(len(demand)))
    for h in range(len(demand)):
        if covers_idx[h]:
            prob += y[h] <= pulp.lpSum(x[j] for j in covers_idx[h])
        else:
            prob += y[h] <= 0
    prob += pulp.lpSum(x) <= officers
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    return [j for j in range(len(cand)) if x[j].value() and x[j].value() > 0.5]


def _greedy(cand, demand, covered_by, officers):
    pic = demand["pic_raw"].to_numpy(float)
    chosen, covered = [], set()
    for _ in range(min(officers, len(cand))):
        best_j, best_gain = -1, -1.0
        for j in range(len(cand)):
            if j in chosen:
                continue
            gain = sum(pic[h] for h in covered_by[j] if h not in covered)
            if gain > best_gain:
                best_j, best_gain = j, gain
        if best_j < 0 or best_gain <= 0:
            break
        chosen.append(best_j); covered.update(covered_by[best_j])
    return chosen


def _covered_pic(idxs, covered_by, demand):
    pic = demand["pic_raw"].to_numpy(float)
    s = set()
    for j in idxs:
        s.update(covered_by[j])
    return float(pic[list(s)].sum()) if s else 0.0


def _route(station_ll, stops_df):
    """Nearest-neighbour order from the station centroid; returns stops + km."""
    pts = stops_df[["lat", "lon"]].to_numpy(float)
    ids = list(stops_df["h3_r10"])
    order, used = [], set()
    cur = np.array([station_ll])
    total = 0.0
    while len(order) < len(ids):
        d = _haversine_matrix(cur[:, 0], cur[:, 1], pts[:, 0], pts[:, 1])[0]
        d[list(used)] = np.inf
        nxt = int(np.argmin(d))
        total += float(d[nxt]); used.add(nxt); order.append(nxt)
        cur = np.array([pts[nxt]])
    return [ids[i] for i in order], round(total, 2)


def run() -> dict:
    pic = pd.read_parquet(C.DATA_PROC / "pic.parquet")
    ev = pd.read_parquet(C.DATA_PROC / "events_h3.parquet")
    stations = _stations(ev)

    demand = pic[pic["pic_raw"] > 0].sort_values("pic_raw", ascending=False).head(600).reset_index(drop=True)
    cand = demand.head(C.DISPATCH_CANDIDATES).reset_index(drop=True)

    D = _haversine_matrix(cand["lat"].to_numpy(float), cand["lon"].to_numpy(float),
                          demand["lat"].to_numpy(float), demand["lon"].to_numpy(float))
    within = D <= C.DISPATCH_COVER_RADIUS_KM
    covered_by = [list(np.where(within[j])[0]) for j in range(len(cand))]      # cand -> demand
    covers_idx = [list(np.where(within[:, h])[0]) for h in range(len(demand))]  # demand -> cand

    if _HAS_PULP:
        try:
            chosen = _mclp(cand, demand, covers_idx, C.DISPATCH_OFFICERS)
            solver = "MCLP/PuLP-CBC (exact)"
        except Exception as e:           # pragma: no cover
            chosen = _greedy(cand, demand, covered_by, C.DISPATCH_OFFICERS)
            solver = f"greedy (PuLP failed: {type(e).__name__})"
    else:
        chosen = _greedy(cand, demand, covered_by, C.DISPATCH_OFFICERS)
        solver = "greedy submodular"

    covered = _covered_pic(chosen, covered_by, demand)
    total_pic = float(demand["pic_raw"].sum())

    # value check: random officer placement baseline
    rng = np.random.default_rng(42)
    rand = [_covered_pic(list(rng.choice(len(cand), size=min(C.DISPATCH_OFFICERS, len(cand)),
            replace=False)), covered_by, demand) for _ in range(C.DISPATCH_SIM_TRIALS)]
    rand_mean = float(np.mean(rand)) if rand else 0.0

    # assign chosen stops to nearest station, then route per station
    chosen_df = cand.iloc[chosen].copy()
    plan = {"officers": C.DISPATCH_OFFICERS, "solver": solver,
            "covered_pic": round(covered, 2), "total_pic": round(total_pic, 2),
            "covered_pct": round(100 * covered / total_pic, 1) if total_pic else 0.0,
            "n_stations": int(len(stations)), "routes": []}
    if len(stations):
        s_lat = stations["lat"].to_numpy(float); s_lon = stations["lon"].to_numpy(float)
        SD = _haversine_matrix(chosen_df["lat"].to_numpy(float),
                               chosen_df["lon"].to_numpy(float), s_lat, s_lon)
        chosen_df["station"] = [stations.index[i] for i in SD.argmin(axis=1)]
        for stn, grp in chosen_df.groupby("station"):
            ll = (float(stations.loc[stn, "lat"]), float(stations.loc[stn, "lon"]))
            order, km = _route(ll, grp)
            plan["routes"].append({"station": str(stn), "n_stops": int(len(grp)),
                                   "route_km": km, "stops": order})
        plan["routes"].sort(key=lambda r: -r["n_stops"])

    metrics = {"solver": solver, "officers": C.DISPATCH_OFFICERS,
               "candidates": int(len(cand)), "demand_cells": int(len(demand)),
               "coverage_radius_km": C.DISPATCH_COVER_RADIUS_KM,
               "covered_pic": round(covered, 2), "covered_pct": plan["covered_pct"],
               "random_baseline_pic": round(rand_mean, 2),
               "uplift_vs_random": round(covered / rand_mean, 2) if rand_mean else None,
               "coverage_source": "haversine-proxy (isochrone when API live)"}
    U.write_json(C.DATA_PROC / "dispatch_plan.json", plan)
    U.write_json(C.DATA_PROC / "dispatch_metrics.json", metrics)

    print(f"[08_dispatch] {solver} · {C.DISPATCH_OFFICERS} officers cover "
          f"{plan['covered_pct']}% of PIC ({covered:.0f}/{total_pic:.0f})")
    print(f"[08_dispatch] vs random baseline {rand_mean:.0f} -> uplift "
          f"{metrics['uplift_vs_random']}× · stations routed={len(plan['routes'])}")
    return metrics


if __name__ == "__main__":
    run()
