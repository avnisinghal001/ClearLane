"""
ClearLane API — serves the precomputed pipeline artifacts.

The ML is precomputed (ml/pipeline). This layer just loads the JSON artifacts
(from MongoDB on Vercel, filesystem in local dev), sanitizes NaN/Inf, gzips large
payloads and bbox-filters heavy layers. The complaint / officer-feedback /
copilot routes are clearly-labelled deployment extensions; the core intelligence
is fully deterministic.

Run locally:  uvicorn app.main:app --reload --port 8000   (from backend/)
On Vercel:    exposed through api/index.py as a Python serverless function.
"""
from __future__ import annotations

import datetime
import math
import os
import time

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from . import db

DEMO_MODE = not db.mongo_enabled()


def load(name: str):
    """Load a precomputed artifact: MongoDB first, filesystem fallback."""
    return db.artifact(name)


def _scrub(obj):
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def ok(payload):
    return JSONResponse(content=_scrub(payload))


app = FastAPI(title="ClearLane API", version="1.0",
              description="Bias-corrected parking-enforcement intelligence for Bengaluru.")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# operational layer (additive): the live complaint -> verify -> dispatch -> clear
# loop, persisted in MongoDB. Never modifies historical ML scores.
from . import operational  # noqa: E402
# force-command layer (additive): RBAC auth + station/officer roster management in
# MongoDB + troop-tracking simulation. Also never modifies historical ML scores.
from . import force  # noqa: E402

app.include_router(operational.router)
app.include_router(force.router)


@app.on_event("startup")
def _startup():
    operational.init_db()
    force.init_db()


# --------------------------------------------------------------------------- #
@app.get("/health")
@app.get("/api/health")
def health():
    artifacts = {n: (load(n) is not None) for n in
                 ["map_payload.json", "zones_detail.json", "validation.json",
                  "timing_gap.json", "forecast.json"]}
    return ok({"status": "ok", "mongo": db.mongo_enabled(),
               "source": "mongodb" if db.mongo_enabled() else "filesystem",
               "artifacts": artifacts, "ts": time.time()})


@app.get("/api/map/payload")
def map_payload():
    return ok(load("map_payload.json"))


@app.get("/api/priority/queue")
def priority_queue(station: str | None = None, tier: str | None = None,
                   limit: int = Query(100, le=2000)):
    zones = (load("map_payload.json") or {}).get("zones", [])
    rows = sorted(zones, key=lambda z: z["rank"])
    if station:
        rows = [z for z in rows if (z.get("station") or "").lower() == station.lower()]
    if tier:
        rows = [z for z in rows if z["tier"] == tier.upper()]
    return ok(rows[:limit])


@app.get("/api/flow-impact")
def flow_impact(tier: str | None = None, limit: int = Query(200, le=2000)):
    """Carriageway Impact Index lens — zones ranked by the modeled flow-impact
    proxy (obstruction pressure × static road-context multiplier). NOT a
    congestion measurement. Fields ride on map_payload (no separate artifact)."""
    zones = (load("map_payload.json") or {}).get("zones", [])
    rows = sorted(zones, key=lambda z: z.get("flow_impact_rank") or 10**9)
    if tier:
        rows = [z for z in rows if z["tier"] == tier.upper()]
    return ok(rows[:limit])


@app.get("/api/zone/{zone_id}")
def zone_detail(zone_id: str):
    details = load("zones_detail.json") or {}
    z = details.get(zone_id)
    return ok(z) if z else JSONResponse({"error": "not found"}, status_code=404)


@app.get("/api/timing-gap")
def timing_gap():
    return ok({"timing": load("timing_gap.json"),
               "blind_spots": [z for z in (load("map_payload.json") or {}).get("zones", [])
                               if z.get("evening_blind_spot")]})


@app.get("/api/coverage-curve")
def coverage_curve():
    return ok(load("coverage_curve.json"))


@app.get("/api/emerging")
def emerging():
    return ok(load("emerging.json"))


