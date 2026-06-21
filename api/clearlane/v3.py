"""
ClearLane v3 — cell-centric read APIs + the H3 closed loop + self-learning.

This router serves the `ml.v3` pipeline (the cell-centric "live-first" rebuild,
artifacts in `data/processed/v3/`) and runs the operational feedback loop keyed by
H3 res-10 cell (not the v1 zone). It is a sibling of `operational.py`: same
three-number honesty separation, same transparent rule table, but the unit is the
hexagon and the live online-rate update reuses the Gamma-Poisson math of
`ml.v3/09_online.py`.

HONESTY CONTRACT (carried over, never violate):
  * The data is parking TICKETS, not congestion. `congestion_source` is
    `modeled` / `mappls_typical` / `live` — NEVER "measured congestion" from
    ticket data.
  * Three SEPARATE numbers per cell:
      - historical_priority  : immutable ML output (pic_score, from pic.json)
      - live_adjustment      : transparent operational boost/cooldown (decays)
      - operational_priority : clamp(historical + live_adjustment, 0..100)
  * Forecast layers are labelled (modeled day-of-week curve; predictive ETA is
    `api_unavailable` until the Mappls Predictive product is enabled).
  * All state is cell-level — NEVER per officer.

Reads work offline (filesystem fallback via db.v3_artifact). Writes need MongoDB
(collections v3_complaints, v3_tickets, v3_cell_state, v3_meta) and degrade to a
clear 503 when Mongo is absent, exactly like operational.py / force.py.
"""
from __future__ import annotations

import datetime
import math
import os
import time
from threading import Lock

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import db
from . import force                      # reuse RBAC sessions + slugify

try:                                     # bandit is optional (numpy/Thompson)
    from . import bandit
    _HAS_BANDIT = True
except Exception:                        # pragma: no cover
    _HAS_BANDIT = False

try:                                     # h3 lets us snap to the TRUE res-10 cell
    import h3
    _HAS_H3 = True
except Exception:                        # pragma: no cover - fall back to nearest
    _HAS_H3 = False

router = APIRouter(prefix="/api/v3")

# --------------------------------------------------------------------------- #
# Constants (single source — mirrors operational.OP_RULES + ml.v3/config.py)
# --------------------------------------------------------------------------- #
BBOX = {"lat_min": 12.80, "lat_max": 13.29, "lon_min": 77.44, "lon_max": 77.77}
H3_RES = 10
SNAP_MAX_M = 300.0                       # citizen pin -> nearest known cell radius
_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Transparent operational rules — every live cell adjustment lives HERE
# (same values as operational.OP_RULES so v1 zone loop and v3 cell loop agree).
OP_RULES = {
    "complaint_unverified": 5.0,
    "verified_obstruction": 12.0,
    "needs_towing": 15.0,
    "action_taken": -8.0,
    "false_alarm": -10.0,
    "cleared": None,                     # reset live adjustment to 0
    "structural_issue": 0.0,
    "decay_per_hour": 1.0,
    "max_adjustment": 40.0,
}

# Fixed resolution dropdown (PATCH .../tickets/{id}). Each maps to a cell effect
# AND a dispatch-bandit reward in [0,1] (mirrors main._BANDIT_REWARD). `resolution`
# is the suggested truth value; the caller's explicit `resolution` always wins.
V3_REASONS = {
    "verified_obstruction": {"delta": 12.0,  "reward": 0.7, "resolution": True},
    "needs_towing":         {"delta": 15.0,  "reward": 0.9, "resolution": True},
    "action_taken":         {"delta": -8.0,  "reward": 1.0, "resolution": True},
    "cleared":              {"reset": True,  "reward": 1.0, "resolution": True},
    "structural_issue":     {"escalate": True, "reward": 0.5, "resolution": True},
    "false_alarm":          {"delta": -10.0, "reward": 0.0, "resolution": False},
    "no_obstruction":       {"delta": -10.0, "reward": 0.0, "resolution": False},
    "duplicate":            {"delta": -5.0,  "reward": 0.0, "resolution": False},
    "other":                {"delta": 0.0,   "reward": 0.5, "resolution": None},
}
REASON_VALUES = list(V3_REASONS.keys())

# Officer-feedback kinds == the same vocabulary (reused by /officer-feedback).
FEEDBACK_KINDS = REASON_VALUES

# Gamma-Poisson prior (verbatim from ml.v3/config.py ONLINE_PRIOR_*). Posterior is
# Gamma(s0+Σy, r0+n): a new verified day updates E[λ] by ADDING TWO NUMBERS.
ONLINE_PRIOR_SHAPE = 1.0
ONLINE_PRIOR_RATE = 1.0

RECOMPUTE_INTERVAL_H = 24.0              # cron cadence (daily on Vercel Hobby) -> /online/status due
LAZY_MAX_AGE_H = 24.0                    # read path force-refreshes if staler than this
LAZY_LOCK_TTL_S = 180                    # lock window so two cold readers don't both run

TICKET_KINDS = {"complaint", "chalan", "action"}

_lock = Lock()


