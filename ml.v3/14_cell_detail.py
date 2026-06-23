"""
Stage 14 — per-cell DETAIL for the "Place analysis" modal.

The map cell (`map_cells.json`) and the scores (`pic.json`, `forecast_daily.json`,
`online_state.json`) are thin — they carry the headline numbers but NOT the raw
distributions a person needs to understand *why* a spot is flagged. This stage
groups the cleaned, H3-binned tickets (`events_h3.parquet`, one row per ticket)
by `h3_r10` and bakes the human-readable breakdown the modal shows:

  violation_mix       top parking violations (count)
  vehicle_mix         top vehicle types (count)
  hourly_histogram    24 bins by hour-of-day (IST)
  monthly_recurrence  {YYYY-MM: count} over the data window
  fingerprint         7×24 weekday(Mon=0)×hour grid
  exposure            distinct officers + distinct active days (bias control)
  repeat_share        share of tickets that are repeat *vehicles* in this cell
  n_tickets, top_streets

HONESTY: ticket *times* reflect officer upload/shift patterns, NOT live traffic;
the modal labels the hourly/fingerprint sections accordingly. Counts are recorded
enforcement activity. This is the historical layer — the API overlays LIVE Mongo
tickets on top at read time (`/api/v3/cell/{h3}`).

Output: data/processed/v3/cell_detail.json  (keyed by h3_r10, ~6.5k cells).
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402

_MONTH_ORDER = list(C.MONTHLY_RAW.keys())


def _top_counts(series: pd.Series, n: int = 6) -> list[dict]:
    return [{"name": str(k), "count": int(v)}
            for k, v in series.value_counts().head(n).items()]


def _street_of(loc: str) -> str | None:
    """First address segment (e.g. '18th Main Road, Block 2, …' -> '18th Main Road')."""
    if not isinstance(loc, str) or not loc.strip():
        return None
    return loc.split(",")[0].strip() or None


def _clean_junction(j) -> str | None:
    """'BTP051 - Safina Plaza' -> 'Safina Plaza'; drop the 'No Junction' sentinel."""
    if not isinstance(j, str) or not j.strip() or "No Junction" in j:
        return None
    return j.split(" - ")[-1].strip() or None


def _mode_or_none(series):
    s = series.dropna()
    return s.mode().iloc[0] if len(s) else None


def run():
    ev = pd.read_parquet(C.DATA_PROC / "events_h3.parquet")
    ev = ev[ev["h3_r10"].notna()].copy()
    ev["hour_ist"] = ev["hour_ist"].clip(0, 23).astype(int)
    ev["dow_ist"] = ev["dow_ist"].clip(0, 6).astype(int)
    ev["_street"] = ev["location"].map(_street_of)
    ev["_junction"] = ev["junction_name"].map(_clean_junction) if "junction_name" in ev.columns else None

    # ---- vectorized group aggregates (one pass each) --------------------- #
    n_tickets = ev.groupby("h3_r10", observed=True).size()

    # readable place NAME per cell: most-common junction > most-common street >
    # police station. Gives every row/marker a human label instead of an h3 id.
    g_h3 = ev.groupby("h3_r10", observed=True)
    junction_name = g_h3["_junction"].agg(_mode_or_none) if "_junction" in ev.columns else {}
    street_name = g_h3["_street"].agg(_mode_or_none)
    station_name = g_h3["police_station"].agg(_mode_or_none)

    def _val(x):
        return None if x is None or (isinstance(x, float) and pd.isna(x)) else x

    def _name_of(h3) -> str:
        jn = _val(junction_name.get(h3)) if hasattr(junction_name, "get") else None
        return str(jn or _val(street_name.get(h3)) or _val(station_name.get(h3)) or "Unnamed spot")

    names = {str(h3): _name_of(h3) for h3 in n_tickets.index}

    hourly = (ev.groupby(["h3_r10", "hour_ist"], observed=True).size()
                .unstack(fill_value=0).reindex(columns=range(24), fill_value=0))

    monthly = (ev.groupby(["h3_r10", "month_ist"], observed=True).size()
                 .unstack(fill_value=0))
    for m in _MONTH_ORDER:
        if m not in monthly.columns:
            monthly[m] = 0
    monthly = monthly[[m for m in _MONTH_ORDER if m in monthly.columns]]

    # 7×24 weekday×hour grid, built per cell from a single grouped pass (fast: no
    # per-(cell,day,hour) .loc lookups). fp_rows[h3] = {dow: {hour: count}}.
    fp_series = ev.groupby(["h3_r10", "dow_ist", "hour_ist"], observed=True).size()
    fp_rows: dict = {}
    for (h3, d, hh), cnt in fp_series.items():
        fp_rows.setdefault(h3, {}).setdefault(int(d), {})[int(hh)] = int(cnt)

    def _grid(h3):
        cell = fp_rows.get(h3, {})
        return [[cell.get(d, {}).get(hh, 0) for hh in range(24)] for d in range(7)]

    officers = ev.groupby("h3_r10", observed=True)["created_by_id"].nunique()
    active_days = ev.groupby("h3_r10", observed=True)["date_ist"].nunique()

    # repeat-vehicle share: tickets on a vehicle seen >1× in this cell / all tickets
    veh = ev.groupby(["h3_r10", "vehicle_number"], observed=True).size()
    repeat_tickets = veh[veh > 1].groupby("h3_r10").sum()

    # per-cell mixes (top-N) — group once, build dicts
    viol_mix = {h: _top_counts(g, 6) for h, g in ev.groupby("h3_r10", observed=True)["primary_violation"]}
    veh_mix = {h: _top_counts(g, 6) for h, g in ev.groupby("h3_r10", observed=True)["vehicle_type"]}
    street_mix = {h: _top_counts(g.dropna(), 3) for h, g in ev.groupby("h3_r10", observed=True)["_street"]}

    details: dict[str, dict] = {}
    for h3 in n_tickets.index:
        nt = int(n_tickets[h3])
        rep = int(repeat_tickets.get(h3, 0))
        details[str(h3)] = {
            "h3_r10": str(h3),
            "name": names.get(str(h3)),
            "n_tickets": nt,
            "violation_mix": viol_mix.get(h3, []),
            "vehicle_mix": veh_mix.get(h3, []),
            "top_streets": street_mix.get(h3, []),
            "hourly_histogram": [int(v) for v in hourly.loc[h3].tolist()],
            "monthly_recurrence": {m: int(monthly.loc[h3, m]) for m in monthly.columns},
            "fingerprint": _grid(h3),
            "exposure": {"officers": int(officers.get(h3, 0)),
                         "active_days": int(active_days.get(h3, 0))},
            "repeat_share": round(rep / nt, 3) if nt else 0.0,
        }

    out = {
        "n_cells": len(details),
        "month_order": _MONTH_ORDER,
        "data_window": C.TIME_WINDOW_LABEL,
        "note": ("Recorded enforcement activity (tickets), NOT live traffic. Ticket "
                 "times reflect officer upload/shift patterns. The API overlays live "
                 "tickets on top of this historical layer."),
        "cells": details,
    }
    U.write_json(C.DATA_PROC / "cell_detail.json", out)

    # patch map_cells.json with the readable name so the map/table/modal can show a
    # human label everywhere (one source of truth; backend passes it straight through).
    mc_path = C.DATA_PROC / "map_cells.json"
    n_named = 0
    if mc_path.exists():
        mc = json.loads(mc_path.read_text(encoding="utf-8"))
        for rec in mc.get("cells", []):
            nm = names.get(rec.get("h3_r10"))
            if nm:
                rec["name"] = nm
                n_named += 1
        U.write_json(mc_path, mc)

    print(f"[14_cell_detail] cell_detail.json — {len(details)} cells "
          f"from {len(ev):,} tickets · named {n_named} map cells")
    return len(details)


if __name__ == "__main__":
    run()
