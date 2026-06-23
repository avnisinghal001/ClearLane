"""
Stage 05 (Phase 2) — Parking-Induced Congestion (PIC) score.

    PIC_h = ViolationIntensity_h (0–1, bias-corrected from Phase 1)
            × CongestionSeverity_h (0–1)

CongestionSeverity is, per cell, one of:
  * MEASURED (source="mappls_typical"): a Mappls TYPICAL-traffic ratio on a short
        A->B road segment via the advancedmaps Distance-Time Matrix,
        severity = clip(1 − free_flow / typical_eta, 0, 1)
        where typical_eta = distance_matrix_eta, free_flow = distance_matrix.
        This is Mappls' own historical TYPICAL traffic — NOT real-time, NOT
        predictive, NEVER from the ticket data. Bounded to the top-N cells by
        intensity (config.PIC_TOP_CORRIDORS); cached.
  * MODELED (source="modeled"): a clearly-labelled proxy from static road context
        (road class, junction density, neighbour spillover) when the typical ETA is
        unavailable (no key / quota / API not enabled). NEVER called "measured".

WORKED EXAMPLE: a cell with intensity 0.80 and typical severity 0.45 (road runs
~1.8× slower than free-flow on a typical day) -> PIC 0.36. A jam-prone cell that is
NOT a parking magnet (intensity 0.1) scores low even at severity 0.45 -> PIC 0.045.
PIC ranks the city by "real parking problem AND typically slow".

Output: pic.parquet (all cells), pic.json (top 200 + summary).
"""
from __future__ import annotations

import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402
import mappls as M          # noqa: E402


