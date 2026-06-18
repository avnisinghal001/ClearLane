"""
ClearLane API — serves the precomputed pipeline artifacts.

The ML is precomputed (ml/pipeline). This layer just loads the JSON artifacts,
sanitizes NaN/Inf, gzips large payloads and bbox-filters heavy layers. The
complaint / officer-feedback / copilot routes are clearly-labelled deployment
extensions; the core intelligence is fully deterministic.

Run:  uvicorn app.main:app --reload --port 8000   (from backend/)
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

# artifacts: prefer data/processed, fall back to the bundled demo folder
ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
DEMO = ROOT / "frontend" / "public" / "demo"
# explicit override (used by the Docker image, which bundles only the artifacts)
OVERRIDE = os.environ.get("CLEARLANE_ARTIFACTS")
DEMO_MODE = os.environ.get("CLEARLANE_DEMO_MODE", "0") == "1"


def _art_dir() -> Path:
    if OVERRIDE and Path(OVERRIDE).exists():
        return Path(OVERRIDE)
    if DEMO_MODE:
        return DEMO
    return PROC if (PROC / "map_payload.json").exists() else DEMO


_CACHE: dict[str, object] = {}


def load(name: str):
    if name in _CACHE:
        return _CACHE[name]
    path = _art_dir() / name
    if not path.exists():           # last-resort fallback to demo bundle
        path = DEMO / name
    data = json.loads(path.read_text()) if path.exists() else None
    _CACHE[name] = data
    return data


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
# loop, persisted in SQLite. Never modifies historical ML scores.
from . import operational  # noqa: E402

app.include_router(operational.router)


@app.on_event("startup")
def _startup():
    operational.init_db()


# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    artifacts = {n: (_art_dir() / n).exists() for n in
                 ["map_payload.json", "zones_detail.json", "validation.json",
                  "timing_gap.json", "forecast.json"]}
    return ok({"status": "ok", "demo_mode": DEMO_MODE,
               "artifact_dir": str(_art_dir()), "artifacts": artifacts,
               "ts": time.time()})


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


@app.get("/api/replay-frames")
def replay_frames():
    return ok(load("replay_frames.json"))


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