@app.get("/api/forecast")
def forecast():
    return ok(load("forecast.json"))


@app.get("/api/typology")
def typology():
    return ok(load("typology.json"))


@app.get("/api/stations")
def stations():
    return ok(load("stations.json"))


@app.get("/api/validation")
def validation():
    return ok({"validation": load("validation.json"),
               "offender_stat": load("offender_stat.json")})


@app.get("/api/evidence-points")
def evidence_points(bbox: str | None = Query(None, description="lonW,latS,lonE,latN")):
    pts = load("evidence_points.json") or []
    if bbox:
        try:
            w, s, e, n = (float(x) for x in bbox.split(","))
            pts = [p for p in pts if w <= p["lon"] <= e and s <= p["lat"] <= n]
        except ValueError:
            pass
    return ok(pts)


@app.get("/api/search")
def search(q: str = Query(..., min_length=1)):
    idx = load("search_index.json") or []
    ql = q.lower()
    hits = [r for r in idx if ql in (r.get("label") or "").lower()
            or ql in (r.get("station") or "").lower()
            or ql in (r.get("junction") or "").lower()
            or ql in r["id"].lower()]
    return ok(hits[:25])


@app.get("/api/briefings")
def briefings():
    return ok(load("briefings.json"))


@app.get("/api/offenders")
def offenders():
    """Repeat-vehicle tracing: most-ticketed anonymized vehicles + time-wise logs.
    Vehicle-level only (stable anonymized IDs) — never officer-level."""
    return ok(load("offenders.json"))


@app.get("/api/daily")
def daily():
    """Per-zone / station / city daily ticket counts for the global Time Lens and
    officer-demand estimator. Recorded enforcement activity by day, not traffic."""
    return ok(load("daily.json"))


@app.get("/api/replay-frames")
def replay_frames():
    return ok(load("replay_frames.json"))


# --------------------------------------------------------------------------- #
# Multi-model dispatch layer (M4 reranker served live).
# --------------------------------------------------------------------------- #
_W_LIVE = 0.30          # weight of the live traffic-stress proxy in the served score
_DEDUP_M = 300          # same-station corridor dedup radius (metres)
_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
_DISPATCH_NOTE = ("dispatch_priority = base modeled risk (0.7) + live travel-time "
                  "stress proxy (0.3). 'pressure' is MODELED from historical tickets, "
                  "NOT a live congestion measurement. assoc_score is a Mappls ETA "
                  "delta proxy for present stress.")


def _dispatch_score(z):
    """Precomputed M4 dispatch_priority (0-100); fall back to historical priority
    for an older artifact that predates the reranker."""
    v = z.get("dispatch_priority")
    return float(v) if v is not None else float(z.get("priority", 0) or 0)


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _evening_target_iso():
    """Next 18:30 IST — the evening enforcement-planning window (informational)."""
    now = datetime.datetime.now(_IST)
    tgt = now.replace(hour=18, minute=30, second=0, microsecond=0)
    if now.hour >= 19:
        tgt += datetime.timedelta(days=1)
    return tgt.isoformat()


def _dispatch_tier(score):
    if score >= 82: return "P1"
    if score >= 68: return "P2"
    if score >= 55: return "P3"
    return "P4"


def _reason_codes(z, live_stress, eta_min, enriched):
    """Honest, instance-level reason strings. Pressure is MODELED from historical
    tickets — never a live congestion measurement."""
    out = []
    if (z.get("pressure") or 0) >= 60:
        out.append("high modeled obstruction pressure")
    if (z.get("forecast_score") or 0) >= 60:
        out.append("forecast pressure rising next month")
    if (z.get("under_observed") or 0) >= 55:
        out.append("likely under-observed (blind-spot candidate)")
    if z.get("evening_blind_spot"):
        out.append("evening coverage gap vs assumed peak")
    if enriched and live_stress > 0.05:
        out.append(f"elevated live travel delay now (+{round(live_stress * 100)}%)")
    if eta_min is not None and eta_min <= 8:
        out.append(f"~{eta_min} min from station")
    return out[:5] or ["top modeled enforcement priority"]