def _offset_point(lat, lon, d_m, bearing_deg=90.0):
    """Point d_m metres from (lat,lon) at a bearing (default east) — corridor B."""
    dlat = d_m * math.cos(math.radians(bearing_deg)) / 111_320.0
    dlon = d_m * math.sin(math.radians(bearing_deg)) / (111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def _live_severity(lat, lon):
    """Mappls TYPICAL-traffic congestion ratio on a short A->B segment (None if
    unavailable). Delegates to mappls.congestion_severity (advancedmaps
    distance_matrix free-flow vs distance_matrix_eta typical) — a Mappls-measured
    typical ratio, never derived from ticket data."""
    if not (C.MAPPLS_ENABLED and M.rest_key()):
        return None
    blat, blon = _offset_point(lat, lon, C.CORRIDOR_LEN_M)
    return M.congestion_severity(lat, lon, blat, blon)


def _modeled_severity(cells: pd.DataFrame) -> pd.Series:
    """Offline congestion proxy in [0,1] from static road context (NOT measured)."""
    w = C.PIC_PROXY_WEIGHTS
    road = pd.to_numeric(cells.get("road_class_wt", 0.5), errors="coerce").fillna(0.5)
    jn = pd.to_numeric(cells.get("junction_share", 0.0), errors="coerce").fillna(0.0)
    nb = pd.to_numeric(cells.get("neighbor_pressure", 0.0), errors="coerce").fillna(0.0)
    nb = (U.percentile_norm(nb) / 100.0) if nb.nunique() > 1 else nb.clip(0, 1)
    sev = w["road_class"] * road + w["junction"] * jn + w["neighbor"] * nb
    return sev.clip(0.0, 1.0)


def run() -> dict:
    cells = pd.read_parquet(C.DATA_PROC / "hotspots.parquet").set_index("h3_r10")

    # baseline: everyone gets the modeled proxy ...
    severity = _modeled_severity(cells)
    source = pd.Series("modeled", index=cells.index)

    # ... then upgrade the top-N intensity cells to the Mappls TYPICAL-traffic ratio.
    online = bool(C.MAPPLS_ENABLED and M.rest_key())   # advancedmaps needs the REST key
    n_typical = 0
    if online:
        top = cells.sort_values("intensity", ascending=False).head(C.PIC_TOP_CORRIDORS)
        for cid, r in top.iterrows():
            if M.route_down():            # distance-matrix disabled/quota -> stop trying
                break
            s = _live_severity(float(r["lat"]), float(r["lon"]))
            if s is not None:
                severity.loc[cid] = s
                source.loc[cid] = "mappls_typical"
                n_typical += 1
            if n_typical and n_typical % 25 == 0:
                M.flush()
        M.flush()

    intensity_unit = pd.to_numeric(cells["intensity"], errors="coerce").fillna(0) / 100.0
    pic_raw = intensity_unit * severity
    cells["congestion_severity"] = severity
    cells["congestion_source"] = source
    cells["pic_raw"] = pic_raw
    cells["pic_score"] = U.percentile_norm(pic_raw)
    cells["pic_rank"] = pic_raw.rank(ascending=False, method="first").astype(int)

    cells.reset_index().to_parquet(C.DATA_PROC / "pic.parquet", index=False)

    keep = ["h3_r10", "lat", "lon", "police_station", "intensity",
            "congestion_severity", "congestion_source", "road_class",
            "pic_raw", "pic_score", "pic_rank"]
    top = (cells.reset_index().sort_values("pic_score", ascending=False)
           .head(200)[[k for k in keep if k in cells.reset_index().columns]])
    summary = {
        "n_cells": int(len(cells)),
        "congestion_mode": "mappls_typical+modeled" if n_typical else "modeled-only",
        "n_live_corridors": int(n_typical),       # kept key name (downstream compat)
        "n_mappls_typical": int(n_typical),
        "n_modeled": int((source == "modeled").sum()),
        "note": ("CongestionSeverity is a Mappls TYPICAL-traffic ratio "
                 "(1 − distance_matrix / distance_matrix_eta) for the mappls_typical "
                 "cells and a MODELED proxy otherwise; PIC = bias-corrected intensity × "
                 "severity. It is Mappls' historical typical traffic — NOT real-time, "
                 "NOT predictive, and never a measurement of congestion from ticket data."),
        "top_cells": top.to_dict(orient="records"),
    }
    U.write_json(C.DATA_PROC / "pic.json", summary)

    # --- map_cells.json: the FULL occupied-cell set (thin record) so the map can
    # render the WHOLE distribution (low→high), not just the all-high top-200. This
    # is what makes the rendered map "alive" — pic_score is percentile-uniform
    # (0..100), so colouring by tier/PIC spans green→yellow→red across ~6.5k cells.
    full = cells.reset_index()
    mc_keep = ["h3_r10", "lat", "lon", "police_station", "road_class",
               "intensity", "congestion_severity", "congestion_source",
               "count", "pic_score", "pic_rank"]
    mc_keep = [k for k in mc_keep if k in full.columns]
    mcells = []
    for _, row in full.sort_values("pic_score", ascending=False)[mc_keep].iterrows():
        ps = row.get("police_station")
        mcells.append({
            "h3_r10": row["h3_r10"],
            "lat": round(float(row["lat"]), 6), "lon": round(float(row["lon"]), 6),
            "police_station": (None if pd.isna(ps) else str(ps)),
            "road_class": (None if pd.isna(row.get("road_class")) else str(row.get("road_class"))),
            "intensity": round(float(row["intensity"]), 1),
            "congestion_severity": round(float(row["congestion_severity"]), 3),
            "congestion_source": row.get("congestion_source"),
            "count": int(row["count"]) if "count" in full.columns and not pd.isna(row.get("count")) else None,
            "pic_score": round(float(row["pic_score"]), 1),
            "pic_rank": int(row["pic_rank"]) if "pic_rank" in full.columns else None,
        })
    U.write_json(C.DATA_PROC / "map_cells.json", {
        "n_cells": len(mcells),
        "congestion_mode": summary["congestion_mode"],
        "note": ("FULL occupied-cell set (thin) for the map. pic_score is a 0..100 "
                 "percentile of bias-corrected PIC; the backend composes a "
                 "time-varying display_score = pic_score × MODELED hourly congestion "
                 "× day-of-week factor per request. Modeled, never measured."),
        "cells": mcells,
    })
    print(f"[05_pic] map_cells.json: {len(mcells):,} cells "
          f"(pic_score {mcells[-1]['pic_score']:.0f}..{mcells[0]['pic_score']:.0f})")

    print(f"[05_pic] PIC built for {len(cells):,} cells · congestion="
          f"{summary['congestion_mode']} (mappls_typical={n_typical}, "
          f"modeled={summary['n_modeled']})")
    top1 = cells.sort_values('pic_raw', ascending=False).iloc[0]
    print(f"[05_pic] top PIC cell intensity={top1['intensity']:.0f} "
          f"severity={top1['congestion_severity']:.2f} src={top1['congestion_source']}")
    return summary


if __name__ == "__main__":
    run()
