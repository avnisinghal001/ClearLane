# AGENTS.md — ClearLane AI (root)

> Guidance for AI coding agents (and humans) working in this repo. Read this first,
> then the scoped `AGENTS.md` for the layer you're touching:
> `api/clearlane/` (the API), `ml/` (v1 pipeline), `ml.v3/` (v3 pipeline),
> `frontend/` (deployed JSX app), `frontend.v3/` (TS role-based successor).
>
> **This repo has two coexisting generations — know which one you're in:**
>
> | | Generation v1 (DEPLOYED) | Generation v3 (newer) |
> |---|---|---|
> | ML | `ml/pipeline/` (8 stages, zone-based) | `ml.v3/` (12 stages, H3 cell-based) |
> | Artifacts | `data/processed/*.json` | `data/processed/v3/*` |
> | API | `api/clearlane/main.py` (+ `operational.py`, `force.py`) | `api/clearlane/v3.py` |
> | Frontend | `frontend/` (React 18 + JSX) | `frontend.v3/` (React 18 + **TS** + shadcn) |
> | Demo bundle | `frontend/public/demo/` | `frontend.v3/public/demo-v3/` |
>
> `vercel.json` currently builds **`frontend/`** and serves the whole FastAPI app
> (all routers, including `/api/v3`) through **`api/index.py`**. So the v3 API is
> live, but the deployed UI is still the v1 `frontend/`. Don't assume `frontend.v3`
> is wired into production unless `vercel.json` says so.

## What this project is

**ClearLane AI** — bias-corrected parking-enforcement intelligence for Bengaluru.
Built for **Gridlock Hackathon 2.0, Theme 1 (PS1)**: "Poor visibility on
parking-induced congestion." Submission deadline **21 Jun 2026**.

The product is a command center for the Bengaluru Traffic Police that turns five
months of parking-violation tickets into a ranked, validated deployment plan —
*while being honest that the data is enforcement-shaped, not congestion-measured.*

## The single most important thing: the honesty contract

This entire project lives or dies on intellectual honesty. **Never violate these
rules in code, comments, UI copy, docs, or commit messages:**

1. **We never claim to measure congestion.** The dataset has ZERO flow/speed/
   delay/congestion signal — every row is a parking ticket an officer wrote.
2. The "evening blind spot" is an enforcement-**coverage** gap versus the city's
   *assumed* congestion peaks — it is NOT measured evening congestion. Congestion
   windows (morning 8–11, evening 17–21 IST) are stated **assumptions** from
   domain knowledge.
3. Ticket times track **officer shifts**, not traffic. Enforcement peaks ~10am;
   only ~0.16% of tickets fall in the 5–9pm window.
4. A naive ticket-count hotspot map just reproduces where police already patrol.
   Our value is **correcting** for that bias (exposure = distinct officers ×
   active days), not counting tickets.
5. We **never** profile, rank, or score individual officers. All exposure
   analysis is aggregated to the zone level only.
6. The forecaster predicts **future obstruction pressure** (a real observed
   quantity on held-out months) — never congestion.
7. Operational/live features **never** modify historical ML scores. See the
   three-number separation below.

If a change would imply we measure congestion, or would rank officers, it is wrong.

## Verified dataset ground truth (never contradict)

All of these are checked against the raw file and codified in `ml/pipeline/config.py`.

- Raw file: `data/raw/jan to may police violation_anonymized791b166 (1).csv` =
  **298,450 rows**. (Gitignored — too big. A 500-row sample lives at
  `data/raw/sample_500.csv`.)
- Real time window: **9 Nov 2023 → 8 Apr 2024**. The filename "jan to may" is a
  vendor mislabel — do not trust it.
- `description`, `closed_datetime`, `action_taken_timestamp` are **100% empty** —
  never engineer features from them.
- Drop `rejected` + `duplicate` validation_status and non-parking violations.
- Timestamps are stored UTC (+00); all user-facing times are **IST** (+5:30).
- Bengaluru bbox: lat 12.80–13.29, lon 77.44–77.77 (0 missing coords).

## Architecture (precompute → serve → render, ×2 generations)

```
v1:  ml/pipeline/  ──writes──>  data/processed/*.json|*.parquet
                                      │
                                      ├──> api/clearlane/main.py  (FastAPI serves artifacts)
                                      │         │
                                      │         └──> frontend/  (React JSX dashboard)
                                      │
                                      └──> frontend/public/demo/  (offline fallback bundle)

v3:  ml.v3/  ──writes──>  data/processed/v3/*.json|*.parquet
                                      │
                                      ├──> api/clearlane/v3.py  (FastAPI /api/v3 cell APIs + H3 loop)
                                      │         │
                                      │         └──> frontend.v3/  (React TS, 3 role apps)
                                      │
                                      └──> frontend.v3/public/demo-v3/  (offline fallback bundle)

Deploy (vercel.json):  api/index.py  →  imports the WHOLE FastAPI app (v1 + v3 routers)
                       frontend/      →  static Vite build at the web root
                       cron hourly    →  GET /api/v3/cron/recompute
```

- **ML is precomputed and deterministic.** The API does not run models; it loads,
  sanitizes, and serves the JSON/parquet artifacts a pipeline produced. (Exceptions:
  the live Mappls dispatch *rerank* and the bandit/online-rate updates — explicitly
  labelled, additive, and never modify historical ML scores.)
- Each pipeline copies a curated set of artifacts into its frontend's demo bundle
  so the UI renders **even with no backend**.