def _reason_detail(z, base, live_stress, enriched):
    d = [{"code": "MODELED_RISK", "label": "modeled obstruction risk",
          "value": round(_dispatch_score(z), 1),
          "contribution": round(base * (1 - _W_LIVE) * 100, 1)}]
    if enriched:
        d.append({"code": "LIVE_DELAY", "label": "live travel-time delay proxy",
                  "value": round(live_stress * 100, 1),
                  "contribution": round(live_stress * _W_LIVE * 100, 1)})
    return d


def _dedup(rows, radius_m):
    """Greedy same-station corridor clustering: keep the top-ranked representative,
    attach nearby same-station zones as supporting evidence (avoids two units sent
    to effectively the same corridor)."""
    from . import mappls
    kept, clusters = [], []
    for r in rows:                       # rows arrive best-first
        merged = False
        for k in kept:
            if (k["station"] == r["station"] and r.get("lat") is not None
                    and k.get("lat") is not None
                    and mappls.haversine_km(k["lat"], k["lon"], r["lat"], r["lon"]) * 1000 <= radius_m):
                k.setdefault("supporting_zones", []).append(r["id"])
                merged = True
                break
        if not merged:
            kept.append(r)
    for k in kept:
        if k.get("supporting_zones"):
            clusters.append({"representative": k["id"], "supporting": k["supporting_zones"]})
    return kept, clusters


def _assemble(station=None, tier=None, limit=60, enrich=40, do_live=True):
    """Build the dispatch queue honestly:
    - uniform live enrichment across the candidate set (no bias for *being* live);
    - de-saturated score = base·(1-W) + live_stress·W;
    - every record gets a backed ETA (mappls_live or haversine_estimate);
    - same-station corridor dedup; sequential ranks; base vs dispatch tier."""
    from . import mappls
    zones = list((load("map_payload.json") or {}).get("zones", []))
    if station:
        zones = [z for z in zones if (z.get("station") or "").lower() == station.lower()]
    if tier:
        zones = [z for z in zones if (z.get("tier") or "") == tier.upper()]
    zones.sort(key=lambda z: -_dispatch_score(z))

    mappls_on = mappls.available()
    live_on = bool(do_live) and mappls_on
    st_ctr = {s["station"]: (s["lat"], s["lon"])
              for s in (load("stations.json") or []) if s.get("lat") is not None}
    enrich = min(enrich, limit)
    counts = {"req": 0, "ok": 0}

    def make(z, allow_live):
        base = _dispatch_score(z) / 100.0
        ctr = st_ctr.get(z.get("station"))
        live_stress, eta_min, eta_source, assoc, enriched = 0.0, None, "unavailable", None, False
        if allow_live and live_on and ctr and z.get("lat") is not None:
            counts["req"] += 1
            dr = mappls.delay_ratio(ctr[0], ctr[1], z["lat"], z["lon"])
            sec = mappls.reach_seconds(ctr[0], ctr[1], z["lat"], z["lon"], traffic=True)
            if dr is not None:
                counts["ok"] += 1
                live_stress = max(0.0, min(1.0, dr))
                assoc = round(dr * 100, 1)
                enriched = True
            if sec is not None:
                eta_min, eta_source = round(sec / 60.0, 1), "mappls_live"
        if eta_min is None and ctr and z.get("lat") is not None:   # backed fallback
            km = mappls.haversine_km(ctr[0], ctr[1], z["lat"], z["lon"])
            eta_min, eta_source = round(km / 20.0 * 60.0, 1), "haversine_estimate"
        score = base * (1 - _W_LIVE) + live_stress * _W_LIVE
        uo = z.get("under_observed")
        return {
            "id": z["id"], "name": z.get("name"), "station": z.get("station"),
            "lat": z.get("lat"), "lon": z.get("lon"),
            "base_priority": z.get("priority"), "base_tier": z.get("tier"),
            "tier": z.get("tier"),                       # back-compat (base/historical)
            "pressure": z.get("pressure"), "forecast_score": z.get("forecast_score"),
            "dispatch_priority_raw": round(score, 4),
            "dispatch_priority": round(score * 100, 1),
            "dispatch_tier": _dispatch_tier(score * 100),
            "under_observed": uo, "under_observed_score": uo,
            "under_observed_candidate": bool((uo or 0) >= 55),
            "blind_spot_ml": bool(z.get("blind_spot_ml", False)),
            "evening_blind_spot": bool(z.get("evening_blind_spot", False)),
            "assoc_score": assoc, "eta_min": eta_min, "eta_source": eta_source,
            "live_enriched": enriched,
            "reason_codes": _reason_codes(z, live_stress, eta_min, enriched),
            "reasons": _reason_detail(z, base, live_stress, enriched),
        }

    candidates = [make(z, True) for z in zones[:enrich]]
    planned = [make(z, False) for z in zones[enrich:limit]]
    candidates.sort(key=lambda r: -r["dispatch_priority_raw"])
    live_queue, clusters = _dedup(candidates, _DEDUP_M)
    for i, r in enumerate(live_queue, 1):
        r["dispatch_rank"] = i
    for i, r in enumerate(planned, 1):
        r["dispatch_rank"] = i

    cov = round(100.0 * counts["ok"] / counts["req"], 1) if counts["req"] else 0.0
    return {
        "generated_at": _now_iso(), "horizon": "deploy_now",
        "traffic_mode": "live" if live_on else "model_only",
        "evening_target_at": _evening_target_iso(),
        "mappls_enabled": mappls_on, "live": live_on,
        "mappls_requested_count": counts["req"], "mappls_success_count": counts["ok"],
        "live_coverage_pct": cov, "note": _DISPATCH_NOTE,
        "count": len(live_queue), "queue": live_queue,
        "planned_count": len(planned), "planned": planned, "clusters": clusters,
    }


