"""
Stage 04 — advanced intelligence (the modules no other team will build).

  7.1  Enforcement-exposure bias correction   (zone-level only; never officers)
  7.2  Habitual-offender analysis             (chronic-demand vs transient)
  7.3  Enforcement responsiveness             (is enforcement even working?)
  7.4  Intervention recommendation engine     (concrete action per P1/P2 zone)
  7.5  Zone typology (KMeans) + temporal fingerprint

Every signal is computable from real columns. All output is aggregated to the
zone level — we never profile or rank individual officers.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402


# --------------------------------------------------------------------------- #
def _bias_correction(ev, z):
    """7.1 exposure = distinct officers × distinct active days; adjust pressure."""
    g = ev.groupby("superzone_id", observed=True)
    officers = g["created_by_id"].nunique().rename("n_officers")
    odays = g["date_ist"].nunique().rename("exposure_days")
    exp = pd.concat([officers, odays], axis=1)
    exp["exposure"] = (exp["n_officers"] * exp["exposure_days"]).clip(lower=1)
    z = z.join(exp, on="superzone_id")
    z["bias_adjusted"] = z["pressure_raw"] / (z["exposure"] ** C.EXPOSURE_ALPHA)
    z["bias_adjusted_score"] = U.percentile_norm(z["bias_adjusted"])
    z["bias_adjusted_rank"] = (z["bias_adjusted"].rank(ascending=False, method="min")
                               .astype(int))
    # divergence: under-recognized = bad relative to how little it's patrolled
    z["rank_divergence"] = z["rank"] - z["bias_adjusted_rank"]
    z["under_recognized"] = z["rank_divergence"] > 100
    return z


def _offenders(ev, z):
    """7.2 repeat-vehicle share per zone + city headline stat."""
    veh_global = ev.groupby("vehicle_number", observed=True)["id"].count()
    repeat_global = set(veh_global[veh_global >= C.REPEAT_GLOBAL_MIN].index)

    vz = (ev.groupby(["superzone_id", "vehicle_number"], observed=True)["id"]
            .count().rename("n").reset_index())
    vz["is_repeat"] = (vz["n"] >= C.REPEAT_ZONE_MIN) | vz["vehicle_number"].isin(repeat_global)

    rep_tickets = (vz.assign(rep_n=vz["n"] * vz["is_repeat"])
                     .groupby("superzone_id", observed=True)
                     .agg(zone_tickets=("n", "sum"), repeat_tickets=("rep_n", "sum")))
    rep_tickets["repeat_share"] = (rep_tickets["repeat_tickets"] /
                                   rep_tickets["zone_tickets"]).fillna(0)
    z = z.join(rep_tickets["repeat_share"], on="superzone_id")
    z["repeat_share"] = z["repeat_share"].fillna(0)
    z["habitual"] = z["repeat_share"] >= C.HABITUAL_SHARE_THRESHOLD

    # city headline: "X% of violations come from Y% of vehicles"
    total_tickets = int(veh_global.sum())
    repeat_vehicle_tickets = int(veh_global[veh_global.index.isin(repeat_global)].sum())
    n_vehicles = int(len(veh_global))
    n_repeat_vehicles = int(len(repeat_global))
    city_stat = {
        "n_vehicles": n_vehicles,
        "n_repeat_vehicles": n_repeat_vehicles,
        "pct_repeat_vehicles": round(100 * n_repeat_vehicles / max(n_vehicles, 1), 1),
        "pct_tickets_from_repeats": round(100 * repeat_vehicle_tickets / max(total_tickets, 1), 1),
    }
    return z, city_stat


def _responsiveness(ev, z):
    """7.3 monthly pressure trend over Nov->Mar -> responding/resistant/stable."""
    mp = (ev[ev["month_ist"].isin(C.RESPONSIVENESS_MONTHS)]
          .groupby(["superzone_id", "month_ist"], observed=True)["event_weight"]
          .sum().unstack(fill_value=0))
    for m in C.RESPONSIVENESS_MONTHS:
        if m not in mp.columns:
            mp[m] = 0.0
    mp = mp[C.RESPONSIVENESS_MONTHS]
    x = np.arange(len(C.RESPONSIVENESS_MONTHS))

    def _slope(row):
        mean = row.mean()
        if mean <= 0:
            return 0.0
        return float(np.polyfit(x, row.values / mean, 1)[0])

    slope = mp.apply(_slope, axis=1).rename("trend_slope")
    z = z.join(slope, on="superzone_id")
    z["trend_slope"] = z["trend_slope"].fillna(0.0)
    z["responsiveness"] = np.select(
        [z["trend_slope"] <= C.RESPONDING_SLOPE, z["trend_slope"] >= C.RESISTANT_SLOPE],
        ["responding", "resistant"], default="stable",
    )
    return z


def _sprawl_and_anchor(ev, z):
    g = ev.groupby("superzone_id", observed=True)
    n_points = g["point_11m"].nunique().rename("n_points")
    # spread (m): mean distance of distinct points to zone medoid
    z = z.join(n_points, on="superzone_id")
    z["n_points"] = z["n_points"].fillna(1)
    z["sprawl"] = (z["n_points"] / z["n_tickets"].clip(lower=1)).clip(0, 1)
    z["junction_anchored"] = (z["junction_mode"].notna() &
                              ~z["junction_mode"].astype("string").str.contains(
                                  "No Junction", case=False, na=False))
    return z


def _carriageway_impact(ev, z):
    """7.6 Carriageway Impact Index — a MODELED flow-impact proxy from static road
    context (junction criticality, road class, demand-generator proximity).

    NOT a congestion measurement: the data has no flow/speed signal. We estimate
    how disruptive an illegal park here would be from physical context, then scale
    obstruction pressure by a transparent, bounded multiplier."""
    import anchors  # static public coords (metro + commercial); audited reference

    # --- J: junction criticality --------------------------------------------- #
    jname = ev["junction_name"].astype("string").fillna("")
    is_jct = ((jname.str.len() > 0)
              & ~jname.str.contains("No Junction", case=False, na=False)
              & (jname.str.upper() != "NULL")).to_numpy(dtype=bool)
    is_jct = pd.Series(is_jct, index=ev.index)
    jshare = is_jct.groupby(ev["superzone_id"], observed=True).mean().rename("junction_share")
    njct = (jname[is_jct].groupby(ev["superzone_id"][is_jct], observed=True)
            .nunique().rename("n_junctions"))
    z = z.join(jshare, on="superzone_id").join(njct, on="superzone_id")
    z["junction_share"] = z["junction_share"].fillna(0.0)
    z["n_junctions"] = z["n_junctions"].fillna(0).astype(int)
    multi = 1 + C.JUNCTION_MULTI_BOOST * np.clip(z["n_junctions"] - 1, 0, C.JUNCTION_MULTI_CAP)
    z["cii_junction"] = (z["junction_share"] * multi).clip(0, 1)

    # --- R: road class (from the zone's modal address segment) --------------- #
    seg = ev.assign(_seg=ev["location"].astype("string").str.split(",").str[0].str.strip())
    top_seg = (seg.groupby("superzone_id", observed=True)["_seg"]
               .agg(lambda s: s.dropna().mode().iloc[0] if len(s.dropna()) else None))
    z["road_segment"] = z["superzone_id"].map(top_seg)
    z["road_class"] = z["road_segment"].map(U.classify_road)
    z["cii_road"] = (z["road_class"].map(C.ROAD_CLASS_WEIGHTS)
                     .fillna(C.ROAD_CLASS_WEIGHTS["unknown"]))

    # --- D: proximity to a public metro / commercial demand generator -------- #
    z["dist_metro_m"] = [U.nearest_anchor_m(la, lo, anchors.METRO)
                         for la, lo in zip(z["lat"], z["lon"])]
    z["dist_commercial_m"] = [U.nearest_anchor_m(la, lo, anchors.COMMERCIAL)
                              for la, lo in zip(z["lat"], z["lon"])]
    z["cii_demand"] = np.maximum(z["dist_metro_m"].map(U.demand_proximity),
                                 z["dist_commercial_m"].map(U.demand_proximity))

    # --- combine into a bounded context multiplier -> flow-impact ------------ #
    w = C.CII_WEIGHTS
    m = (w["junction"] * z["cii_junction"] + w["road_class"] * z["cii_road"]
         + w["demand"] * z["cii_demand"])
    lo, hi = C.CII_CLIP
    z["context_multiplier"] = (lo + m * (hi - lo)).clip(lo, hi)
    z["flow_impact_raw"] = z["pressure_raw"] * z["context_multiplier"]
    z["flow_impact_score"] = U.percentile_norm(z["flow_impact_raw"])
    z["flow_impact_rank"] = (z["flow_impact_raw"].rank(ascending=False, method="min")
                             .astype(int))
    return z


def _typology(ev, z):
    """7.5 cluster zones on temporal+composition fingerprint; pick k by silhouette."""
    g = ev.groupby("superzone_id", observed=True)
    h = ev["hour_ist"]
    bins = {
        "f_early": ev[(h >= 3) & (h < 8)],
        "f_morning": ev[(h >= 8) & (h < 11)],
        "f_midday": ev[(h >= 11) & (h < 17)],
        "f_evening": ev[(h >= 17) & (h < 21)],
        "f_night": ev[(h >= 21) | (h < 3)],
    }
    feat = pd.DataFrame(index=z["superzone_id"])
    tot = g["id"].count()
    for name, sub in bins.items():
        feat[name] = (sub.groupby("superzone_id", observed=True)["id"].count() / tot).fillna(0)
    feat["weekend_share"] = (g["is_weekend"].mean()).reindex(feat.index).fillna(0)
    feat["veh_footprint"] = (g["vehicle_wt"].mean()).reindex(feat.index).fillna(0)
    feat["severity_mean"] = (g["row_severity"].mean()).reindex(feat.index).fillna(0)
    zi = z.set_index("superzone_id")
    feat["repeat_share"] = zi["repeat_share"].reindex(feat.index).fillna(0)
    feat["sprawl"] = zi["sprawl"].reindex(feat.index).fillna(0)
    feat["junction"] = zi["junction_anchored"].reindex(feat.index).fillna(False).astype(float)
    feat["log_vol"] = np.log1p(tot.reindex(feat.index).fillna(0))

    X = StandardScaler().fit_transform(feat.values)
    best_k, best_s, best_lab = None, -1, None
    for k in C.TYPOLOGY_K_RANGE:
        km = KMeans(n_clusters=k, random_state=C.TYPOLOGY_RANDOM_STATE, n_init=10)
        lab = km.fit_predict(X)
        s = silhouette_score(X, lab, sample_size=min(5000, len(X)),
                             random_state=C.TYPOLOGY_RANDOM_STATE)
        if s > best_s:
            best_k, best_s, best_lab = k, s, lab
    feat["cluster"] = best_lab

    # interpretable labels: a cluster is named by what most distinguishes it
    # from the city-wide average (centroid minus global mean per temporal bin).
    centroids = feat.groupby("cluster").mean(numeric_only=True)
    gmean = feat.mean(numeric_only=True)
    time_bins = {
        "f_early": "Early-morning sweep zone",
        "f_morning": "Weekday-morning commercial",
        "f_midday": "Midday market / all-day",
        "f_evening": "Evening-active corridor",
        "f_night": "Night-active corridor",
    }
    labels = {}
    for cl, row in centroids.iterrows():
        if row["junction"] > 0.5:
            labels[cl] = "Junction choke point"
            continue
        if (row["repeat_share"] > 0.30 and
                row["log_vol"] > centroids["log_vol"].quantile(0.66)):
            labels[cl] = "Market / all-day demand"
            continue
        # otherwise: the time bin where this cluster most exceeds the city mean
        diffs = {b: row[b] - gmean[b] for b in time_bins}
        dom = max(diffs, key=diffs.get)
        labels[cl] = time_bins[dom]
    # de-duplicate identical labels by appending the cluster's volume tier
    seen = {}
    for cl in sorted(labels):
        base = labels[cl]
        if base in seen.values():
            tier = "high-vol" if centroids.loc[cl, "log_vol"] > gmean["log_vol"] else "low-vol"
            labels[cl] = f"{base} ({tier})"
        seen[cl] = labels[cl]
    feat["typology"] = feat["cluster"].map(labels)

    # temporal fingerprint (hour×weekday) — store compactly per zone
    fp = (ev.groupby(["superzone_id", "dow_ist", "hour_ist"], observed=True)["id"]
            .count().rename("n").reset_index())
    fingerprints = {}
    for sid, sub in fp.groupby("superzone_id", observed=True):
        grid = np.zeros((7, 24), dtype=int)
        grid[sub["dow_ist"].values, sub["hour_ist"].values] = sub["n"].values
        fingerprints[sid] = grid.tolist()

    z = z.join(feat[["cluster", "typology"]], on="superzone_id")
    meta = {
        "k": int(best_k), "silhouette": round(float(best_s), 3),
        "labels": {int(k): v for k, v in labels.items()},
        "counts": {v: int((feat["typology"] == v).sum()) for v in set(labels.values())},
    }
    return z, fingerprints, meta


def _intervention(z):
    """7.4 concrete recommended intervention per P1/P2 zone (else monitor)."""
    def rec(r):
        if r["tier"] in ("P1", "P2"):
            if r.get("evening_blind_spot", False):
                pass  # blind-spot recommendation added in stage 06; keep generic here
            if r["veh_footprint_flag"]:
                return "Towing readiness — heavy-vehicle obstruction mix"
            if r["habitual"] and r["responsiveness"] == "resistant":
                return "Install no-parking infrastructure / designate parking (habitual + enforcement-resistant)"
            if r["sprawl"] > 0.6:
                return "Continuous corridor patrol / barricading (obstruction spread across zone)"
            if r["junction_anchored"]:
                return "Fixed no-parking board + junction sweep (point obstruction)"
            return "Targeted enforcement sweep"
        return "Monitor"
    z["veh_footprint_flag"] = z.get("veh_footprint_flag", False)
    z["intervention"] = z.apply(rec, axis=1)
    return z


def run():
    ev = pd.read_parquet(C.DATA_PROC / "events_clean.parquet")
    z = pd.read_parquet(C.DATA_PROC / "zone_scores.parquet")

    # idempotent: drop any advanced columns from a prior standalone run
    _added = ["veh_footprint_mean", "veh_footprint_flag", "n_officers",
              "exposure_days", "exposure", "bias_adjusted", "bias_adjusted_score",
              "bias_adjusted_rank", "rank_divergence", "under_recognized",
              "repeat_share", "habitual", "trend_slope", "responsiveness",
              "n_points", "sprawl", "junction_anchored", "cluster", "typology",
              "intervention",
              "junction_share", "n_junctions", "cii_junction", "road_segment",
              "road_class", "cii_road", "dist_metro_m", "dist_commercial_m",
              "cii_demand", "context_multiplier", "flow_impact_raw",
              "flow_impact_score", "flow_impact_rank"]
    z = z.drop(columns=[c for c in _added if c in z.columns])

    # heavy-vehicle mix flag per zone (mean footprint high)
    vmean = ev.groupby("superzone_id", observed=True)["vehicle_wt"].mean()
    z = z.join(vmean.rename("veh_footprint_mean"), on="superzone_id")
    z["veh_footprint_flag"] = z["veh_footprint_mean"] >= 0.55

    z = _bias_correction(ev, z)
    z, city_stat = _offenders(ev, z)
    z = _responsiveness(ev, z)
    z = _sprawl_and_anchor(ev, z)
    z = _carriageway_impact(ev, z)
    z, fingerprints, typ_meta = _typology(ev, z)
    z = _intervention(z)

    z.to_parquet(C.DATA_PROC / "zone_scores.parquet", index=False)
    U.write_json(C.DATA_PROC / "fingerprints.json", fingerprints)
    U.write_json(C.DATA_PROC / "offender_stat.json", city_stat)
    U.write_json(C.DATA_PROC / "typology_meta.json", typ_meta)

    print(f"[04_advanced] habitual zones={int(z['habitual'].sum())} · "
          f"under-recognized (bias)={int(z['under_recognized'].sum())}")
    print(f"[04_advanced] responsiveness: "
          f"{z['responsiveness'].value_counts().to_dict()}")
    print(f"[04_advanced] city offender stat: "
          f"{city_stat['pct_tickets_from_repeats']}% of tickets from "
          f"{city_stat['pct_repeat_vehicles']}% of vehicles")
    print(f"[04_advanced] typology k={typ_meta['k']} "
          f"silhouette={typ_meta['silhouette']} -> {typ_meta['counts']}")
    _cii_top = set(z.sort_values("flow_impact_raw", ascending=False).head(20)["superzone_id"])
    _pr_top = set(z.sort_values("priority", ascending=False).head(20)["superzone_id"])
    print(f"[04_advanced] carriageway-impact: multiplier "
          f"{z['context_multiplier'].min():.2f}–{z['context_multiplier'].max():.2f}, "
          f"road-class {z['road_class'].value_counts().to_dict()}, "
          f"flow-impact top-20 shares {len(_cii_top & _pr_top)}/20 with priority")
    return z


if __name__ == "__main__":
    run()
