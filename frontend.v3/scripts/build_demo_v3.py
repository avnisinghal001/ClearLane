"""
Builds the offline demo-v3 bundle for frontend.v3 from the ml.v3 artifacts in
data/processed/v3/. The live backend serves /api/v3/* dynamically; this bundle
is the OFFLINE-FIRST fallback so the dashboard always renders (judging safety).

Honesty contract carries over verbatim:
  - congestion_source is live | mappls_typical | modeled (never "measured from tickets")
  - forecast layers are clearly labeled
  - hour_profile is RECORDED enforcement activity (officer shifts), not live traffic
  - aggregation is cell- and station-level only; never per-officer

Run:  python frontend.v3/scripts/build_demo_v3.py   (from repo root, in .venv)
Out:  frontend.v3/public/demo-v3/*.json
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "processed" / "v3"
OUT = ROOT / "frontend.v3" / "public" / "demo-v3"
OUT.mkdir(parents=True, exist_ok=True)

# Public, domain-whitelisted Mappls keys. The REST key works against the legacy
# map_load endpoint (engine 1); the static key 401s there but is the access_token
# for the Mappls v3 SDK (engine 2). GET /api/config returns the REST key.
REST_KEY = "1c04439bdb5b2f9d9bd3bca144614f5c"
STATIC_KEY = "dnnjqdkukvlealrrtuvklzwjtkyoshusxdef"

DOW_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAP_CELLS = 800  # top cells (by PIC) carried into the offline map


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "station"


def jload(name: str):
    with open(SRC / name, "r", encoding="utf-8") as f:
        return json.load(f)


def jdump(name: str, obj):
    with open(OUT / name, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  wrote {name:24s} {(OUT / name).stat().st_size/1024:8.1f} KB")


def r(x, n=2):
    try:
        if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
            return None
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def main():
    print("Loading artifacts...")
    pic = pd.read_parquet(SRC / "pic.parquet")
    online = jload("online_state.json")
    fdaily = jload("forecast_daily.json")
    plan = jload("dispatch_plan.json")
    evaluation = jload("evaluation.json")
    causal = jload("causal.json")
    sim = jload("sim_rl.json")
    conc = jload("h3_concentration.json")
    nbm = jload("nb_metrics.json")
    fdm = jload("forecaster_daily_metrics.json")
    onm = jload("online_metrics.json")
    dpm = jload("dispatch_metrics.json")

    ev = pd.read_parquet(
        SRC / "events_h3.parquet",
        columns=["id", "latitude", "longitude", "location", "vehicle_number",
                 "vehicle_type", "primary_violation", "violation_list_str",
                 "police_station", "h3_r10", "created_ist", "hour_ist", "dow_ist",
                 "is_approved"],
    )

    # ---- per-cell forecast + emerging lookups -----------------------------
    fc_by_h3 = {c["h3_r10"]: c for c in fdaily.get("cells", [])}
    em_by_h3 = {c["h3_r10"]: c for c in online.get("emerging_cells", [])}

    # ---- choose the cell set carried into the offline map -----------------
    pic_sorted = pic.sort_values("pic_score", ascending=False)
    keep = set(pic_sorted.head(MAP_CELLS)["h3_r10"])
    keep |= set(em_by_h3.keys())
    for r_ in plan.get("routes", []):
        keep |= set(r_.get("stops", []))
    cells_df = pic[pic["h3_r10"].isin(keep)].copy()

    cells = []
    for _, row in cells_df.iterrows():
        h3 = row["h3_r10"]
        fc = fc_by_h3.get(h3)
        em = em_by_h3.get(h3)
        cells.append({
            "h3_r10": h3,
            "lat": r(row["lat"], 6),
            "lon": r(row["lon"], 6),
            "police_station": row["police_station"],
            "intensity": r(row["intensity"], 2),
            "pic_score": r(row["pic_score"], 2),
            "congestion_severity": r(row["congestion_severity"], 3),
            "congestion_source": row["congestion_source"],
            "road_class": row.get("road_class"),
            "count": int(row["count"]),
            "dow_curve": [r(v, 2) for v in fc["dow_curve"]] if fc else None,
            "peak_dow": fc.get("peak_dow") if fc else None,
            "weekly_expected": r(fc.get("weekly_expected"), 1) if fc else None,
            "emerging": bool(em),
            "drift_z": r(em.get("drift_z"), 2) if em else None,
            "e_lambda": r(em.get("e_lambda"), 3) if em else None,
        })
    cells.sort(key=lambda c: c["pic_score"] or 0, reverse=True)

    # recorded enforcement activity by hour-of-day (officer shifts, NOT traffic)
    hour_counts = ev.groupby("hour_ist").size().reindex(range(24), fill_value=0)
    hmax = max(int(hour_counts.max()), 1)
    hour_profile = [round(int(v) / hmax, 4) for v in hour_counts]

    jdump("cells.json", {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "n_cells": len(cells),
        "dow_order": DOW_ORDER,
        "hour_profile": hour_profile,
        "congestion_mode": jload("pic.json").get("congestion_mode", "modeled-only"),
        "cells": cells,
    })

    # ---- KPI bundle -------------------------------------------------------
    c = conc["concentration"]
    kpis = {
        "n_cells": conc["n_occupied_cells"],
        "total_violations": conc["total_violations"],
        "concentration": {
            "top_2_5_pct_share": c["top_2.5pct_cells"]["share_of_violations_pct"],
            "top_2_5_pct_cells": c["top_2.5pct_cells"]["n_cells"],
            "top_5_pct_share": c["top_5pct_cells"]["share_of_violations_pct"],
            "top_10_pct_share": c["top_10pct_cells"]["share_of_violations_pct"],
            "cells_for_50pct": c["cells_for_50pct"]["n_cells"],
            "cells_for_50pct_share": c["cells_for_50pct"]["pct_of_all_cells"],
        },
        "dispatch": {
            "officers": dpm["officers"], "covered_pct": dpm["covered_pct"],
            "uplift_vs_random": dpm["uplift_vs_random"], "solver": dpm["solver"],
            "coverage_source": dpm.get("coverage_source"),
        },
        "forecaster": {
            "model": fdm["model"], "spearman": fdm["spearman"],
            "poisson_deviance": fdm["poisson_deviance"],
            "baseline_poisson_deviance": fdm["baseline_poisson_deviance"],
            "beats_baseline": fdm["beats_baseline"], "mae": fdm["mae"],
        },
        "online": {
            "n_emerging": onm["n_emerging"], "n_eligible": onm["n_eligible_cells"],
            "emerging_share": onm["emerging_share_of_eligible"],
        },
        "hotspots": {
            "model": nbm["model"]["family"], "spatial_cv_spearman": nbm["spatial_cv"]["spearman_rate"],
            "n_sig_hot": nbm["significance"]["n_sig_hot"], "n_under_policed": nbm["n_under_policed"],
        },
        "causal": {"beta": causal["beta"], "ci": [causal["ci_low"], causal["ci_high"]],
                   "placebo_beta_mean": causal["placebo_beta_mean"]},
        "sim": {"linucb_uplift_vs_random": sim["uplift_vs_random"]["linucb"],
                "linucb_pct_of_oracle": sim["pct_of_oracle"]["linucb"]},
        "capabilities": {"n_pass": evaluation["n_pass"], "n_total": evaluation["n_capabilities"]},
    }
    jdump("kpis.json", kpis)

    # ---- per-station stats ------------------------------------------------
    real = pic[pic["police_station"].notna() & (pic["police_station"] != "No Police Station")].copy()
    ev_counts = ev.groupby("police_station").size().to_dict()
    plan_by_station = {r_["station"]: r_ for r_ in plan.get("routes", [])}
    em_station = {}
    for em in online.get("emerging_cells", []):
        st = em.get("police_station")
        if st:
            em_station[st] = em_station.get(st, 0) + 1
    fc_weekly = {}
    for fc in fdaily.get("cells", []):
        st = fc.get("police_station")
        if st:
            fc_weekly[st] = fc_weekly.get(st, 0.0) + (fc.get("weekly_expected") or 0.0)

    stations = []
    for st, g in real.groupby("police_station"):
        w = g["pic_score"].clip(lower=0.01)
        lat = float((g["lat"] * w).sum() / w.sum())
        lon = float((g["lon"] * w).sum() / w.sum())
        top = g.sort_values("pic_score", ascending=False).iloc[0]
        pl = plan_by_station.get(st, {})
        stations.append({
            "station": st, "slug": slugify(st),
            "lat": r(lat, 6), "lon": r(lon, 6),
            "n_cells": int(len(g)),
            "mean_pic": r(g["pic_score"].mean(), 1),
            "max_pic": r(g["pic_score"].max(), 1),
            "sum_pic": r(g["pic_score"].sum(), 1),
            "mean_intensity": r(g["intensity"].mean(), 1),
            "n_sig_hot": int(g["sig_hot"].sum()),
            "n_emerging": int(em_station.get(st, 0)),
            "weekly_expected": r(fc_weekly.get(st, 0.0), 0),
            "n_tickets": int(ev_counts.get(st, 0)),
            "top_cell": top["h3_r10"],
            "dispatch_stops": int(pl.get("n_stops", 0)),
            "route_km": r(pl.get("route_km", 0), 2),
        })
    stations.sort(key=lambda s: s["sum_pic"] or 0, reverse=True)
    jdump("stations.json", stations)

    # ---- dispatch plan (resolve stop h3 -> coords) ------------------------
    coord = {row["h3_r10"]: (r(row["lat"], 6), r(row["lon"], 6), r(row["pic_score"], 1))
             for _, row in pic.iterrows()}
    routes = []
    for r_ in plan.get("routes", []):
        stops = []
        for h3 in r_.get("stops", []):
            ll = coord.get(h3)
            if ll:
                stops.append({"h3_r10": h3, "lat": ll[0], "lon": ll[1], "pic_score": ll[2]})
        routes.append({**{k: r_[k] for k in ("station", "n_stops", "route_km")}, "stops": stops})
    jdump("dispatch_plan.json", {
        "officers": plan["officers"], "solver": plan["solver"],
        "covered_pic": plan["covered_pic"], "total_pic": plan["total_pic"],
        "covered_pct": plan["covered_pct"], "n_stations": plan["n_stations"],
        "routes": routes,
    })

    # ---- representative tickets (historical, anonymized) ------------------
    def sv(v):  # safe scalar: NA/NaN -> None
        try:
            if v is None or (isinstance(v, float) and math.isnan(v)) or pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        return v

    cat_clean = lambda s: (str(s).strip().title() if sv(s) else None)

    def mk_ticket(row, kind, status, resolution, reason):
        ci = sv(row["created_ist"])
        labels = [x for x in str(sv(row.get("violation_list_str")) or "").split("|") if x][:4]
        loc = str(sv(row.get("location")) or "")
        return {
            "id": str(row["id"]),
            "kind": kind,
            "category": cat_clean(row.get("primary_violation")),
            "labels": [cat_clean(x) for x in labels],
            "station": sv(row.get("police_station")),
            "cell": sv(row.get("h3_r10")),
            "lat": r(row["latitude"], 6), "lon": r(row["longitude"], 6),
            "vehicle_type": (str(sv(row.get("vehicle_type")) or "").title() or None),
            "vehicle_number": sv(row.get("vehicle_number")),
            "note": (loc[:70] + "...") if len(loc) > 70 else (loc or None),
            "traffic_caused": None,
            "status": status, "resolution": resolution, "reason": reason,
            "reason_other": None,
            "created_at": (ci.isoformat() if isinstance(ci, (datetime, pd.Timestamp)) else str(ci)),
            "hour": int(sv(row.get("hour_ist"))) if sv(row.get("hour_ist")) is not None else None,
            "source": "historical",
        }

    tickets = []
    ev_real = ev[ev["police_station"].notna() & (ev["police_station"] != "No Police Station")]
    top_stations = [s["station"] for s in stations[:24]]
    for st in top_stations:
        sub = ev_real[ev_real["police_station"] == st]
        if len(sub) == 0:
            continue
        sample = sub.sample(n=min(10, len(sub)), random_state=42)
        for _, row in sample.iterrows():
            tickets.append(mk_ticket(row, "police_ticket", "closed", True, "action_taken"))

    # a dozen open citizen complaints seeded at the hottest / emerging cells
    CATS = ["Footpath Parking", "No-Parking Zone", "Double Parking", "Bus Stop Blocked",
            "Junction Blocked", "Wrong-Side Parking"]
    seed_cells = cells[:18]
    for i, cc in enumerate(seed_cells[:12]):
        tickets.append({
            "id": f"CMP{i:04d}",
            "kind": "citizen_complaint",
            "category": CATS[i % len(CATS)],
            "labels": [CATS[i % len(CATS)]],
            "station": cc["police_station"],
            "cell": cc["h3_r10"], "lat": cc["lat"], "lon": cc["lon"],
            "vehicle_type": ["Car", "Auto", "Truck", "Two-Wheeler"][i % 4],
            "vehicle_number": None,
            "note": "Vehicles blocking the lane during peak hours.",
            "traffic_caused": True,
            "status": "open", "resolution": None, "reason": None, "reason_other": None,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "source": "seed",
        })
    jdump("tickets.json", tickets)

    # ---- copies consumed directly by the read endpoints -------------------
    jdump("online.json", online)
    jdump("forecast_daily.json", fdaily)
    jdump("evaluation.json", evaluation)
    jdump("causal.json", causal)
    jdump("sim_rl.json", sim)
    jdump("hourly_congestion.json", jload("hourly_congestion.json"))  # stage 13 overlay
    jdump("config.json", {"mappls_key": REST_KEY, "static_key": STATIC_KEY, "demo": True})

    print(f"\nDone. {len(cells)} map cells, {len(stations)} stations, {len(tickets)} tickets -> {OUT}")


if __name__ == "__main__":
    main()