def _filter_rank(items, station, tier, limit):
    out = list(items)
    if station:
        out = [z for z in out if (z.get("station") or "").lower() == station.lower()]
    if tier:
        out = [z for z in out if tier.upper() in
               ((z.get("dispatch_tier") or ""), (z.get("base_tier") or ""))]
    out = out[:limit]
    for i, r in enumerate(out, 1):
        r = dict(r); r["dispatch_rank"] = i; out[i - 1] = r
    return out


@app.get("/api/dispatch/queue")
def dispatch_queue(station: str | None = None, tier: str | None = None,
                   live: bool = False, limit: int = Query(60, le=500)):
    """Serves the latest live-rerank snapshot (kept fresh by the recalc cron) so
    the console is fast and consistent; falls back to a model-only compute when no
    snapshot exists. `?live=1` forces a fresh Mappls recompute."""
    snap = load("dispatch_rerank.json")
    if snap and snap.get("queue") and not live:
        q = _filter_rank(snap["queue"], station, tier, limit)
        meta = {k: snap.get(k) for k in
                ("generated_at", "horizon", "traffic_mode", "evening_target_at",
                 "mappls_enabled", "live", "live_coverage_pct",
                 "mappls_requested_count", "mappls_success_count", "note")}
        return ok({**meta, "from_snapshot": True, "last_recalc": snap.get("generated_at"),
                   "auto_interval_min": 5, "count": len(q), "queue": q})
    res = _assemble(station, tier, limit, enrich=min(limit, 40), do_live=live)
    res["from_snapshot"] = False
    res["last_recalc"] = (load("dispatch_rerank.json") or {}).get("generated_at")
    res["auto_interval_min"] = 5
    return ok(res)


