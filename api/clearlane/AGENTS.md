# AGENTS.md — API (`api/clearlane/`)

> Scope: the **canonical** FastAPI service for ClearLane. Read the root `AGENTS.md`
> first — the honesty contract and the three-number separation are enforced here.
> This package **replaced the old `backend/app/`** (now a stub). Don't reach for
> `backend/` — everything serves from here.

## What this layer is (and is NOT)

A **thin serving layer over precomputed artifacts**. It does NOT run ML models. The
pipelines (`ml/pipeline/` for v1, `ml.v3/` for v3) already produced every number;
this layer:

- loads JSON artifacts from **MongoDB** (filesystem fallback in local dev),
- sanitizes `NaN`/`Inf` → `null` (`_scrub` / `ok()`) so JSON is always valid,
- gzips large payloads, sets permissive CORS, bbox-filters heavy layers,
- runs the **stateful loops** (operational, force command, v3 H3 loop) in MongoDB,
- runs **labelled additive compute**: the live Mappls dispatch *rerank*, the
  contextual bandit, and the v3 Gamma-Poisson online-rate update.

**HARD RULE (every router):** additive/live features **never modify historical ML
scores**. Each zone/cell keeps three separate numbers — `historical_priority`
(immutable), `live_adjustment` (transparent, decays), `operational_priority =
clamp(historical + live_adjustment, 0..100)`.

## How it runs

- **Vercel:** `api/index.py` inserts `api/` on `sys.path` and exposes
  `clearlane.main:app` as the ASGI function. `@vercel/python` bundles the whole
  self-contained `clearlane/` package — **no imports from outside `api/`** (keep it
  that way so the function bundle stays complete with zero config).
- **Local:** `uvicorn clearlane.main:app --reload --port 8000 --app-dir api`.
- Deps: `api/requirements.txt` (kept light — `fastapi`, `pydantic`, `pymongo`,
  `dnspython`). `anthropic` is optional, only for the copilot extension.

