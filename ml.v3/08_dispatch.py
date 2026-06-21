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

try:
    import lightgbm as lgb
    _HAS_LGB = True
except Exception:                       # pragma: no cover
    _HAS_LGB = False

# LambdaMART challenger features (interpretable, all already in pic.parquet +
# a reachability term). Mirrors the M4 blend's signals: pressure, congestion,
# road context, blind-spot divergence, reachability.
LTR_FEATURES = ["intensity", "congestion_severity", "road_class_wt",
                "junction_share", "neighbor_pressure", "rank_divergence",
                "gistar_z", "reach_km"]
LTR_GRADES = 5                          # relevance grades 0..4 (qcut of pic_score)
LTR_LGBM = {"objective": "lambdarank", "n_estimators": 300, "learning_rate": 0.05,
            "num_leaves": 31, "min_child_samples": 20, "subsample": 0.9,
            "colsample_bytree": 0.9}


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


def _train_lambdamart(pic: pd.DataFrame, stations: pd.DataFrame) -> dict | None:
    """Train + PERSIST a LightGBM LambdaMART dispatch-reranker CHALLENGER (mirrors
    the v1 ml/pipeline/07b_reranker.py learning-to-rank model). Query groups =
    police stations; relevance grade = pic_score quantile (0..4). The SHIPPED
    dispatch score stays the transparent M4 config-weight blend — this model is a
    trained challenger kept for VISIBILITY/comparison, not used for dispatch.

    HONEST: ranks cells by modeled obstruction priority (never measured congestion);
    grouping is station-level, never per officer. Returns a manifest-metrics dict."""
    if not _HAS_LGB:
        print("[08_dispatch] lightgbm unavailable -> LambdaMART challenger skipped")
        return None
    df = pic[pic["police_station"].notna() &
             (pic["police_station"] != "No Police Station")].copy()
    if len(df) < 50 or df["police_station"].nunique() < 2:
        print("[08_dispatch] too few labelled cells -> LambdaMART skipped")
        return None

    # reachability: km to the NEAREST station centroid (0 when no stations resolved)
    if len(stations):
        SD = _haversine_matrix(df["lat"].to_numpy(float), df["lon"].to_numpy(float),
                               stations["lat"].to_numpy(float),
                               stations["lon"].to_numpy(float))
        df["reach_km"] = SD.min(axis=1)
    else:                                   # pragma: no cover
        df["reach_km"] = 0.0

    for col in LTR_FEATURES:                 # some context cols may be absent -> 0
        if col not in df.columns:
            df[col] = 0.0
    df = df.sort_values("police_station", kind="stable")
    # LightGBM rejects pandas-3.0 pyarrow-backed dtypes -> hand it clean numpy.
    Xdf = df[LTR_FEATURES].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    X = np.ascontiguousarray(Xdf.to_numpy(dtype="float64"))
    # relevance grade 0..4 from the pic_score percentile (the rank target)
    y = np.asarray(pd.qcut(df["pic_score"].rank(method="first"), LTR_GRADES,
                           labels=False, duplicates="drop"), dtype=int)
    groups = df.groupby("police_station", sort=True, observed=True).size().tolist()

    ranker = lgb.LGBMRanker(random_state=42, verbose=-1, **LTR_LGBM)
    ranker.fit(X, y, group=groups, eval_set=[(X, y)], eval_group=[groups],
               eval_at=[5, 10], eval_metric="ndcg")
    # in-fit NDCG (a CHALLENGER skill readout; shipped score is still the blend)
    ndcg = {}
    try:
        bs = ranker.best_score_ or {}
        vd = next(iter(bs.values()), {}) if bs else {}
        ndcg = {k: round(float(v), 4) for k, v in vd.items()}
    except Exception:                       # pragma: no cover
        ndcg = {}
    imp = dict(sorted(zip(LTR_FEATURES, ranker.feature_importances_.tolist()),
                      key=lambda kv: -kv[1]))

    import models_io as MIO                  # noqa: E402 (pipeline-local helper)
    MIO.save_lgb(ranker, "reranker_lambdamart.lgb")
    metrics = {"n_cells": int(len(df)), "n_groups": int(len(groups)),
               "grades": LTR_GRADES, **{f"fit_{k}": v for k, v in ndcg.items()}}
    MIO.register(
        "dispatch_reranker_lambdamart", model_type="LightGBM(LambdaMART)",
        file="reranker_lambdamart.lgb", features=LTR_FEATURES, metrics=metrics,
        params=LTR_LGBM, trained_at=None,
        notes=("CHALLENGER learning-to-rank model (query groups = police stations, "
               "relevance = pic_score quantile). The SHIPPED dispatch score remains "
               "the transparent M4 config-weight blend in api/clearlane/v3.py + "
               "ml.v3/config.RERANK_WEIGHTS; this model is kept for visibility only. "
               "Ranks modeled obstruction priority, never measured congestion; "
               "station-level, never per officer."))
    print(f"[08_dispatch] LambdaMART challenger: {len(df):,} cells / {len(groups)} "
          f"stations · fit ndcg={ndcg or 'n/a'} -> models/reranker_lambdamart.lgb")
    return {"file": "reranker_lambdamart.lgb", "n_cells": int(len(df)),
            "n_groups": int(len(groups)), "ndcg": ndcg, "top_importance": imp}


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

    # M4 reranker stays the SHIPPED transparent blend; additionally train + save a
    # LightGBM LambdaMART challenger (for visibility — never used for the shipped score).
    try:
        ltr = _train_lambdamart(pic, stations)
    except Exception as e:                   # pragma: no cover - best-effort
        print(f"[08_dispatch] LambdaMART challenger skipped: {type(e).__name__}: {e}")
        ltr = None

    metrics = {"solver": solver, "officers": C.DISPATCH_OFFICERS,
               "candidates": int(len(cand)), "demand_cells": int(len(demand)),
               "coverage_radius_km": C.DISPATCH_COVER_RADIUS_KM,
               "covered_pic": round(covered, 2), "covered_pct": plan["covered_pct"],
               "random_baseline_pic": round(rand_mean, 2),
               "uplift_vs_random": round(covered / rand_mean, 2) if rand_mean else None,
               "coverage_source": "haversine-proxy (isochrone when API live)",
               "reranker": {"shipped": "M4 transparent config-weight blend "
                            "(RERANK_WEIGHTS, served by api/clearlane/v3.py)",
                            "challenger": ltr}}
    U.write_json(C.DATA_PROC / "dispatch_plan.json", plan)
    U.write_json(C.DATA_PROC / "dispatch_metrics.json", metrics)

    print(f"[08_dispatch] {solver} · {C.DISPATCH_OFFICERS} officers cover "
          f"{plan['covered_pct']}% of PIC ({covered:.0f}/{total_pic:.0f})")
    print(f"[08_dispatch] vs random baseline {rand_mean:.0f} -> uplift "
          f"{metrics['uplift_vs_random']}× · stations routed={len(plan['routes'])}")
    return metrics


if __name__ == "__main__":
    run()