@app.get("/api/dispatch/recalc")
@app.post("/api/dispatch/recalc")
def dispatch_recalc(limit: int = Query(80, le=500), enrich: int = Query(40, le=120)):
    """Force a live rerank NOW: enrich the top `enrich` candidates UNIFORMLY with
    current Mappls ETA deltas, re-blend + re-rank + dedup, persist the snapshot to
    Mongo, and return it. Hit by the 5-min cron and the console's 'Force
    recalculate' button. Recompute-only — never edits the historical ML scores."""
    res = _assemble(None, None, limit, enrich=enrich, do_live=True)
    try:
        from . import db
        if db.mongo_enabled():
            db.save_artifact("dispatch_rerank.json", res)
            res["persisted"] = True
        else:
            res["persisted"] = False
    except Exception as e:                       # pragma: no cover
        res["persisted"] = False
        res["persist_error"] = type(e).__name__
    return ok(res)


_BANDIT_REWARD = {              # officer-feedback kind -> bandit reward in [0,1]
    "action_taken": 1.0, "cleared": 1.0, "needs_towing": 0.9, "verified": 0.7,
    "structural_issue": 0.5, "no_obstruction": 0.0, "no_obstruction_found": 0.0,
    "false_alarm": 0.0,
}


@app.get("/api/dispatch/next")
def dispatch_next(station: str | None = None, n: int = Query(5, le=25),
                  pool: int = Query(20, le=200)):
    """Contextual-bandit pick of the next zones to deploy to (M5). Balances
    exploiting known hotspots with exploring high-context, under-observed zones so
    the loop discovers blind spots instead of only re-confirming patrol bias."""
    from . import bandit
    zones = list((load("map_payload.json") or {}).get("zones", []))
    if station:
        zones = [z for z in zones if (z.get("station") or "").lower() == station.lower()]
    zones.sort(key=lambda z: -_dispatch_score(z))
    chosen = bandit.rank(zones[:pool], n=n)
    slim = [{"id": z["id"], "name": z.get("name"), "station": z.get("station"),
             "tier": z.get("tier"), "lat": z.get("lat"), "lon": z.get("lon"),
             "dispatch_priority": round(_dispatch_score(z), 1),
             "under_observed": z.get("under_observed"),
             "reason_codes": z.get("reason_codes", []),
             "bandit_score": z.get("bandit_score"), "exploit": z.get("exploit"),
             "explore_bonus": z.get("explore_bonus")} for z in chosen]
    return ok({"algo": bandit.algo(), "n": len(slim), "selected": slim,
               "note": "Explore/exploit re-ordering only; historical ML scores are untouched."})


@app.post("/api/dispatch/reward")
def dispatch_reward(payload: dict):
    """Online update for the dispatch bandit from an outcome. `kind` is an
    officer-feedback label (action_taken / cleared / false_alarm / ...) or pass an
    explicit `reward` in [0,1]."""
    from . import bandit
    zid = (payload or {}).get("zone_id")
    if not zid:
        return JSONResponse({"error": "zone_id required"}, status_code=400)
    z = next((x for x in (load("map_payload.json") or {}).get("zones", [])
              if x["id"] == zid), None)
    if not z:
        return JSONResponse({"error": "unknown zone_id"}, status_code=404)
    r = payload.get("reward")
    if r is None:
        r = _BANDIT_REWARD.get((payload.get("kind") or "").lower(), 0.5)
    bandit.reward(z, float(r))
    return ok({"ok": True, "zone_id": zid, "reward": float(r), "algo": bandit.algo()})


