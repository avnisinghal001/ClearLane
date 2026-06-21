"""
Stage 02 — H3 hexagon binning + enforcement-exposure + spatial scaffold.

We chop Bengaluru into block-sized hexagons (H3 res-10, ~65.9 m edge) so each
hexagon is one candidate hotspot. For every cell we compute the two quantities the
bias-correction needs:

  count_h     = number of parking tickets in the cell            (what we see)
  exposure_h  = distinct (device_id × date) pairs active in cell  (how hard police
                LOOKED there)                                     (the bias driver)

WORKED EXAMPLE:
  Cell 8a61... has 150 tickets written by 3 officers/devices across 12 days.
  distinct (device × date) pairs = 30  ->  exposure = 30.
  raw_rate = 150 / 30 = 5.0 tickets per device-day.
  A different cell with 150 tickets but exposure 90 has raw_rate 1.67 — same raw
  count, very different TRUE intensity once you divide out policing. That gap is
  the whole point (Lum & Isaac 2016 feedback loop).

We also build:
  * the 6-neighbour H3 adjacency (for spatial-lag features + Gi* weights),
  * a coarse res-7 block id per cell (for spatially-disjoint CV folds),
  * the concentration curve (top X% of cells = Y% of violations) — the pitch stat.

Outputs: cells_r10.parquet, h3_adjacency.json, h3_concentration.json.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402


def run() -> pd.DataFrame:
    if not U.h3_available():
        raise RuntimeError(
            "h3 not installed — run `pip install -r ml.v3/requirements.txt` "
            "(needs h3>=4).")

    ev = pd.read_parquet(C.DATA_PROC / "events_clean.parquet")
    print(f"[02_h3_bin] {len(ev):,} clean events -> H3 res-{C.H3_RES_FINE}")

    # --- assign each ticket to its fine + coarse hexagon ------------------ #
    ev["h3_r10"] = [U.h3_cell(la, lo, C.H3_RES_FINE)
                    for la, lo in zip(ev["latitude"], ev["longitude"])]
    ev["h3_r9"] = [U.h3_cell(la, lo, C.H3_RES_COARSE)
                   for la, lo in zip(ev["latitude"], ev["longitude"])]
    ev = ev[ev["h3_r10"].notna()].copy()
    ev.to_parquet(C.DATA_PROC / "events_h3.parquet", index=False)

    # device×date key for the exposure count (distinct enforcement effort units).
    ev["dev_day"] = (ev["device_id"].astype("string").fillna("NA") + "|"
                     + ev["date_ist"].astype("string"))

    g = ev.groupby("h3_r10", observed=True)
    cells = pd.DataFrame({
        "count": g.size(),
        "pressure_raw": g["event_weight"].sum(),         # severity×footprint×conf
        "n_officers": g["created_by_id"].nunique(),
        "n_devices": g["device_id"].nunique(),
        "active_days": g["date_ist"].nunique(),
        "exposure": g["dev_day"].nunique().clip(lower=C.EXPOSURE_MIN),
        "h3_r9": g["h3_r9"].first(),
    })
    # cell centroid (for mapping + KNN fallback weights).
    cents = {c: U.h3_to_latlng(c) for c in cells.index}
    cells["lat"] = [cents[c][0] for c in cells.index]
    cells["lon"] = [cents[c][1] for c in cells.index]
    # coarse block id (res-7) -> used to make spatially-disjoint CV folds.
    cells["block"] = [U.h3_parent(c, C.H3_BLOCK_RES) for c in cells.index]

    # raw (biased) rate vs the naive raw count — kept for the side-by-side story.
    cells["raw_rate"] = cells["count"] / cells["exposure"]

    # --- 6-neighbour adjacency among OCCUPIED cells ----------------------- #
    occupied = set(cells.index)
    adjacency = {c: [n for n in U.h3_ring(c, C.H3_K_RING) if n in occupied]
                 for c in cells.index}
    # spatial-lag scaffold: mean neighbour pressure (filled fully in stage 03).
    cells["n_neighbors"] = [len(adjacency[c]) for c in cells.index]

    cells = cells.reset_index().rename(columns={"index": "h3_r10"})
    cells.to_parquet(C.DATA_PROC / "cells_r10.parquet", index=False)
    U.write_json(C.DATA_PROC / "h3_adjacency.json", adjacency)

    # --- concentration curve (the "tiny slice = whole problem" stat) ------ #
    s = cells.sort_values("count", ascending=False)["count"].to_numpy()
    total = s.sum()
    cum = np.cumsum(s) / total
    n = len(s)
    conc = {}
    for pct in (0.025, 0.05, 0.10, 0.117, 0.20):
        k = max(1, int(round(pct * n)))
        conc[f"top_{pct*100:g}pct_cells"] = {
            "n_cells": k, "share_of_violations_pct": round(100 * cum[k - 1], 1)}
    # also: how few cells hold 50% / 80% of violations.
    for share in (0.50, 0.80):
        k = int(np.searchsorted(cum, share) + 1)
        conc[f"cells_for_{int(share*100)}pct"] = {
            "n_cells": k, "pct_of_all_cells": round(100 * k / n, 1)}

    U.write_json(C.DATA_PROC / "h3_concentration.json",
                 {"n_occupied_cells": n, "total_violations": int(total),
                  "concentration": conc})

    top50 = conc["cells_for_50pct"]
    print(f"[02_h3_bin] {n:,} occupied cells · exposure median="
          f"{cells['exposure'].median():.0f} · "
          f"{top50['n_cells']:,} cells ({top50['pct_of_all_cells']}%) = 50% of violations")
    return cells


if __name__ == "__main__":
    run()
