"""
Stage 08 — build the serving payloads (map, zone detail, evidence, KPIs) and
optional LLM briefings.

Outputs (consumed by the FastAPI backend and bundled into the demo fallback):
  map_payload.json     lean per-zone records + KPIs for the command map
  zones_detail.json    full per-zone detail objects (§3)
  evidence_points.json 4-dec evidence points (capped for the bundled demo)
  emerging.json, forecast.json, typology.json, search_index.json

The LLM copilot is an OPTIONAL deployment extension (env CLEARLANE_LLM=1). The
core product is fully deterministic; the demo never depends on a live API call.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402

_MONTH_ORDER = list(C.MONTHLY_RAW.keys())
_MONTH_LABEL_SHORT = {"2023-11": "Nov '23", "2023-12": "Dec '23", "2024-01": "Jan '24",
                      "2024-02": "Feb '24", "2024-03": "Mar '24", "2024-04": "Apr '24"}


def _top_counts(series, n=6):
    return [{"name": str(k), "count": int(v)}
            for k, v in series.value_counts().head(n).items()]


def _explanation(r):
    bits = [f"Tier {r['tier']} zone (priority {r['priority']:.0f}/100)."]
    bits.append(f"Obstruction pressure {r['A']:.0f}, recurrence {r['B']:.0f}"
                + (", chronic" if r["chronic"] else "") + ".")
    if r["habitual"]:
        bits.append(f"{r['repeat_share']*100:.0f}% of tickets are repeat vehicles "
                    "— a structural parking-demand problem, not transient.")
    else:
        bits.append("Mostly unique vehicles — responsive to enforcement presence.")
    bits.append({"responding": "Pressure is declining month-on-month — enforcement is working.",
                 "resistant": "Pressure is flat/rising despite ticketing — needs a structural fix.",
                 "stable": "Pressure is steady."}[r["responsiveness"]])
    if r["evening_blind_spot"]:
        bits.append("Evening blind spot: <2% of tickets fall in the 17:00–21:00 "
                    "congestion window though this is a top zone.")
    return " ".join(bits)


def _window_for(r):
    if r["evening_blind_spot"]:
        return "17:00–21:00 (currently unenforced)"
    return "Sustain current coverage; add spot checks"


def _display_name(r):
    """Human-recognizable label: junction > street/area > police station > id.
    Recognizable names beat internal zone IDs everywhere in the UI (§ honesty)."""
    j = r.get("junction_mode")
    if isinstance(j, str) and j and "No Junction" not in j:
        return j.split(" - ")[-1].strip()         # "BTP051 - Safina Plaza" -> "Safina Plaza"
    top = r.get("_top_street")
    if isinstance(top, str) and top:
        return top
    st = r.get("police_station")
    if isinstance(st, str) and st:
        return f"{st} area"
    return f"Zone {r['superzone_id']}"


def run():
    ev = pd.read_parquet(C.DATA_PROC / "events_clean.parquet")
    z = pd.read_parquet(C.DATA_PROC / "zone_scores.parquet")
    fingerprints = json.loads((C.DATA_PROC / "fingerprints.json").read_text())

    g = ev.groupby("superzone_id", observed=True)
    hourly = {sid: list(sub) for sid, sub in
              g["hour_ist"].apply(lambda s: s.value_counts()
                                  .reindex(range(24), fill_value=0).sort_index().tolist()).items()}
    monthly = (ev.groupby(["superzone_id", "month_ist"], observed=True)["id"].count()
                 .unstack(fill_value=0))
    for m in _MONTH_ORDER:
        if m not in monthly.columns:
            monthly[m] = 0
    monthly = monthly[_MONTH_ORDER]

    # most common road/area label per zone (first address segment) for naming
    seg = ev.assign(_seg=ev["location"].astype("string").str.split(",").str[0].str.strip())
    top_seg = (seg.groupby("superzone_id", observed=True)["_seg"]
                  .agg(lambda s: s.dropna().mode().iloc[0] if len(s.dropna()) else None))
    z["_top_street"] = z["superzone_id"].map(top_seg)

    # ---- KPIs ------------------------------------------------------------ #
    kpis = {
        "total_zones": int(len(z)),
        "P1": int((z["tier"] == "P1").sum()),
        "P2": int((z["tier"] == "P2").sum()),
        "P3": int((z["tier"] == "P3").sum()),
        "P4": int((z["tier"] == "P4").sum()),
        "chronic": int(z["chronic"].sum()),
        "evening_blind_spot": int(z["evening_blind_spot"].sum()),
        "emerging": int(z["emerging"].sum()),
        "forecast_rising": int(z["forecast_rising"].sum()),
        "habitual": int(z["habitual"].sum()),
        "total_events": int(len(ev)),
        "data_window": C.TIME_WINDOW_LABEL,
    }

    # ---- lean map payload ------------------------------------------------ #
    map_rows = []
    for _, r in z.iterrows():
        map_rows.append({
            "id": str(r["superzone_id"]), "name": _display_name(r),
            "lat": round(float(r["lat"]), 5),
            "lon": round(float(r["lon"]), 5), "tier": r["tier"],
            "rank": int(r["rank"]), "priority": round(float(r["priority"]), 1),
            "pressure": round(float(r["A"]), 1), "recurrence": round(float(r["B"]), 1),
            "emergence": round(float(r["C"]), 1),
            "bias_adjusted_rank": int(r["bias_adjusted_rank"]),
            "chronic": bool(r["chronic"]), "emerging": bool(r["emerging"]),
            "evening_blind_spot": bool(r["evening_blind_spot"]),
            "evening_share": round(float(r["evening_share"]), 4),
            "forecast_rising": bool(r["forecast_rising"]),
            "under_recognized": bool(r["under_recognized"]),
            "typology": r["typology"], "habitual": bool(r["habitual"]),
            "responsiveness": r["responsiveness"], "intervention": r["intervention"],
            "station": (None if pd.isna(r["police_station"]) else str(r["police_station"])),
            "n_tickets": int(r["n_tickets"]),
            # compact hour-of-day histogram (recorded enforcement activity, not traffic)
            "hourly": [int(v) for v in hourly.get(r["superzone_id"], [0] * 24)],
        })
    U.write_json(C.DATA_PROC / "map_payload.json", {"kpis": kpis, "zones": map_rows})

    # ---- precompute per-zone mixes once (avoid re-scanning events) ------- #
    def _by_group(col, n):
        out = {}
        for sid, sub in ev.groupby("superzone_id", observed=True)[col]:
            out[sid] = _top_counts(sub.dropna(), n)
        return out
    viol_mix = _by_group("primary_violation", 6)
    veh_mix = _by_group("vehicle_type", 6)
    street_mix = _by_group("location", 4)

    # ---- full per-zone detail ------------------------------------------- #
    details = {}
    for _, r in z.iterrows():
        sid = str(r["superzone_id"])
        zid = r["superzone_id"]
        details[sid] = {
            "id": sid, "name": _display_name(r),
            "lat": round(float(r["lat"]), 5), "lon": round(float(r["lon"]), 5),
            "tier": r["tier"], "rank": int(r["rank"]),
            "scores": {"pressure": round(float(r["A"]), 1),
                       "recurrence": round(float(r["B"]), 1),
                       "emergence": round(float(r["C"]), 1),
                       "priority": round(float(r["priority"]), 1)},
            "chronic": bool(r["chronic"]), "emerging": bool(r["emerging"]),
            "bias_adjusted_rank": int(r["bias_adjusted_rank"]),
            "under_recognized": bool(r["under_recognized"]),
            "exposure": {"officers": int(r["n_officers"]),
                         "active_days": int(r["exposure_days"])},
            "repeat_share": round(float(r["repeat_share"]), 3),
            "habitual": bool(r["habitual"]),
            "responsiveness": r["responsiveness"],
            "trend_slope": round(float(r["trend_slope"]), 4),
            "typology": r["typology"],
            "evening_share": round(float(r["evening_share"]), 4),
            "evening_blind_spot": bool(r["evening_blind_spot"]),
            "forecast": {"pressure": round(float(r["forecast_pressure"]), 2),
                         "score": round(float(r["forecast_score"]), 1),
                         "rising": bool(r["forecast_rising"])},
            "violation_mix": viol_mix.get(zid, []),
            "vehicle_mix": veh_mix.get(zid, []),
            "top_streets": street_mix.get(zid, []),
            "monthly_recurrence": {m: int(monthly.loc[r["superzone_id"], m])
                                   if r["superzone_id"] in monthly.index else 0
                                   for m in _MONTH_ORDER},
            "hourly_histogram": hourly.get(r["superzone_id"], [0] * 24),
            "fingerprint": fingerprints.get(sid),
            "station": (None if pd.isna(r["police_station"]) else str(r["police_station"])),
            "junction": (None if pd.isna(r["junction_mode"]) else str(r["junction_mode"])),
            "intervention": r["intervention"],
            "recommended_window": _window_for(r),
            "confidence": "high" if r["n_tickets"] >= 30 else "medium",
            "explanation": _explanation(r),
            "maps_url": f"https://www.google.com/maps?q={r['lat']:.5f},{r['lon']:.5f}",
        }
    U.write_json(C.DATA_PROC / "zones_detail.json", details)

    # ---- emerging / forecast / typology views --------------------------- #
    emerging = sorted(
        [{"id": str(r["superzone_id"]), "lat": round(float(r["lat"]), 5),
          "lon": round(float(r["lon"]), 5), "growth_ratio": round(float(r["growth_ratio"]), 2),
          "recent_vol": int(r["recent_vol"]), "tier": r["tier"],
          "station": (None if pd.isna(r["police_station"]) else str(r["police_station"]))}
         for _, r in z[z["emerging"]].iterrows()],
        key=lambda d: -(d["growth_ratio"] or 0))
    U.write_json(C.DATA_PROC / "emerging.json", emerging)

    forecast = {
        "metrics": json.loads((C.DATA_PROC / "forecaster_metrics.json").read_text()),
        "zones": sorted(
            [{"id": str(r["superzone_id"]), "lat": round(float(r["lat"]), 5),
              "lon": round(float(r["lon"]), 5),
              "forecast_score": round(float(r["forecast_score"]), 1),
              "rising": bool(r["forecast_rising"]), "tier": r["tier"]}
             for _, r in z.iterrows()],
            key=lambda d: -d["forecast_score"])[:200],
    }
    U.write_json(C.DATA_PROC / "forecast.json", forecast)

    typ_meta = json.loads((C.DATA_PROC / "typology_meta.json").read_text())
    typology = {"meta": typ_meta,
                "zones": [{"id": str(r["superzone_id"]), "lat": round(float(r["lat"]), 5),
                           "lon": round(float(r["lon"]), 5), "typology": r["typology"],
                           "tier": r["tier"]} for _, r in z.iterrows()]}
    U.write_json(C.DATA_PROC / "typology.json", typology)

    # ---- evidence points (4-dec, capped for the bundled demo) ------------ #
    pts = (ev.groupby("point_11m", observed=True)
             .agg(lat=("latitude", "mean"), lon=("longitude", "mean"),
                  n=("id", "count"), w=("event_weight", "sum")).reset_index())
    pts = pts.sort_values("w", ascending=False)
    evidence = [{"lat": round(float(r["lat"]), 4), "lon": round(float(r["lon"]), 4),
                 "n": int(r["n"]), "w": round(float(r["w"]), 2)}
                for _, r in pts.head(8000).iterrows()]
    U.write_json(C.DATA_PROC / "evidence_points.json", evidence)

    # ---- search index ---------------------------------------------------- #
    search = [{"id": d["id"], "lat": d["lat"], "lon": d["lon"], "tier": d["tier"],
               "station": d["station"], "junction": d["junction"], "name": d["name"],
               "label": (d["name"] or d["junction"] or d["station"] or d["id"])}
              for d in details.values()]
    U.write_json(C.DATA_PROC / "search_index.json", search)

    # ---- historical replay frames (compact aggregated activity) ---------- #
    # Per-zone monthly ticket counts — NOT the raw event dump. Labelled in the
    # UI as "Historical enforcement replay", never live traffic.
    replay = {
        "periods": _MONTH_ORDER,
        "labels": [_MONTH_LABEL_SHORT.get(m, m) for m in _MONTH_ORDER],
        "zones": [{"id": str(r["superzone_id"]), "name": _display_name(r),
                   "lat": round(float(r["lat"]), 5), "lon": round(float(r["lon"]), 5),
                   "tier": r["tier"],
                   "counts": [int(monthly.loc[r["superzone_id"], m])
                              if r["superzone_id"] in monthly.index else 0
                              for m in _MONTH_ORDER]}
                  for _, r in z.iterrows()],
    }
    U.write_json(C.DATA_PROC / "replay_frames.json", replay)

    # ---- optional LLM briefings (deterministic fallback always present) -- #
    _maybe_llm_briefings(z)

    print(f"[08_payload] map_payload ({len(map_rows)} zones), zones_detail, "
          f"{len(evidence)} evidence points, {len(emerging)} emerging")
    return kpis


def _maybe_llm_briefings(z):
    """Optional: per-station plain-English briefing. Deterministic by default;
    upgraded to an LLM rewrite only if CLEARLANE_LLM=1 and a key is present."""
    briefings = {}
    for st, sub in z.groupby("police_station", observed=True):
        if pd.isna(st):
            continue
        p1 = int((sub["tier"] == "P1").sum())
        bs = int(sub["evening_blind_spot"].sum())
        top = sub.sort_values("priority", ascending=False).iloc[0]
        briefings[str(st)] = (
            f"{st}: {p1} P1 zone(s), {bs} evening blind spot(s). Priority focus: "
            f"zone {top['superzone_id']} ({top['intervention']}). "
            "Recommend an evening sweep (17:00–21:00) at the flagged blind spots.")

    if os.environ.get("CLEARLANE_LLM") == "1":
        try:                                       # pragma: no cover
            briefings = _llm_rewrite(briefings)
        except Exception as e:
            print(f"[08_payload] LLM rewrite skipped ({type(e).__name__}); "
                  "using deterministic briefings")
    U.write_json(C.DATA_PROC / "briefings.json", briefings)


def _llm_rewrite(briefings):                       # pragma: no cover
    """Optional Anthropic rewrite of the deterministic briefings (flagged)."""
    import anthropic
    client = anthropic.Anthropic()
    out = {}
    for st, text in briefings.items():
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=200,
            messages=[{"role": "user", "content":
                       f"Rewrite this police deployment note crisply, 2 sentences, "
                       f"no new facts:\n{text}"}])
        out[st] = msg.content[0].text.strip()
    return out


if __name__ == "__main__":
    run()