@app.post("/api/dispatch/route")
def dispatch_route(payload: dict):
    """Order a set of zones into a deployment run. With ?live (and Mappls
    configured) it nearest-neighbour-orders the stops by live drive time from the
    station; otherwise it keeps dispatch-priority order. A route-optimization proxy
    for multi-stop patrols."""
    from . import mappls
    ids = (payload or {}).get("ids") or []
    station = (payload or {}).get("station")
    live = bool((payload or {}).get("live"))
    zmap = {z["id"]: z for z in (load("map_payload.json") or {}).get("zones", [])}
    stops = [zmap[i] for i in ids if i in zmap]
    if not stops:
        return JSONResponse({"error": "no known ids"}, status_code=400)
    start = None
    if station:
        s = next((s for s in (load("stations.json") or [])
                  if s.get("station") == station and s.get("lat") is not None), None)
        if s:
            start = (s["lat"], s["lon"])
    if start is None:
        start = (stops[0]["lat"], stops[0]["lon"])

    ordered, live_on = stops, False
    if live and mappls.available():
        pts = [(z["lat"], z["lon"]) for z in stops]
        order = mappls.nn_order(start, pts, traffic=True)
        if order:
            ordered, live_on = [stops[i] for i in order], True
    route = [{"id": z["id"], "name": z.get("name"), "station": z.get("station"),
              "lat": z.get("lat"), "lon": z.get("lon"),
              "dispatch_priority": round(_dispatch_score(z), 1)} for z in ordered]
    return ok({"live": live_on, "start": {"lat": start[0], "lon": start[1]},
               "stops": len(route), "route": route})


@app.get("/api/zone/{zone_id}/why")
def zone_why(zone_id: str):
    """Reason codes + the model breakdown behind a zone's dispatch priority."""
    d = (load("zones_detail.json") or {}).get(zone_id)
    if not d:
        return JSONResponse({"error": "not found"}, status_code=404)
    fc = load("forecaster_metrics.json") or {}
    shap = fc.get("shap_importance") or {}
    top_drivers = list(shap.items())[:5]
    disp = d.get("dispatch") or {}
    reasons = disp.get("reason_codes") or []
    if not reasons:                       # synthesize from flags for older artifacts
        if d.get("chronic"):
            reasons.append("chronic hotspot")
        if d.get("evening_blind_spot"):
            reasons.append("evening enforcement gap")
        if (d.get("forecast") or {}).get("rising"):
            reasons.append("forecast pressure rising next month")
    return ok({
        "id": zone_id, "name": d.get("name"), "tier": d.get("tier"),
        "dispatch": disp, "reason_codes": reasons,
        "forecast": d.get("forecast"), "blind_spot": d.get("blind_spot"),
        "flow_impact": d.get("flow_impact"), "scores": d.get("scores"),
        "explanation": d.get("explanation"),
        "model_drivers": [{"feature": k, "importance": v} for k, v in top_drivers],
        "model": {"forecaster": fc.get("model"), "objective": fc.get("objective")},
    })


# --------------------------------------------------------------------------- #
# Deployment extensions (labelled) — not part of the core data claims.
# The complaint / feedback / dispatch loop now lives in operational.py (SQLite).
# --------------------------------------------------------------------------- #
@app.post("/api/copilot")
def copilot(payload: dict):
    """Optional LLM copilot (deployment extension). Falls back to the
    deterministic station briefing when no LLM is configured."""
    q = (payload or {}).get("query", "")
    station = (payload or {}).get("station")
    briefs = load("briefings.json") or {}
    if station and station in briefs:
        base = briefs[station]
    else:
        base = ("Ask about a station's deployment, e.g. 'worst evening blind "
                "spots in Shivajinagar'. (Core analytics are deterministic; the "
                "LLM copilot is an optional deployment extension.)")
    if os.environ.get("CLEARLANE_LLM") == "1":
        try:                                       # pragma: no cover
            import anthropic
            client = anthropic.Anthropic()
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=300,
                messages=[{"role": "user", "content":
                           f"You are a Bengaluru Traffic Police deployment "
                           f"copilot. Using ONLY this context, answer briefly:\n"
                           f"Context: {base}\nQuestion: {q}"}])
            return ok({"answer": msg.content[0].text.strip(), "source": "llm",
                       "_extension": True})
        except Exception as e:
            return ok({"answer": base, "source": f"fallback ({type(e).__name__})",
                       "_extension": True})
    return ok({"answer": base, "source": "deterministic", "_extension": True})
