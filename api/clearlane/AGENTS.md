# AGENTS.md — API (`api/clearlane/`)

> Scope: the FastAPI service for ClearLane (v3-only). Read the root `AGENTS.md`
> first — the honesty contract and the three-number separation are enforced here.

## What this layer is (and is NOT)

A **thin serving layer over precomputed `ml.v3` artifacts**. It does NOT run the ML
pipeline. It:

- loads JSON artifacts from **MongoDB** (filesystem fallback in local dev),
- sanitizes `NaN`/`Inf` → `null` (`ok()` / `_safe`),
- gzips large payloads, sets permissive CORS,
- runs the **stateful H3 closed loop** + **self-learning recompute** in MongoDB,
- bakes the **24-hour heatmap cache** (`heatmap_hourly.json`).

**HARD RULE:** live/additive features **never modify historical ML scores.** Each
cell keeps three numbers — `historical_priority` (immutable pic_score),
`live_adjustment` (transparent, decays via `OP_RULES`), `operational_priority =
clamp(historical + live_adjustment, 0..100)`.

## How it runs

- **Vercel:** `api/index.py` exposes `clearlane.main:app`. `@vercel/python` bundles
  the self-contained `clearlane/` package — **no imports from outside `api/`** (so the
  function bundle is complete; data comes from MongoDB, not the filesystem).
- **Local:** `uvicorn clearlane.main:app --reload --port 8000 --app-dir api`.
- Deps: `api/requirements.txt` (fastapi, pydantic, pymongo, dnspython).

`main.py` is slim (health + `/api/config`) and mounts two routers:

```python
app.include_router(force.router)   # /api/auth, /api/govt, /api/force   (RBAC + rosters)
app.include_router(v3.router)      # /api/v3/*                          (H3 cells + loop)
```

## Files

| File | Role |
|---|---|
| `main.py` | app + middleware, `/health`, `/api/config` (Mappls keys), router mounts. |
| `v3.py` | all `/api/v3/*` — reads, the hour-aware map, H3 closed loop, self-learning recompute, hourly heatmap cache, govt force-recompute, cron. |
| `force.py` | RBAC auth (sessions) + station/officer rosters (`station` + `govt` roles), MongoDB. |
| `db.py` | cached MongoClient + `v3_artifact()` / `save_v3_artifact()` (MongoDB→filesystem fallback at `data/processed/v3` → `frontend.v3/public/demo-v3`). |
| `bandit.py` | contextual bandit (explore/exploit) used by the v3 dispatch loop. |

## The hour-aware map (`GET /api/v3/map?when=&hour=`)

Returns each cell's **`intensity` = historical PIC × MODELED typical congestion for
the hour** (`_hour_heat`), plus the immutable `pic_score`, `congestion_hour`, the
three operational numbers, and a city `hour_profile` (24 values). `when` = `now` /
`today` / `tomorrow` (forecast overlays the day-of-week curve). Served from the
DB-cached `heatmap_hourly.json` when present, else composed inline. Congestion is
**modeled, not measured** — keep that in the badge/`source_note`.

## Self-learning + the govt Force-update

- `_recompute()` folds verified outcomes since `last_calc` into each cell's
  Gamma-Poisson posterior (closed-form, mirrors `ml.v3/09_online.py`) and re-ranks
  dispatch. `_rebuild_hourly_cache()` bakes the 24-hour `heatmap_hourly.json`.
- `POST /api/v3/recompute` — **government-only** (bearer session, `role == "govt"`);
  runs `_recompute("manual")` + `_rebuild_hourly_cache()`. This is the dashboard
  **"Force update now"** button.
- `GET|POST /api/v3/cron/recompute` — hourly webhook (Vercel cron), protected by
  `CLEARLANE_CRON_SECRET`; same recompute + cache re-bake.
- A read-path lazy recompute fires if state is >24h stale (Mongo-locked).

## Other v3 routes

Reads: `/api/v3/{hotspots,pic,online,online/status,forecast/daily,forecast/eta,
dispatch/plan,evaluation,causal,sim,stations,tickets,tickets/{id},
tickets-meta/reasons,operational/snapshot}`. Writes (need Mongo, else 503):
`POST /api/v3/{complaints,tickets,officer-feedback}`, `PATCH /api/v3/tickets/{id}`.
Citizen pins snap to the nearest cell within `SNAP_MAX_M` (300 m); `OP_RULES` /
`V3_REASONS` are the transparent rule tables.

## Conventions for new work

- Wrap responses in `ok()`. Don't run ML here — emit it in `ml.v3` and serve the
  artifact (the only live compute is the labelled recompute / bandit / hour cache).
- Keep the package self-contained (no imports outside `api/`); state only in MongoDB.
- Mirror any rule-table change into `frontend.v3/src/lib/localStore.ts`.
- `congestion_source` is `live` / `mappls_typical` / `modeled` — never "measured".