- Each frontend tries the live API, then transparently falls back to the demo
  bundle (badge flips to "DEMO (offline)").
- **State lives in MongoDB**, not on disk — Vercel's filesystem is read-only. The
  API resolves artifacts MongoDB-first, filesystem-fallback (see `api/clearlane/db.py`).

## The three-number separation (operational layer)

Live/operational features add a closed loop (complaint → verify → dispatch →
clear) but must keep three numbers strictly separate per zone:

- `historical_priority` — immutable ML output from `map_payload.json`.
- `live_adjustment` — transparent rule-based boost/cooldown (decays over time).
- `operational_priority` — `historical + live_adjustment`, clamped 0–100.

API source of truth: `api/clearlane/operational.py` (v1 zones) and
`api/clearlane/v3.py` (v3 H3 cells) — both in MongoDB. Offline mirrors:
`frontend/src/lib/localOps.js` and `frontend.v3/src/lib/localStore.ts` (same rules,
in-memory).

## Repo map

| Path | What |
|------|------|
| `ml/pipeline/` | **v1** 8-stage zone pipeline + `config.py` + `run_all.py`. See `ml/AGENTS.md`. |
| `ml.v3/` | **v3** 12-stage H3 cell pipeline + Mappls cache layer. See `ml.v3/AGENTS.md`. |
| `api/clearlane/` | the **canonical** FastAPI app (deployed via `api/index.py`). See `api/clearlane/AGENTS.md`. |
| `api/index.py` | Vercel `@vercel/python` entry — exposes `clearlane.main:app`. |
| `frontend/` | **deployed** React + Vite + react-leaflet JSX command center. See `frontend/AGENTS.md`. |
| `frontend.v3/` | React + **TS** + shadcn role-based app (citizen/police/govt). See `frontend.v3/AGENTS.md`. |
| `backend/` | **legacy stub** — only a `Dockerfile`/`requirements.txt`. The app moved to `api/clearlane/`. |
| `data/raw/` | raw CSV (gitignored) + `sample_500.csv`. |
| `data/processed/` | v1 artifacts; `data/processed/v3/` holds v3 artifacts. |
| `*/public/demo*/` | bundled artifacts for offline rendering. |
| `outputs/reports/` | judge-facing text reports; `outputs/reports/v3/` for v3. |
| `docs/` | `METHODOLOGY.md`, `PRODUCT_SCOPE.md`, `ML_ARCHITECTURE.md`, `ML_ARCHITECTURE.v3.md`, `CURRENT_STATE_AUDIT.md`. |
| `scripts/migrate_to_mongo.py` | upload artifacts + seed rosters into MongoDB. |
| `ml-v2/` | **unrelated experiment** (Astram/CatBoost routing API) — not part of the ClearLane data flow. |

## Run it

```bash
# 0. one venv at the repo root for everything Python
python -m venv .venv && source .venv/bin/activate   # .\.venv\Scripts\Activate.ps1 on Windows

# 1a. v1 ML pipeline (regenerates data/processed/*; ~11s; prints self-check table)
pip install -r requirements-ml.txt
cd ml/pipeline && python run_all.py && cd ../..

# 1b. v3 ML pipeline (regenerates data/processed/v3/*; ~75s on full data)
pip install -r ml.v3/requirements.txt
python ml.v3/run_all.py

# 2. MongoDB (state + artifacts live here — Vercel has no writable disk)
export MONGODB_URI="mongodb+srv://..."    # Atlas or local mongo
python scripts/migrate_to_mongo.py        # upload artifacts + seed rosters

# 3. API (the same app Vercel runs; serves v1 + v3 routers)
pip install -r api/requirements.txt
uvicorn clearlane.main:app --reload --port 8000 --app-dir api

# 4a. v1 frontend (VITE_API_BASE empty; Vite proxies /api -> :8000)
cd frontend && npm install && cp .env.example .env && npm run dev      # :5173
# 4b. v3 frontend
cd frontend.v3 && npm install && cp .env.example .env && npm run dev   # :5173

# Deploy: one repo -> one Vercel project (api/index.py + frontend/). See DEPLOY.md.
```

> `uvicorn app.main:app` (the old path) no longer exists — the app is
> `clearlane.main:app` under `api/`. `docker-compose.yml` and `backend/Dockerfile`
> predate the move; treat `api/index.py` as the source of truth for how it runs.

## Working norms for agents

- **`config.py` is the single source of truth.** Every weight, threshold, window,
  and verified fact lives there so the sensitivity analysis can perturb it and a
  judge can audit it in one file. Never hard-code a "magic" constant in a stage.
- After any pipeline change, run `python run_all.py` — it exits non-zero if any
  headline metric drifts >15% from the §2 targets. Treat a flag as a real
  regression to explain, not to silence.
- If you change an artifact's shape, update the **whole chain** for that generation:
  the pipeline emitter (v1 `08_payload.py` / v3 stage), the API route
  (`api/clearlane/main.py` or `v3.py`), the frontend reader (`api.js` / `api.ts`),
  and re-bundle the demo. Don't change a v1 artifact and expect v3 to follow (or
  vice-versa) — they are separate pipelines with separate consumers.
- Match the surrounding code's terse, comment-light-but-pointed style. The
  docstrings in each stage/module state the honesty guardrail and the self-check
  target — keep that pattern.
- Confirm which generation a request targets before editing. If unclear, the
  **deployed** path (v1 + `frontend/`) is the safer default to assume.
- Don't commit or push unless asked.