# --------------------------------------------------------------------------- #
# JSON helpers (strip Mongo _id, scrub NaN/Inf) — same contract as ok() elsewhere
# --------------------------------------------------------------------------- #
def _safe(obj):
    if isinstance(obj, dict):
        return {k: _safe(v) for k, v in obj.items() if k != "_id"}
    if isinstance(obj, list):
        return [_safe(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def ok(payload):
    return JSONResponse(content=_safe(payload))


def _require_mongo():
    if not db.mongo_enabled():
        raise HTTPException(503, "MongoDB not configured (set MONGODB_URI).")


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def in_bbox(lat, lon):
    return (BBOX["lat_min"] <= lat <= BBOX["lat_max"] and
            BBOX["lon_min"] <= lon <= BBOX["lon_max"])


def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


# --------------------------------------------------------------------------- #
# Artifact-derived cell indices (built once per process; artifacts are static)
# --------------------------------------------------------------------------- #
_IDX: dict | None = None


def _indices() -> dict:
    """Master cell lookups composed from the v3 JSON artifacts:
      coords : h3 -> (lat, lon, police_station)   (all 6,483 occupied cells)
      intens : h3 -> bias-corrected intensity 0..100
      pic    : h3 -> pic top-cell record (pic_score, congestion_*)
      pic_list: pic.json top_cells (the map's primary PIC layer)
      fc     : h3 -> forecast_daily record (dow_curve)
      online : h3 -> online_state record (e_lambda, drift_z, emerging, shape/rate)
    """
    global _IDX
    if _IDX is not None:
        return _IDX
    hot = db.v3_artifact("hotspots.json") or {}
    pic = db.v3_artifact("pic.json") or {}
    fc = db.v3_artifact("forecast_daily.json") or {}
    on = db.v3_artifact("online_state.json") or {}

    coords, intens = {}, {}
    for c in hot.get("cells", []):
        h = c["h3_r10"]
        coords[h] = (c["lat"], c["lon"], c.get("police_station"))
        intens[h] = c.get("intensity")

    pic_list = pic.get("top_cells", []) or []
    picmap = {}
    for c in pic_list:
        h = c["h3_r10"]
        picmap[h] = c
        coords.setdefault(h, (c["lat"], c["lon"], c.get("police_station")))
        intens.setdefault(h, c.get("intensity"))

    fcmap, fc_max = {}, 1.0
    for c in fc.get("cells", []):
        h = c["h3_r10"]
        fcmap[h] = c
        coords.setdefault(h, (c["lat"], c["lon"], c.get("police_station")))
        curve = c.get("dow_curve") or []
        if curve:
            fc_max = max(fc_max, max(curve))

    onmap = {}
    for c in on.get("cells", []):
        onmap[c["h3_r10"]] = c
    for c in on.get("emerging_cells", []):
        onmap.setdefault(c["h3_r10"], c)

    _IDX = {
        "coords": coords, "intens": intens,
        "pic": picmap, "pic_list": pic_list,
        "fc": fcmap, "fc_order": fc.get("dow_order", _DOW), "fc_max": fc_max,
        "online": onmap,
        "congestion_mode": pic.get("congestion_mode", "modeled-only"),
    }
    return _IDX


def _nearest_cell(lat, lon):
    """Nearest occupied cell by haversine. O(n) over ~6.5k cells — fine for the
    operational write volume; the read path never calls this."""
    coords = _indices()["coords"]
    best, best_d = None, float("inf")
    for h, (clat, clon, _st) in coords.items():
        d = _haversine_m(lat, lon, clat, clon)
        if d < best_d:
            best, best_d = h, d
    return best, best_d


def _snap_cell(lat, lon):
    """Snap a (lat,lon) report to an H3 res-10 cell.

    With h3 available we take the TRUE containing cell; if it is one of our
    occupied cells we use its canonical centroid + station, otherwise it is a new
    quiet cell (valid id) and we borrow the nearest known cell's station for
    context. Without h3 we fall back to the nearest known cell within SNAP_MAX_M.
    Returns (cell, snap_lat, snap_lon, station, distance_m, method)."""
    coords = _indices()["coords"]
    if _HAS_H3:
        try:
            cell = h3.latlng_to_cell(lat, lon, H3_RES)
        except Exception:                # pragma: no cover
            cell = None
        if cell:
            if cell in coords:
                clat, clon, st = coords[cell]
                return cell, clat, clon, st, 0.0, "h3_exact_known"
            try:
                clat, clon = h3.cell_to_latlng(cell)
            except Exception:            # pragma: no cover
                clat, clon = lat, lon
            nz, d = _nearest_cell(lat, lon)
            st = coords[nz][2] if nz else None
            return cell, clat, clon, st, (round(d, 1) if nz else None), "h3_new_cell"
    nz, d = _nearest_cell(lat, lon)
    if nz is None:
        return None, lat, lon, None, None, "unresolved"
    clat, clon, st = coords[nz]
    method = "nearest_known" if d <= SNAP_MAX_M else "nearest_far"
    return nz, clat, clon, st, round(d, 1), method


def _station_of(cell):
    c = _indices()["coords"].get(cell)
    return c[2] if c else None


def _coords_of(cell):
    c = _indices()["coords"].get(cell)
    return (c[0], c[1]) if c else (None, None)


def _hist_priority(cell):
    """historical_priority = pic_score (top-200 PIC cells) else bias-corrected
    intensity (still a 0..100 ML output, never a congestion claim)."""
    idx = _indices()
    p = idx["pic"].get(cell)
    if p and p.get("pic_score") is not None:
        return float(p["pic_score"])
    iv = idx["intens"].get(cell)
    return float(iv) if iv is not None else 0.0


# --------------------------------------------------------------------------- #
# HOURLY CONGESTION OVERLAY (stage 13 artifact; constant fallback) — the honest
# "24 heatmaps". Congestion genuinely varies by hour, so it modulates the map by
# hour; the historical propensity (pic_score) stays day-of-week. The shape is
# MODELED from documented Bengaluru commute peaks — NEVER measured from tickets
# (ticket time is upload time, so ticket COUNTS never vary by hour).
# --------------------------------------------------------------------------- #
_HC_BASE = [0.10, 0.07, 0.05, 0.05, 0.06, 0.12, 0.28, 0.55, 0.82, 0.95, 0.88, 0.70,
            0.62, 0.60, 0.58, 0.62, 0.72, 0.90, 1.00, 0.95, 0.80, 0.55, 0.32, 0.18]
_HC_AMP = {"ring_road": 1.00, "arterial": 0.95, "commercial": 0.90,
           "main_road": 0.85, "local": 0.45, "unknown": 0.70}
_HC_FLOOR = 0.08
# how strongly the hour modulates the displayed heat (keeps spatial structure but
# lets the map visibly pulse with the commute): heat = base·(BASE_W + CONG_W·cong)
_HC_BASE_W, _HC_CONG_W = 0.40, 0.60
_HC: dict | None = None


def _hourly_congestion():
    global _HC
    if _HC is not None:
        return _HC
    d = db.v3_artifact("hourly_congestion.json")
    if d and d.get("curves"):
        _HC = {"curves": d["curves"], "global": d.get("global"),
               "provenance": d.get("provenance", "modeled_typical")}
    else:                                   # constant fallback (Vercel w/o artifact)
        curves = {cls: [round(min(1.0, max(0.0, _HC_FLOOR + b * amp)), 4) for b in _HC_BASE]
                  for cls, amp in _HC_AMP.items()}
        glob = [round(min(1.0, max(0.0, _HC_FLOOR + b * 0.70)), 4) for b in _HC_BASE]
        _HC = {"curves": curves, "global": glob, "provenance": "modeled_typical_fallback"}
    return _HC


def _cong_at(road_class, hour):
    """Typical congestion 0..1 for a road class at an hour (0..23)."""
    hc = _hourly_congestion()
    h = int(hour) % 24
    cur = (hc["curves"].get(road_class or "unknown") or hc.get("global")
           or hc["curves"].get("unknown"))
    try:
        return float(cur[h])
    except Exception:                       # pragma: no cover
        return 0.5


def _hour_heat(base, road_class, hour):
    """Hour-modulated display heat: historical propensity × typical congestion."""
    return _clamp(base * (_HC_BASE_W + _HC_CONG_W * _cong_at(road_class, hour)))


def _city_hour_profile():
    """City-average typical congestion per hour (24) for the time scrubber."""
    hc = _hourly_congestion()
    g = hc.get("global")
    if g and len(g) == 24:
        return [round(float(x), 3) for x in g]
    cur = hc["curves"].get("arterial") or next(iter(hc["curves"].values()))
    return [round(float(x), 3) for x in cur]


def _ist_hour():
    return datetime.datetime.now(_IST).hour


# --------------------------------------------------------------------------- #
# Cell live state (three-number separation), persisted in v3_cell_state
# --------------------------------------------------------------------------- #
def _decayed_boost(boost, updated_ts, now):
    if not boost:
        return 0.0
    hours = max(0.0, (now - (updated_ts or now)) / 3600.0)
    return max(0.0, boost - OP_RULES["decay_per_hour"] * hours)


def _bump_cell(cell, delta=None, reset=False, state=None, escalate=False,
               add_complaint=False):
    """Apply a transparent live adjustment to a cell (decayed, clamped). NEVER
    touches the historical ML score — only v3_cell_state.boost."""
    now = time.time()
    c = db.col("v3_cell_state")
    row = c.find_one({"_id": cell})
    boost = _decayed_boost(row.get("boost"), row.get("updated_ts"), now) if row else 0.0
    if reset:
        boost = 0.0
    elif delta is not None:
        boost = max(0.0, min(OP_RULES["max_adjustment"], boost + delta))
    comp = (row.get("complaints", 0) if row else 0) + (1 if add_complaint else 0)
    new_state = state if state is not None else (row.get("dispatch_state") if row else None)
    esc = 1 if escalate else (row.get("escalated", 0) if row else 0)
    lat, lon = _coords_of(cell)
    c.update_one({"_id": cell}, {"$set": {
        "cell": cell, "boost": round(boost, 3), "dispatch_state": new_state,
        "escalated": esc, "complaints": comp, "updated_ts": now,
        "lat": lat, "lon": lon, "police_station": _station_of(cell),
    }}, upsert=True)
    return boost


def _live_adjustment(cell, now=None):
    now = now or time.time()
    row = db.col("v3_cell_state").find_one({"_id": cell}) if db.mongo_enabled() else None
    if not row:
        return 0.0, None
    return _decayed_boost(row.get("boost"), row.get("updated_ts"), now), row


def _cell_three_numbers(cell, row=None, now=None):
    now = now or time.time()
    if row is None and db.mongo_enabled():
        row = db.col("v3_cell_state").find_one({"_id": cell})
    boost = _decayed_boost((row or {}).get("boost"), (row or {}).get("updated_ts"), now)
    hist = _hist_priority(cell)
    return hist, boost, _clamp(hist + boost)


def _bandit_reward(cell, reward):
    """Feed the in-process dispatch bandit (explore/exploit) a cell outcome. The
    arm context is built from the cell's ML signals; never edits ML scores."""
    if not _HAS_BANDIT:
        return
    idx = _indices()
    p = idx["pic"].get(cell, {})
    on = idx["online"].get(cell, {})
    zone = {
        "id": cell,
        "forecast_score": (idx["fc"].get(cell, {}).get("weekly_expected") or 0),
        "pressure": p.get("pic_score") or idx["intens"].get(cell) or 0,
        "under_observed": (on.get("drift_z") or 0) * 10,
        "dispatch_priority": p.get("pic_score") or idx["intens"].get(cell) or 0,
    }
    try:
        bandit.reward(zone, float(reward))
    except Exception:                    # pragma: no cover - bandit is best-effort
        pass


# --------------------------------------------------------------------------- #
# init (indexes + the lazy-recompute lock doc). Idempotent; no-op without Mongo.
# --------------------------------------------------------------------------- #
_INIT_DONE = False


def init_db():
    if not db.mongo_enabled():
        return
    try:
        db.col("v3_complaints").create_index("created_ts")
        db.col("v3_complaints").create_index("cell")
        db.col("v3_complaints").create_index("created_by")
        db.col("v3_tickets").create_index("updated_ts")
        db.col("v3_tickets").create_index("cell")
        db.col("v3_tickets").create_index("station_slug")
        db.col("v3_cell_state").create_index("updated_ts")
        db.col("v3_meta").update_one({"_id": "lock"},
                                     {"$setOnInsert": {"until": 0.0}}, upsert=True)
    except Exception:                    # pragma: no cover - first-run races
        pass


def _ensure_init():
    """Lazy once-per-process bootstrap (Vercel does not run ASGI startup reliably)."""
    global _INIT_DONE
    if _INIT_DONE or not db.mongo_enabled():
        return
    init_db()
    _INIT_DONE = True


# --------------------------------------------------------------------------- #
# Auth helpers (soft for reads, strict for writes) — reuse force.py sessions
# --------------------------------------------------------------------------- #
def _session_for(authorization):
    if not authorization or not db.mongo_enabled():
        return None
    if not authorization.lower().startswith("bearer "):
        return None
    tok = authorization[7:].strip()
    try:
        return db.col("fz_sessions").find_one({"token": tok})
    except Exception:                    # pragma: no cover
        return None


def _require_session(authorization):
    s = _session_for(authorization)
    if not s:
        raise HTTPException(401, "Not authenticated (police/government login required).")
    return s


def _scope_ok(sess, station_name):
    if sess.get("role") == "govt":
        return True
    return force.slugify(station_name or "") == sess.get("scope")


# --------------------------------------------------------------------------- #
# READ ENDPOINTS
# --------------------------------------------------------------------------- #
def _kpis():
    """Compose the headline KPIs honestly from the evaluation/metric artifacts."""
    pic = db.v3_artifact("pic.json") or {}
    conc = (db.v3_artifact("h3_concentration.json") or {}).get("concentration", {})
    nb = db.v3_artifact("nb_metrics.json") or {}
    onm = db.v3_artifact("online_metrics.json") or {}
    dm = db.v3_artifact("dispatch_metrics.json") or {}
    fcm = db.v3_artifact("forecaster_daily_metrics.json") or {}
    ev = db.v3_artifact("evaluation.json") or {}
    sim = db.v3_artifact("sim_rl.json") or {}
    tiny = conc.get("cells_for_50pct", {})
    return {
        "n_cells": pic.get("n_cells"),
        "congestion_mode": pic.get("congestion_mode"),
        "n_sig_hot": (nb.get("significance") or {}).get("n_sig_hot"),
        "n_under_policed": nb.get("n_under_policed"),
        "n_emerging": onm.get("n_emerging"),
        "concentration_tiny_slice": {
            "n_cells": tiny.get("n_cells"), "pct_of_all_cells": tiny.get("pct_of_all_cells"),
            "share_of_violations_pct": (conc.get("top_2.5pct_cells") or {}).get("share_of_violations_pct"),
            "label": "tiny-slice: a few % of cells hold ~half of violations",
        },
        "dispatch_uplift_vs_random": dm.get("uplift_vs_random"),
        "dispatch_covered_pct": dm.get("covered_pct"),
        "forecaster_beats_baseline": fcm.get("beats_baseline"),
        "forecaster_spearman": fcm.get("spearman"),
        "sim_uplift_vs_random": (sim.get("uplift_vs_random") or {}).get("linucb"),
        "sim_pct_of_oracle": (sim.get("pct_of_oracle") or {}).get("linucb"),
        "evaluation": {"n_pass": ev.get("n_pass"), "n_capabilities": ev.get("n_capabilities")},
        "time_window": "Enforcement records · Nov 2023 – Apr 2024",
    }


@router.get("/map")
def v3_map(when: str = Query("now", pattern="^(now|today|tomorrow)$"),
           hour: int | None = Query(None, ge=0, le=23),
           limit: int = Query(250, ge=1, le=2000),
           authorization: str | None = Header(default=None)):
    """The single composed payload the map renders, hour-aware. The displayed
    `intensity` = historical propensity (pic_score, day-of-week when forecasting)
    × MODELED typical congestion for the chosen hour. Congestion genuinely varies
    by hour; ticket COUNTS never do (upload time, not parking time). `now` overlays
    the live operational boost; `today`/`tomorrow` overlay the forecast_daily
    day-of-week curve. Served from the DB-cached hourly heatmap when present (kept
    fresh by the govt force-recompute / hourly cron), else composed inline."""
    _ensure_init()
    _maybe_lazy_recompute()              # 24h read-path safety net (best-effort)
    idx = _indices()
    now = time.time()
    hour_used = hour if hour is not None else _ist_hour()

    target_dow = None
    if when in ("today", "tomorrow"):
        base = datetime.datetime.now(_IST)
        if when == "tomorrow":
            base += datetime.timedelta(days=1)
        target_dow = _DOW[base.weekday()]   # Mon..Sun
    fc_order = idx["fc_order"]
    fc_max = idx["fc_max"] or 1.0
    forecast_mode = when in ("today", "tomorrow")

    states = {}
    if db.mongo_enabled():
        try:
            states = {s["_id"]: s for s in db.col("v3_cell_state").find()}
        except Exception:                # pragma: no cover
            states = {}

    # DB-cached deterministic hour heat (historical × congestion), baked by the
    # govt force-recompute / cron. {h3: [24]}. Live boost is still applied on top.
    cache = db.v3_artifact("heatmap_hourly.json") or {}
    cache_cells = cache.get("cells") or {}

    cells = []
    for c in idx["pic_list"][:limit]:
        h = c["h3_r10"]
        hist = float(c.get("pic_score") or 0.0)
        rc = c.get("road_class")
        cong = _cong_at(rc, hour_used)
        boost = _decayed_boost((states.get(h) or {}).get("boost"),
                               (states.get(h) or {}).get("updated_ts"), now)
        on = idx["online"].get(h, {})

        # historical base for this lens (day-of-week when forecasting)
        finten = None
        base_val = hist
        if target_dow is not None:
            fcc = idx["fc"].get(h)
            if fcc and fcc.get("dow_curve"):
                try:
                    val = fcc["dow_curve"][fc_order.index(target_dow)]
                    base_val = 100.0 * val / fc_max
                except Exception:        # pragma: no cover
                    base_val = hist

        cached24 = cache_cells.get(h)
        if cached24 and not forecast_mode:
            heat = float(cached24[hour_used % 24])
        else:
            heat = _hour_heat(base_val, rc, hour_used)
        if forecast_mode:
            finten = round(heat, 1)

        cells.append({
            "h3_r10": h, "lat": c["lat"], "lon": c["lon"],
            "police_station": c.get("police_station"),
            "road_class": rc,
            "intensity": round(heat, 1),            # hour-modulated display heat
            "pic_score": c.get("pic_score"),        # immutable historical propensity
            "pic_rank": c.get("pic_rank"),
            "congestion_severity": c.get("congestion_severity"),
            "congestion_source": c.get("congestion_source"),
            "congestion_hour": round(cong, 3),      # typical congestion at this hour
            "forecast_intensity": finten,
            "emerging": bool(on.get("emerging", False)),
            "drift_z": on.get("drift_z"),
            "historical_priority": round(hist, 1),
            "live_adjustment": round(boost, 1),
            "operational_priority": round(_clamp(hist + boost), 1),
        })

    meta = (db.col("v3_meta").find_one({"_id": "state"}) if db.mongo_enabled() else None) or {}
    hc_prov = _hourly_congestion().get("provenance", "modeled_typical")
    hh = f"{hour_used:02d}:00"
    return ok({
        "when": when, "hour": hour_used, "dow": target_dow,
        "source": "forecast" if forecast_mode else "live",
        "congestion_mode": idx["congestion_mode"],
        "congestion_provenance": hc_prov,
        "hour_profile": _city_hour_profile(),   # 24 city-typical congestion values
        "predictive_eta": False,
        "heatmap_cached": bool(cache_cells) and not forecast_mode,
        "source_note": (
            (f"Forecast · {target_dow} @ {hh} — modeled day-of-week propensity × "
             f"modeled TYPICAL congestion for the hour. " if forecast_mode
             else f"Live @ {hh} — historical PIC × modeled TYPICAL congestion for "
                  f"the hour, + live operational boost. ")
            + "Congestion is MODELED from typical commute patterns, not measured "
              "from tickets; ticket counts are day-of-week (upload time)."),
        "badge": (f"{'Forecast · ' + target_dow if forecast_mode else 'Live'} · "
                  f"{hh} · congestion MODELED (typical), counts are day-of-week"),
        "n_cells": len(cells), "cells": cells, "kpis": _kpis(),
        "generated_at": _now_iso(), "last_calc": meta.get("last_calc"),
    })


@router.get("/hotspots")
def v3_hotspots(limit: int = Query(2000, ge=1, le=10000),
                station: str | None = None):
    """Bias-corrected NB hotspot cells (the dense intensity layer). All occupied
    cells; filter by police_station."""
    d = db.v3_artifact("hotspots.json") or {}
    cells = d.get("cells", [])
    if station:
        sl = force.slugify(station)
        cells = [c for c in cells if force.slugify(c.get("police_station") or "") == sl]
    return ok({"model": d.get("model"), "n_cells": len(cells),
               "cells": cells[:limit]})


@router.get("/pic")
def v3_pic():
    """Parking-Induced-Congestion cells (intensity × congestion severity)."""
    return ok(db.v3_artifact("pic.json"))


@router.get("/online")
def v3_online():
    """Gamma-Poisson per-cell rate + emerging-hotspot drift alarm (stage 09).
    Overlays the per-cell live online update from the self-learning recompute."""
    d = db.v3_artifact("online_state.json") or {}
    out = {"metrics": d.get("metrics"), "n_emerging": d.get("n_emerging"),
           "emerging_cells": d.get("emerging_cells", []),
           "cells": d.get("cells", [])}
    if db.mongo_enabled():
        try:
            live = {s["_id"]: s for s in db.col("v3_cell_state").find(
                {"online_e_lambda": {"$exists": True}})}
            for c in out["emerging_cells"] + out["cells"]:
                s = live.get(c.get("h3_r10"))
                if s:
                    c["online_e_lambda_live"] = s.get("online_e_lambda")
                    c["online_y_observed"] = s.get("online_y")
        except Exception:                # pragma: no cover
            pass
    return ok(out)


@router.get("/online/status")
def v3_online_status():
    """Self-learning freshness: when did the last online recompute run, and is one
    due (hourly cadence)?"""
    if not db.mongo_enabled():
        return ok({"mongo": False, "last_calc": None, "age_hours": None,
                   "due": False, "interval_hours": RECOMPUTE_INTERVAL_H,
                   "note": "Mongo not configured — self-learning state lives in Mongo."})
    meta = db.col("v3_meta").find_one({"_id": "state"}) or {}
    last = meta.get("last_calc")
    age = (time.time() - last) / 3600.0 if last else None
    return ok({
        "mongo": True, "last_calc": last,
        "age_hours": round(age, 3) if age is not None else None,
        "due": (age is None) or (age >= RECOMPUTE_INTERVAL_H),
        "interval_hours": RECOMPUTE_INTERVAL_H, "lazy_max_age_hours": LAZY_MAX_AGE_H,
        "last_summary": {k: meta.get(k) for k in
                         ("reason", "n_new_complaints", "n_new_closed",
                          "n_cells_updated", "duration_ms", "prev_calc")},
    })


@router.get("/forecast/daily")
def v3_forecast_daily():
    """Day-of-week violation propensity per cell (LightGBM Poisson, temporal
    holdout). Propensity for FUTURE tickets — never congestion, never hour-of-day."""
    return ok(db.v3_artifact("forecast_daily.json"))


@router.get("/forecast/eta")
def v3_forecast_eta():
    """Predictive 24h ETA curve per corridor. Honestly `api_unavailable` until the
    Mappls Predictive-Distance-Matrix product is enabled."""
    return ok(db.v3_artifact("forecast_eta.json"))


@router.get("/dispatch/plan")
def v3_dispatch_plan():
    """Exact MCLP patrol plan (stage 08). Resolves each route's H3 `stops[]` to
    coordinates + pic_score, and attaches the live operational rerank when present."""
    d = db.v3_artifact("dispatch_plan.json") or {}
    idx = _indices()
    now = time.time()
    states = {}
    if db.mongo_enabled():
        try:
            states = {s["_id"]: s for s in db.col("v3_cell_state").find()}
        except Exception:                # pragma: no cover
            states = {}

    routes = []
    for r in d.get("routes", []):
        stops = []
        for h in r.get("stops", []):
            lat, lon = _coords_of(h)
            hist = _hist_priority(h)
            boost = _decayed_boost((states.get(h) or {}).get("boost"),
                                   (states.get(h) or {}).get("updated_ts"), now)
            stops.append({
                "h3_r10": h, "lat": lat, "lon": lon,
                "police_station": _station_of(h),
                "pic_score": round(hist, 1),
                "operational_priority": round(_clamp(hist + boost), 1),
                "live_adjustment": round(boost, 1),
                "emerging": bool(idx["online"].get(h, {}).get("emerging", False)),
            })
        routes.append({**{k: r.get(k) for k in ("station", "n_stops", "route_km")},
                       "stops": stops})

    meta = (db.col("v3_meta").find_one({"_id": "state"}) if db.mongo_enabled() else None) or {}
    return ok({**{k: d.get(k) for k in
                  ("officers", "solver", "covered_pic", "total_pic",
                   "covered_pct", "n_stations")},
               "routes": routes,
               "live_rerank": meta.get("dispatch_rerank", []),
               "last_calc": meta.get("last_calc")})


@router.get("/evaluation")
def v3_evaluation():
    """One PASS/REVIEW gate per capability (stage 11 scorecard)."""
    return ok(db.v3_artifact("evaluation.json"))


@router.get("/causal")
def v3_causal():
    """Quasi-causal cell×month two-way FE (enforcement responsiveness). Honest:
    estimates exposure(t) -> change in violations(t+1), NOT measured congestion."""
    return ok(db.v3_artifact("causal.json"))


@router.get("/sim")
def v3_sim():
    """Simulation dispatch policy: LinUCB vs random/greedy vs hindsight oracle."""
    return ok(db.v3_artifact("sim_rl.json"))


@router.get("/stations")
def v3_stations(authorization: str | None = Header(default=None)):
    """Per-police-station rollup for the government view: historical ticket volume,
    average bias-corrected intensity, top cells, plus live open/closed ticket
    counts. Aggregated to the station level ONLY (never per officer)."""
    _ensure_init()
    agg = _stations_static()
    if db.mongo_enabled():
        try:
            for coll, field_open, field_closed in (("v3_complaints", "open", "closed"),
                                                   ("v3_tickets", "open", "closed")):
                for row in db.col(coll).aggregate([
                        {"$group": {"_id": {"slug": "$station_slug", "status": "$status"},
                                    "n": {"$sum": 1}}}]):
                    slug = (row["_id"] or {}).get("slug")
                    st = agg.get(slug)
                    if not st:
                        continue
                    if (row["_id"] or {}).get("status") == "closed":
                        st["closed"] += row["n"]
                    else:
                        st["open"] += row["n"]
        except Exception:                # pragma: no cover
            pass
    out = sorted(agg.values(), key=lambda s: -(s["n_tickets"] or 0))
    return ok(out)


_STATIONS_CACHE: list | None = None


def _stations_static():
    """Static per-station rollup from hotspots.json (cached). Returns slug->dict
    with open/closed reset to 0 for the caller to fill from Mongo."""
    global _STATIONS_CACHE
    if _STATIONS_CACHE is None:
        hot = db.v3_artifact("hotspots.json") or {}
        by = {}
        for c in hot.get("cells", []):
            name = c.get("police_station")
            if not name:
                continue
            slug = force.slugify(name)
            s = by.setdefault(slug, {"slug": slug, "name": name, "_lat_w": 0.0,
                                     "_lon_w": 0.0, "_w": 0.0, "n_tickets": 0,
                                     "_inten": [], "_cells": []})
            cnt = c.get("count") or 0
            s["n_tickets"] += int(cnt)
            w = max(cnt, 1)
            s["_lat_w"] += c["lat"] * w
            s["_lon_w"] += c["lon"] * w
            s["_w"] += w
            if c.get("intensity") is not None:
                s["_inten"].append(c["intensity"])
            s["_cells"].append((c.get("intensity") or 0, c["h3_r10"], c["lat"], c["lon"]))
        out = {}
        for slug, s in by.items():
            top = sorted(s["_cells"], reverse=True)[:5]
            out[slug] = {
                "slug": slug, "name": s["name"],
                "lat": round(s["_lat_w"] / s["_w"], 6) if s["_w"] else None,
                "lon": round(s["_lon_w"] / s["_w"], 6) if s["_w"] else None,
                "n_tickets": s["n_tickets"],
                "intensity_avg": round(sum(s["_inten"]) / len(s["_inten"]), 2) if s["_inten"] else None,
                "top_cells": [{"h3_r10": h, "lat": la, "lon": lo, "intensity": round(iv, 1)}
                              for iv, h, la, lo in top],
            }
        _STATIONS_CACHE = list(out.values())
    # fresh copy each call (caller mutates open/closed)
    return {s["slug"]: {**s, "open": 0, "closed": 0} for s in _STATIONS_CACHE}


# --------------------------------------------------------------------------- #
# TICKET LEDGER — unified view over v3_complaints (kind=complaint) and v3_tickets
# (kind=chalan|action). One global id counter keeps ids unambiguous across both.
# --------------------------------------------------------------------------- #
def _ticket_view(doc, kind_default="complaint", redact=False):
    out = {
        "id": doc.get("id"), "kind": doc.get("kind", kind_default),
        "cell": doc.get("cell"), "lat": doc.get("lat"), "lon": doc.get("lon"),
        "category": doc.get("category"),
        "traffic_caused": doc.get("traffic_caused"),
        "description": doc.get("description"),
        "vehicle_type": doc.get("vehicle_type"),
        "vehicle_number": doc.get("vehicle_number"),
        "status": doc.get("status"), "resolution": doc.get("resolution"),
        "reason": doc.get("reason"), "reason_other": doc.get("reason_other"),
        "created_ts": doc.get("created_ts"), "updated_ts": doc.get("updated_ts"),
        "station": doc.get("station"), "station_slug": doc.get("station_slug"),
        "created_by": doc.get("created_by"),
        "labels": doc.get("labels"), "complaint_id": doc.get("complaint_id"),
    }
    if redact:                            # public/community view: drop PII
        out["vehicle_number"] = None
        out["created_by"] = None
    return out


def _find_ticket(tid):
    """Locate a ticket by id across both collections. Returns (collection, doc)."""
    for coll in ("v3_complaints", "v3_tickets"):
        d = db.col(coll).find_one({"id": tid})
        if d:
            return coll, d
    return None, None


@router.get("/tickets")
def v3_tickets(role: str | None = None, station: str | None = None,
               status: str | None = Query(None, pattern="^(open|closed)$"),
               cell: str | None = None, kind: str | None = None,
               limit: int = Query(200, ge=1, le=2000),
               authorization: str | None = Header(default=None),
               x_citizen_id: str | None = Header(default=None)):
    """Unified ticket tracking. Government (auth) sees all; a station session sees
    its own; a citizen (X-Citizen-Id header or ?citizen_id) sees their own;
    unauthenticated callers get the public OPEN community feed with PII redacted."""
    if not db.mongo_enabled():
        return ok([])
    _ensure_init()
    sess = _session_for(authorization)
    q = {}
    if cell:
        q["cell"] = cell
    if status:
        q["status"] = status

    redact = False
    if sess and sess.get("role") == "govt":
        if station:
            q["station_slug"] = force.slugify(station)
    elif sess and sess.get("role") == "station":
        q["station_slug"] = sess.get("scope")
    elif x_citizen_id:
        q["created_by"] = x_citizen_id
    else:                                 # public community feed
        q["status"] = "open"
        q.setdefault("kind", "complaint")
        redact = True
    if kind:
        q["kind"] = kind

    rows = []
    for coll, kd in (("v3_complaints", "complaint"), ("v3_tickets", "chalan")):
        cur = db.col(coll).find(q).sort("created_ts", -1).limit(limit)
        rows += [_ticket_view(d, kd, redact=redact) for d in cur]
    rows.sort(key=lambda r: -(r.get("created_ts") or 0))
    return ok(rows[:limit])


@router.get("/tickets/{tid}")
def v3_ticket_detail(tid: int, authorization: str | None = Header(default=None),
                     x_citizen_id: str | None = Header(default=None)):
    _require_mongo()
    _, doc = _find_ticket(tid)
    if not doc:
        raise HTTPException(404, "Ticket not found.")
    sess = _session_for(authorization)
    redact = not (sess or (x_citizen_id and x_citizen_id == doc.get("created_by")))
    return ok(_ticket_view(doc, redact=redact))


# --------------------------------------------------------------------------- #
# WRITE ENDPOINTS — the H3 closed loop (complaint -> verify -> dispatch -> clear)
# --------------------------------------------------------------------------- #
class ComplaintIn(BaseModel):
    lat: float
    lon: float
    category: str = Field(default="illegal_parking", max_length=60)
    traffic_caused: bool = False
    description: str = Field(default="", max_length=500)
    vehicle_type: str = Field(default="", max_length=40)
    vehicle_number: str = Field(default="", max_length=24)
    citizen_id: str = Field(default="", max_length=80)


@router.post("/complaints")
def post_complaint(body: ComplaintIn,
                   x_citizen_id: str | None = Header(default=None)):
    """Citizen report (open). Snaps to the nearest H3 cell, creates a `complaint`
    ticket (status=open) and bumps that cell's transparent live_adjustment."""
    _require_mongo()
    _ensure_init()
    if not in_bbox(body.lat, body.lon):
        raise HTTPException(422, "Coordinate outside the Bengaluru bounding box.")
    cell, slat, slon, station, dist, method = _snap_cell(body.lat, body.lon)
    if cell is None:
        raise HTTPException(422, "Could not resolve an H3 cell for this location.")
    now = time.time()
    plate = (body.vehicle_number or "").upper().strip()
    citizen = (body.citizen_id or x_citizen_id or "").strip() or "anon"
    with _lock:
        cid = db.next_id("v3_ticketseq")
        db.col("v3_complaints").insert_one({
            "_id": cid, "id": cid, "kind": "complaint",
            "cell": cell, "lat": body.lat, "lon": body.lon,
            "snap_lat": slat, "snap_lon": slon, "snap_method": method,
            "distance_m": dist, "category": body.category,
            "traffic_caused": bool(body.traffic_caused),
            "description": body.description, "vehicle_type": body.vehicle_type,
            "vehicle_number": plate, "station": station,
            "station_slug": force.slugify(station) if station else None,
            "created_by": citizen, "status": "open", "resolution": None,
            "reason": None, "reason_other": None,
            "created_ts": now, "updated_ts": now,
        })
        boost = _bump_cell(cell, delta=OP_RULES["complaint_unverified"], add_complaint=True)
    hist, _, opv = _cell_three_numbers(cell)
    return ok({
        "id": cid, "kind": "complaint", "cell": cell,
        "snapped_to": method, "distance_m": dist,
        "station": station, "vehicle_number": plate or None,
        "status": "open", "created_by": citizen,
        "historical_priority": round(hist, 1),
        "live_adjustment": round(boost, 1),
        "operational_priority": round(opv, 1),
        "acknowledgement": ("Thanks — your report nudged this cell's live priority. "
                            "It does not change the historical ML score; an officer "
                            "verifies before it counts as a real obstruction."),
    })


class TicketIn(BaseModel):
    cell: str | None = Field(default=None, max_length=24)
    complaint_id: int | None = None
    kind: str = Field(default="chalan", max_length=16)
    category: str = Field(default="", max_length=60)
    traffic_caused: bool = False
    description: str = Field(default="", max_length=500)
    vehicle_type: str = Field(default="", max_length=40)
    vehicle_number: str = Field(default="", max_length=24)
    labels: dict | None = None
    note: str = Field(default="", max_length=300)


@router.post("/tickets")
def post_ticket(body: TicketIn, authorization: str | None = Header(default=None)):
    """Police-created ticket (chalan/action). Requires a station or government
    session; a station may only write to cells in its own area."""
    _require_mongo()
    _ensure_init()
    sess = _require_session(authorization)
    kind = body.kind if body.kind in ("chalan", "action") else "chalan"

    cell = body.cell
    comp = None
    if not cell and body.complaint_id is not None:
        comp = db.col("v3_complaints").find_one({"id": body.complaint_id})
        if not comp:
            raise HTTPException(404, "complaint_id not found.")
        cell = comp.get("cell")
    if not cell:
        raise HTTPException(422, "Provide `cell` or a valid `complaint_id`.")
    station = _station_of(cell)
    if not _scope_ok(sess, station):
        raise HTTPException(403, "Out of scope: this cell is not in your station's area.")
    lat, lon = _coords_of(cell)
    now = time.time()
    with _lock:
        tid = db.next_id("v3_ticketseq")
        db.col("v3_tickets").insert_one({
            "_id": tid, "id": tid, "kind": kind, "cell": cell,
            "lat": lat, "lon": lon, "category": body.category,
            "traffic_caused": bool(body.traffic_caused),
            "description": body.description or body.note,
            "vehicle_type": body.vehicle_type,
            "vehicle_number": (body.vehicle_number or "").upper().strip(),
            "labels": body.labels or {}, "complaint_id": body.complaint_id,
            "station": station,
            "station_slug": force.slugify(station) if station else None,
            "created_by": sess.get("name") or sess.get("scope"),
            "status": "open", "resolution": None,
            "reason": None, "reason_other": None,
            "created_ts": now, "updated_ts": now,
        })
    return ok({"id": tid, "kind": kind, "cell": cell, "station": station,
               "status": "open"})


class TicketPatch(BaseModel):
    status: str = Field(default="closed", max_length=12)
    resolution: bool | None = None
    reason: str = Field(default="other", max_length=40)
    reason_other: str = Field(default="", max_length=300)


@router.patch("/tickets/{tid}")
def patch_ticket(tid: int, body: TicketPatch,
                 authorization: str | None = Header(default=None)):
    """Resolve a ticket (true/false) with a reason. Applies the reward map to the
    ticket's cell: a transparent live boost/decay/reset + a dispatch-bandit reward.
    Requires a police/government session in scope for the cell."""
    _require_mongo()
    _ensure_init()
    sess = _require_session(authorization)
    coll, doc = _find_ticket(tid)
    if not doc:
        raise HTTPException(404, "Ticket not found.")
    if not _scope_ok(sess, doc.get("station")):
        raise HTTPException(403, "Out of scope for this ticket's station.")

    reason = body.reason if body.reason in V3_REASONS else "other"
    rule = V3_REASONS[reason]
    resolution = body.resolution if body.resolution is not None else rule.get("resolution")
    cell = doc.get("cell")
    now = time.time()
    with _lock:
        db.col(coll).update_one({"id": tid}, {"$set": {
            "status": body.status or "closed",
            "resolution": resolution, "reason": reason,
            "reason_other": body.reason_other or None,
            "resolved_by": sess.get("name") or sess.get("scope"),
            "updated_ts": now,
        }})
        if cell:
            if rule.get("reset"):
                _bump_cell(cell, reset=True, state="cleared")
            elif rule.get("escalate"):
                _bump_cell(cell, escalate=True, state="structural_escalation")
            else:
                _bump_cell(cell, delta=rule.get("delta", 0.0))
            _bandit_reward(cell, rule.get("reward", 0.5))
    hist, boost, opv = _cell_three_numbers(cell) if cell else (0, 0, 0)
    return ok({"id": tid, "status": body.status or "closed",
               "resolution": resolution, "reason": reason,
               "reason_other": body.reason_other or None, "cell": cell,
               "bandit_reward": rule.get("reward"),
               "historical_priority": round(hist, 1),
               "live_adjustment": round(boost, 1),
               "operational_priority": round(opv, 1)})


@router.get("/tickets-meta/reasons")
def v3_ticket_reasons():
    """The fixed resolution dropdown (value -> effect) so the frontend renders the
    exact same enum the backend enforces."""
    return ok({"reasons": [{"value": k, "reward": v.get("reward"),
                            "default_resolution": v.get("resolution"),
                            "cell_effect": ("reset" if v.get("reset") else
                                            "escalate" if v.get("escalate") else
                                            f"{v.get('delta', 0):+.0f} live_adjustment")}
                           for k, v in V3_REASONS.items()],
               "feedback_kinds": FEEDBACK_KINDS})


class FeedbackIn(BaseModel):
    cell: str = Field(max_length=24)
    kind: str = Field(max_length=40)
    ticket_id: int | None = None
    note: str = Field(default="", max_length=300)


@router.post("/officer-feedback")
def post_feedback(body: FeedbackIn, authorization: str | None = Header(default=None)):
    """Officer outcome on a cell (verified_obstruction / needs_towing /
    action_taken / cleared / false_alarm / structural_issue / …). Bumps the cell's
    live_adjustment and rewards the dispatch bandit. Cell-level only."""
    _require_mongo()
    _ensure_init()
    sess = _require_session(authorization)
    if body.kind not in V3_REASONS:
        raise HTTPException(422, f"Unknown feedback kind '{body.kind}'. "
                                 f"Allowed: {FEEDBACK_KINDS}")
    if not _scope_ok(sess, _station_of(body.cell)):
        raise HTTPException(403, "Out of scope for this cell's station.")
    rule = V3_REASONS[body.kind]
    now = time.time()
    with _lock:
        db.col("v3_officer_feedback").insert_one({
            "_id": db.next_id("v3_officer_feedback"),
            "cell": body.cell, "kind": body.kind, "ticket_id": body.ticket_id,
            "note": body.note, "by": sess.get("name") or sess.get("scope"),
            "created_ts": now,
        })
        if rule.get("reset"):
            _bump_cell(body.cell, reset=True, state="cleared")
        elif rule.get("escalate"):
            _bump_cell(body.cell, escalate=True, state="structural_escalation")
        else:
            _bump_cell(body.cell, delta=rule.get("delta", 0.0))
        _bandit_reward(body.cell, rule.get("reward", 0.5))
    hist, boost, opv = _cell_three_numbers(body.cell)
    return ok({"stored": True, "cell": body.cell, "kind": body.kind,
               "bandit_reward": rule.get("reward"),
               "historical_priority": round(hist, 1),
               "live_adjustment": round(boost, 1),
               "operational_priority": round(opv, 1)})


@router.get("/operational/snapshot")
def v3_snapshot():
    """Live operational state, three-number per cell:
    historical_priority (pic_score) · live_adjustment (decayed boost) ·
    operational_priority = clamp(historical + live_adjustment, 0..100)."""
    _ensure_init()
    now = time.time()
    if not db.mongo_enabled():
        return ok({"ts": now, "mongo": False,
                   "counts": {"active_complaints": 0, "open_tickets": 0,
                              "live_cells": 0, "escalations": 0},
                   "cells": [], "complaints": [], "tickets": []})
    states = list(db.col("v3_cell_state").find())
    complaints = list(db.col("v3_complaints").find().sort("created_ts", -1).limit(200))
    tickets = list(db.col("v3_tickets").find().sort("updated_ts", -1).limit(200))

    cells = []
    for s in states:
        cell = s["_id"]
        boost = _decayed_boost(s.get("boost"), s.get("updated_ts"), now)
        if boost <= 0 and not s.get("dispatch_state") and not s.get("escalated"):
            continue
        hist = _hist_priority(cell)
        cells.append({
            "h3_r10": cell, "lat": s.get("lat"), "lon": s.get("lon"),
            "police_station": s.get("police_station"),
            "historical_priority": round(hist, 1),
            "live_adjustment": round(boost, 1),
            "operational_priority": round(_clamp(hist + boost), 1),
            "dispatch_state": s.get("dispatch_state"),
            "escalated": bool(s.get("escalated")),
            "complaints": s.get("complaints", 0),
            "online_e_lambda_live": s.get("online_e_lambda"),
        })
    cells.sort(key=lambda x: -x["operational_priority"])
    return ok({
        "ts": now, "mongo": True,
        "counts": {
            "active_complaints": sum(1 for c in complaints if c.get("status") == "open"),
            "open_tickets": sum(1 for t in tickets if t.get("status") == "open"),
            "live_cells": len(cells),
            "escalations": sum(1 for c in cells if c["escalated"]),
        },
        "cells": cells,
        "complaints": [_ticket_view(c, "complaint") for c in complaints],
        "tickets": [_ticket_view(t, "chalan") for t in tickets],
    })


# --------------------------------------------------------------------------- #
# SELF-LEARNING — lightweight online refresh (NOT the full ml.v3 pipeline)
# --------------------------------------------------------------------------- #
def _online_base():
    """h3 -> (shape, rate) from the offline Gamma-Poisson posterior (stage 09)."""
    on = db.v3_artifact("online_state.json") or {}
    base = {}
    for c in on.get("cells", []) + on.get("emerging_cells", []):
        h = c.get("h3_r10")
        if h and h not in base and c.get("shape") is not None and c.get("rate"):
            base[h] = (float(c["shape"]), float(c["rate"]))
    return base


def _dispatch_rerank(now=None, top=60):
    """Re-rank candidate cells by operational priority + online lift. Candidates =
    dispatch_plan stops ∪ cells with live state. Recompute-only (never edits ML)."""
    now = now or time.time()
    plan = db.v3_artifact("dispatch_plan.json") or {}
    cand = set()
    for r in plan.get("routes", []):
        cand.update(r.get("stops", []))
    states = {s["_id"]: s for s in db.col("v3_cell_state").find()} if db.mongo_enabled() else {}
    cand.update(states.keys())
    rows = []
    for cell in cand:
        st = states.get(cell, {})
        boost = _decayed_boost(st.get("boost"), st.get("updated_ts"), now)
        hist = _hist_priority(cell)
        e_live = st.get("online_e_lambda")
        e_base = st.get("online_base_e_lambda")
        lift = 0.0
        if e_live is not None and e_base:
            lift = _clamp((e_live / e_base - 1.0) * 100.0, -50.0, 50.0)
        score = _clamp(hist + boost + 0.2 * lift)
        rows.append({"cell": cell, "police_station": _station_of(cell),
                     "operational_priority": round(score, 1),
                     "historical_priority": round(hist, 1),
                     "live_adjustment": round(boost, 1),
                     "online_lift_pct": round(lift, 1)})
    rows.sort(key=lambda r: -r["operational_priority"])
    return rows[:top]


def _recompute(reason="cron"):
    """The hourly self-learning step. Folds verified outcomes since `last_calc`
    into each cell's Gamma-Poisson posterior (closed-form: posterior =
    Gamma(shape+Σy, rate+n) — exactly stage 09's update), then recomputes the
    operational priorities + a dispatch rerank. Writes a summary to v3_meta."""
    _require_mongo()
    t0 = time.time()
    meta = db.col("v3_meta").find_one({"_id": "state"}) or {}
    last = meta.get("last_calc") or 0.0

    new_comp = list(db.col("v3_complaints").find({"created_ts": {"$gt": last}}))
    closed_q = {"status": "closed", "updated_ts": {"$gt": last}}
    closed = (list(db.col("v3_complaints").find(closed_q)) +
              list(db.col("v3_tickets").find(closed_q)))

    verified = {}                         # cell -> # of verified-true closures
    for t in closed:
        if t.get("resolution") is True and t.get("cell"):
            verified[t["cell"]] = verified.get(t["cell"], 0) + 1

    # elapsed days extend the Gamma denominator (capped so a long gap can't swamp it)
    n_new = 0.0 if not last else max(0.0, min((t0 - last) / 86400.0, 7.0))
    base = _online_base()
    touched = set(verified) | {c["cell"] for c in new_comp if c.get("cell")}
    updates = []
    for cell in touched:
        y_new = float(verified.get(cell, 0))
        st = db.col("v3_cell_state").find_one({"_id": cell}) or {}
        oy = float(st.get("online_y", 0.0)) + y_new
        on_ = float(st.get("online_n", 0.0)) + n_new
        bs, br = base.get(cell, (ONLINE_PRIOR_SHAPE, ONLINE_PRIOR_RATE))
        post_shape, post_rate = bs + oy, br + on_
        e_lambda = post_shape / post_rate if post_rate > 0 else None
        e_base = bs / br if br > 0 else None
        db.col("v3_cell_state").update_one({"_id": cell}, {"$set": {
            "cell": cell, "online_y": oy, "online_n": on_,
            "online_shape": round(post_shape, 4), "online_rate": round(post_rate, 4),
            "online_e_lambda": round(e_lambda, 4) if e_lambda is not None else None,
            "online_base_e_lambda": round(e_base, 4) if e_base is not None else None,
            "online_updated_ts": t0,
        }}, upsert=True)
        if y_new:
            updates.append({"cell": cell, "y_new": int(y_new),
                            "e_lambda": round(e_lambda, 4) if e_lambda else None,
                            "base_e_lambda": round(e_base, 4) if e_base else None})

    rerank = _dispatch_rerank(now=t0)
    summary = {
        "_id": "state", "last_calc": t0, "prev_calc": last or None, "reason": reason,
        "n_new_complaints": len(new_comp), "n_new_closed": len(closed),
        "n_verified_cells": len(verified), "n_cells_updated": len(touched),
        "elapsed_days_added": round(n_new, 5),
        "online_prior": {"shape": ONLINE_PRIOR_SHAPE, "rate": ONLINE_PRIOR_RATE},
        "updates": updates[:50], "dispatch_rerank": rerank,
        "duration_ms": round((time.time() - t0) * 1000, 1),
        "method": ("Gamma-Poisson conjugate online update (posterior = "
                   "Gamma(shape+Σy_verified, rate+n_days)); recompute-only — "
                   "historical ML scores untouched."),
    }
    db.col("v3_meta").replace_one({"_id": "state"}, summary, upsert=True)
    return summary


def _rebuild_hourly_cache():
    """Bake the deterministic 24-hour heat (historical pic_score × MODELED typical
    congestion per road class) for the top PIC cells and persist it to Mongo as
    heatmap_hourly.json, so /map serves a force-calculated, cached heatmap. The
    live operational boost stays separate (applied at read time). Not measured."""
    idx = _indices()
    cells = {}
    for c in idx["pic_list"]:
        h = c["h3_r10"]
        hist = float(c.get("pic_score") or 0.0)
        rc = c.get("road_class")
        cells[h] = [round(_hour_heat(hist, rc, hr), 1) for hr in range(24)]
    payload = {
        "generated_at": _now_iso(),
        "provenance": _hourly_congestion().get("provenance", "modeled_typical"),
        "n_cells": len(cells),
        "hour_profile": _city_hour_profile(),
        "note": ("24-hour heat = historical PIC propensity × MODELED typical "
                 "congestion per hour; live boost applied at read time. Not measured."),
        "cells": cells,
    }
    if db.mongo_enabled():
        db.save_v3_artifact("heatmap_hourly.json", payload)
    return {"n_cells": len(cells), "provenance": payload["provenance"],
            "generated_at": payload["generated_at"]}


@router.post("/recompute")
def v3_force_recompute(authorization: str | None = Header(default=None)):
    """Government-only FORCE update (the dashboard button). Folds live feedback into
    the per-cell online rates, re-ranks dispatch, and re-bakes the 24-hour heatmap
    cache — so the map immediately reflects the freshly recomputed, DB-cached
    heatmaps. Recompute-only; historical ML scores are never edited."""
    sess = _require_session(authorization)
    if sess.get("role") != "govt":
        raise HTTPException(403, "Government role required to force a recompute.")
    _require_mongo()
    _ensure_init()
    with _lock:
        summary = _recompute("manual")
        heat = _rebuild_hourly_cache()
    return ok({
        "ok": True, "reason": "manual",
        "recompute": {k: summary.get(k) for k in
                      ("last_calc", "prev_calc", "n_new_complaints", "n_new_closed",
                       "n_cells_updated", "n_verified_cells", "duration_ms")},
        "dispatch_rerank_top": summary.get("dispatch_rerank", [])[:10],
        "heatmap": heat,
        "method": summary.get("method"),
    })


def _check_cron(token, authorization):
    secret = (os.environ.get("CLEARLANE_CRON_SECRET") or os.environ.get("CRON_SECRET"))
    if not secret:
        raise HTTPException(503, "CLEARLANE_CRON_SECRET not configured.")
    supplied = token
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or supplied != secret:
        raise HTTPException(401, "Invalid or missing cron token.")


@router.get("/cron/recompute")
@router.post("/cron/recompute")
def cron_recompute(token: str | None = None,
                   authorization: str | None = Header(default=None)):
    """Hourly self-learning webhook. Protected by `?token=` == CLEARLANE_CRON_SECRET
    (or Vercel's automatic `Authorization: Bearer $CRON_SECRET`). Lightweight: it
    folds new verified outcomes into the per-cell online rate and reranks — it does
    NOT run the full ml.v3 pipeline. Wire it in vercel.json `crons`."""
    _check_cron(token, authorization)
    _require_mongo()
    _ensure_init()
    with _lock:
        summary = _recompute("cron")
        heat = _rebuild_hourly_cache()
    return ok({"updated": summary["n_cells_updated"],
               "last_calc": summary["last_calc"], "heatmap": heat,
               "summary": summary})


def _maybe_lazy_recompute():
    """Read-path safety net: if the self-learning state is staler than 24h, run one
    recompute now, guarded by a Mongo lock so two cold readers don't both fire.
    Best-effort — never raises into the read path."""
    if not db.mongo_enabled():
        return
    try:
        meta = db.col("v3_meta").find_one({"_id": "state"})
        last = (meta or {}).get("last_calc") or 0.0
        age_h = (time.time() - last) / 3600.0 if last else 1e9
        if age_h <= LAZY_MAX_AGE_H:
            return
        now = time.time()
        lock = db.col("v3_meta").find_one_and_update(
            {"_id": "lock", "until": {"$lt": now}},
            {"$set": {"until": now + LAZY_LOCK_TTL_S}})
        if not lock:                      # someone else holds it (or no lock doc yet)
            return
        try:
            _recompute("lazy")
        finally:
            db.col("v3_meta").update_one({"_id": "lock"}, {"$set": {"until": 0.0}})
    except Exception:                    # pragma: no cover - read path must not fail
        pass