`main.py` mounts three routers and runs their `init_db()` on startup *and* lazily on
first request (Vercel doesn't fire ASGI startup events reliably):

```python
app.include_router(operational.router)   # /api/operational, /api/complaints, ...  (v1 zones)
app.include_router(force.router)         # /api/auth, /api/govt, /api/force         (RBAC + rosters)
app.include_router(v3.router)            # /api/v3/*                                (H3 cells)
```

## Files

| File | Role |
|---|---|
| `main.py` | v1 read APIs + the M4 live **dispatch rerank** + M5 **bandit** routes + copilot. |
| `operational.py` | v1 **zone** closed loop (complaint → verify → dispatch → clear), MongoDB. |
| `force.py` | RBAC auth (sessions) + station/officer rosters + troop sim, MongoDB. |
| `v3.py` | v3 **cell-centric** reads over `ml.v3` artifacts + H3 closed loop + self-learning recompute + the hourly cron. |
| `db.py` | cached MongoClient + artifact store. `artifact()` (v1) and `v3_artifact()` (v3), MongoDB→filesystem fallback, `_load_dotenv()` for local dev. |
| `mappls.py` | MapMyIndia distance-matrix / ETA helpers (`reach_seconds`, `delay_ratio`, `nn_order`, `haversine_km`) + `available()` gate. |
| `bandit.py` | contextual bandit (`rank`/`reward`/`algo`) for explore/exploit dispatch picks. |

## Artifact resolution (important)

`db.artifact(name)` (v1) and `db.v3_artifact(name)` (v3) resolve in priority order:

1. MongoDB `artifacts` collection (`{_id: "<name>.json", data: …}`; v3 prefers a
   namespaced `{_id: "v3/<name>.json"}`, falls back to the flat key);
2. filesystem fallback — v1: `data/processed/` → `frontend/public/demo/`; v3:
   `data/processed/v3/` → `frontend.v3/public/demo-v3/` → `frontend/public/demo/v3/`.

Results are cached in `db._artifact_cache`. **If you add an artifact**, re-run
`python scripts/migrate_to_mongo.py` so it lands in MongoDB, and make sure the
pipeline bundled it into the demo dir too. `save_artifact` / `save_v3_artifact`
invalidate the cache entry on write (used by the live rerank + cron).

## v1 read endpoints (`main.py`)

All wrapped in `ok()` → `_scrub()`. Use that wrapper for new routes.

| Route | Serves |
|---|---|
| `GET /health`, `/api/health` | status, mongo on/off, which artifacts are present |
| `GET /api/config` | public Mappls Map-SDK keys for the browser (domain-whitelisted) |
| `GET /api/map/payload` | lean per-zone records + KPIs (the command map) |
| `GET /api/priority/queue` | sorted by rank; filter `station`, `tier`, `limit` |
| `GET /api/flow-impact` | Carriageway Impact lens (modeled proxy; rides on map_payload) |
| `GET /api/zone/{id}` / `/api/zone/{id}/why` | full zone detail (404 if missing) / reason codes + model drivers |
| `GET /api/timing-gap` `/coverage-curve` `/emerging` `/forecast` `/typology` `/stations` `/validation` | the analytics artifacts |
| `GET /api/evidence-points` | raw points; optional `bbox=lonW,latS,lonE,latN` |
| `GET /api/search` `/briefings` `/offenders` `/daily` `/replay-frames` | search / briefings / repeat-vehicle / daily series / replay |

### Live dispatch layer (M4/M5, `main.py`)

| Route | Purpose |
|---|---|
| `GET /api/dispatch/queue` | serves the latest live-rerank snapshot (kept fresh by cron); `?live=1` forces a Mappls recompute |
| `GET/POST /api/dispatch/recalc` | force a live rerank now (uniform Mappls enrichment → re-blend → dedup → persist snapshot). Hit by the 5-min cron + the console button |
| `GET /api/dispatch/next` | contextual-bandit pick of next zones (explore/exploit) |
| `POST /api/dispatch/reward` | online bandit update from an officer-feedback outcome |
| `POST /api/dispatch/route` | order stops into a run (live NN-order by Mappls drive time, else priority order) |

`dispatch_priority = base modeled risk·0.7 + live travel-time stress proxy·0.3`.
`pressure` is **MODELED from historical tickets, NOT a live congestion measurement** —
keep that label (`_DISPATCH_NOTE`) on every emitter. The rerank is recompute-only.

## Operational loop (`operational.py`) — v1 zones, stateful

Complaint → verify → dispatch → clear, persisted in MongoDB. Every live adjustment
lives in **`OP_RULES`** (transparent, auditable); `decay_per_hour` relaxes the boost,
`max_adjustment` (40) caps it. Complaints snap to the nearest historical zone within
**600 m**; coords must sit inside the Bengaluru bbox (422 otherwise). Endpoints:
`GET /api/operational/snapshot|changes`, `POST /api/complaints|officer-feedback|
dispatches`, `PATCH /api/dispatches/{id}/status`.

**The frontend mirrors this rule set offline in `frontend/src/lib/localOps.js`. If
you change `OP_RULES`, `BBOX`, the snap radius, or the state machine, change
`localOps.js` to match** — otherwise the offline demo diverges from live.

## v3 loop (`v3.py`) — H3 cells, stateful + self-learning

Sibling of `operational.py` but the unit is the **H3 res-10 hexagon**, not a zone.
Same three-number separation, same `OP_RULES` values (kept in sync deliberately),
plus a `V3_REASONS` table that maps each resolution to a cell effect **and** a bandit
reward in `[0,1]`. Citizen pins snap to the nearest known cell within `SNAP_MAX_M`
(300 m). The online-rate update reuses the Gamma-Poisson math of `ml.v3/09_online.py`.
Reads work offline (`db.v3_artifact`); writes need Mongo (collections `v3_complaints`,
`v3_tickets`, `v3_cell_state`, `v3_meta`) and degrade to a clear 503 without it.

Routes: `GET /api/v3/{map,hotspots,pic,online,online/status,forecast/daily,
forecast/eta,dispatch/plan,evaluation,causal,sim,stations,tickets,tickets/{id},
tickets-meta/reasons,operational/snapshot}`, `POST /api/v3/{complaints,tickets,
officer-feedback}`, `PATCH /api/v3/tickets/{id}`, and `GET/POST /api/v3/cron/recompute`.

> `congestion_source` is `modeled` / `mappls_typical` / `live` — **never** "measured
> congestion" from ticket data. Predictive ETA stays `api_unavailable` until the
> Mappls Predictive product is enabled.

### The hourly cron (`vercel.json`)

`GET /api/v3/cron/recompute` runs **hourly** (`0 * * * *`). It folds accumulated live
feedback into the online cell state and re-persists the v3 snapshot — recompute-only,
never editing historical ML scores. The v1 dispatch rerank is refreshed separately
via `/api/dispatch/recalc`.

## Force command (`force.py`)

RBAC auth (`/api/auth/login|logout|me` with bearer sessions), govt station management
(`/api/govt/stations`), and per-station rosters (`/api/force/roster`,
`POST/PATCH /api/force/officers`). Roles: `station` and `govt`. All state in MongoDB;
**never** profiles or scores individual officers analytically — rosters are
operational identity only.

## Conventions for new work

- Wrap every response in `ok()` so NaN/Inf scrubbing and JSON encoding stay uniform.
- Don't add ML/compute here — produce it in a pipeline and serve the artifact. The
  only allowed live compute is the labelled Mappls rerank / bandit / online update.
- Don't introduce statefulness outside the MongoDB collections — Vercel's filesystem
  is read-only.
- Keep the package self-contained (no imports outside `api/`) and the CORS/gzip
  middleware intact — both frontends rely on cross-origin + gzip.
- Mirror any rule-table change into the offline frontends (`localOps.js` for v1,
  `localStore.ts` for v3).
