"""
ClearLane API (v3-only) — serves the precomputed ml.v3 artifacts + the live H3
closed loop. The ML is precomputed (ml.v3/); this layer loads the JSON artifacts
(from MongoDB on Vercel, filesystem in local dev), sanitizes NaN/Inf, gzips large
payloads, and runs the operational + self-learning loops in MongoDB. Citizen
complaints / officer feedback / the government force-recompute are labelled,
additive deployment features — the core intelligence stays deterministic and the
historical ML scores are never edited.

Run locally:  uvicorn clearlane.main:app --reload --port 8000 --app-dir api
On Vercel:    exposed through api/index.py as a Python serverless function.
"""
from __future__ import annotations

import math
import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from . import db


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


app = FastAPI(title="ClearLane API", version="3.0",
              description="Bias-corrected, hour-aware parking-enforcement intelligence for Bengaluru (v3).")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# force-command layer (RBAC auth + station/officer rosters) and the v3 cell-centric
# reads + H3 closed loop + self-learning recompute. Both MongoDB-backed; both never
# modify the historical ML scores.
from . import force  # noqa: E402
from . import v3     # noqa: E402

app.include_router(force.router)
app.include_router(force.v3_router)   # /api/v3/force/* (roster, officer CRUD, auto-allocate)
app.include_router(v3.router)


@app.on_event("startup")
def _startup():
    force.init_db()
    v3.init_db()


# --------------------------------------------------------------------------- #
@app.get("/health")
@app.get("/api/health")
def health():
    names = ["pic.json", "hotspots.json", "forecast_daily.json",
             "online_state.json", "dispatch_plan.json", "hourly_congestion.json",
             "map_cells.json", "model_manifest.json"]
    artifacts = {n: (db.v3_artifact(n) is not None) for n in names}
    return ok({"status": "ok", "version": "3.0", "mongo": db.mongo_enabled(),
               "source": "mongodb" if db.mongo_enabled() else "filesystem",
               "artifacts": artifacts, "ts": time.time()})


def _use_mappls_basemap() -> bool:
    """Whether the BROWSER basemap should use MapMyIndia/Mappls (engines 1–2). Set
    `USE_MAPPLE=false` (aliases USE_MAPPLS / USE_MAPMYINDIA) to force the whole app onto
    Avni's CARTO/Leaflet basemap (engine 3) — handy when the MapMyIndia SDK won't render.
    NOTE: this ONLY affects the browser basemap; the police live-traffic layer still
    calls the Mappls REST API (Route ADV/ETA) server-side regardless."""
    v = (os.environ.get("USE_MAPPLE") or os.environ.get("USE_MAPPLS")
         or os.environ.get("USE_MAPMYINDIA") or "true").strip().lower()
    return v not in ("0", "false", "no", "off")


@app.get("/api/config")
def public_config():
    """Public client config: the Mappls Map-SDK keys for the browser (public by
    design — secured via domain whitelist in the Mappls console). Lets the frontend
    fall back to a server-provided key when VITE_MAPMYINDIA_KEY isn't baked into the
    build. `mappls_key` = REST key (engine 1 map_load); `static_key` = SDK key for
    the Mappls Web SDK v3.0 fallback (engine 2). When USE_MAPPLE=false we null the keys
    and flag `use_mappls:false` so the frontend goes straight to the CARTO basemap."""
    use = _use_mappls_basemap()
    key = (os.environ.get("MYMAPINDIA_REST_MAPPLS_API_KEY")
           or os.environ.get("MYMAPINDIA_STATIC_API_KEY")
           or os.environ.get("MYMAPINDIA_API_KEY")) if use else None
    static = (os.environ.get("MYMAPINDIA_STATIC_API_KEY")
              or os.environ.get("MYMAPINDIA_API_KEY")) if use else None
    return ok({"mappls_key": key or None, "static_key": static or None,
               "use_mappls": use})
