# AGENTS.md — ClearLane AI (root)

> Guidance for AI coding agents (and humans). Read this first, then the scoped
> `AGENTS.md` for the layer you touch: `ml.v3/` (pipeline), `api/clearlane/` (API),
> `frontend.v3/` (the role-based app).
>
> **This is a v3-only repo.** The legacy v1 (zone-based `ml/pipeline` + JSX
> `frontend/`) and v2 (`ml-v2/`) generations were removed. Everything is the
> H3-cell-based v3 stack. (A pre-cleanup snapshot lives on the local
> `backup/pre-v1v2-cleanup-*` branch if you ever need the old code.)

## What this project is

**ClearLane AI** — bias-corrected, hour-aware parking-enforcement intelligence for
Bengaluru. Built for **Gridlock Hackathon 2.0, Theme 1 (PS1)**: "Poor visibility on
parking-induced congestion." It turns five months of parking-violation tickets into
a ranked, validated, hour-by-hour deployment plan for the Bengaluru Traffic Police —
*while being honest that the data is enforcement-shaped, not congestion-measured.*

## The single most important thing: the honesty contract

This project lives or dies on intellectual honesty. **Never violate these in code,
comments, UI copy, docs, or commits:**

1. **We never claim to measure congestion.** Every row is a parking ticket an
   officer wrote — zero flow/speed/delay signal.
2. **The ticket timestamp is the UPLOAD time, not the parking time.** So ticket
   COUNTS are only ever used at **day-of-week** granularity — **never hour-of-day.**
3. **Congestion may vary by hour; ticket counts may not.** The hourly heatmap
   modulates a **MODELED typical-congestion** curve (documented commute peaks, or
   Mappls typical-traffic ETA where enabled) — labelled "modeled, not measured."
4. A naive ticket-count map just reproduces where police already patrol. Our value
   is **correcting** for that bias (exposure = distinct officers × active days).
5. We **never** profile, rank, or score individual officers. All aggregation is
   cell- or station-level only.
6. The forecaster predicts **future violation propensity** (a real observed
   quantity on held-out months) — never congestion.
7. Live/operational features **never** modify historical ML scores (three-number
   separation, below).

If a change would imply we measure congestion (especially per-hour), or would rank
officers, it is wrong.

## Verified dataset ground truth (never contradict — codified in `ml.v3/config.py`)

- Raw file = **298,450 rows** (gitignored; 500-row sample at `data/raw/sample_500.csv`).
- True window: **9 Nov 2023 → 8 Apr 2024** (the "jan to may" filename is a vendor mislabel).
- `description`, `closed_datetime`, `action_taken_timestamp` are **100% empty** — never engineer from them.
- Drop `rejected` + `duplicate` validation_status and non-parking violations.
- Timestamps stored UTC (+00); user-facing times are **IST** (+5:30).
- Bengaluru bbox: lat 12.80–13.29, lon 77.44–77.77.

## Architecture (precompute → serve → render)

```
ml.v3/  ──writes──>  data/processed/v3/*.json|*.parquet
                            │
                            ├──> api/clearlane/  (FastAPI: /api/v3 reads + H3 loop + self-learning)
                            │         │
                            │         └──> frontend.v3/  (React TS: citizen / police / govt apps)
                            │
                            └──> frontend.v3/public/demo-v3/  (offline fallback bundle)

Deploy (vercel.json):  api/index.py  →  the FastAPI app (force + v3 routers)
                       frontend.v3/  →  static Vite build at the web root (SPA)
                       cron daily    →  GET /api/v3/cron/recompute  (Hobby plan caps crons at 1/day)
```

> **Live now:** https://clearlane-arisyn.vercel.app (Vercel project `clearlane-arisyn`).
> Deploy with `vercel --prod` (direct CLI upload — there is no GitHub→Vercel
> integration; pushing to GitHub does NOT deploy).

- **ML is precomputed and deterministic.** The API serves artifacts (MongoDB on
  Vercel, filesystem in local dev). The only live compute is the labelled,
  additive self-learning recompute + dispatch rerank — never edits historical scores.
- **State lives in MongoDB** (Vercel's filesystem is read-only). Reads fall back to
  the filesystem / the bundled `demo-v3` so the app always renders.

## The hourly heatmap (the headline feature)

`intensity(cell, hour) = historical PIC propensity × MODELED typical congestion(road_class, hour) × live boost`

- The historical layer is **day-of-week** (honest). Congestion genuinely varies by
  hour, so the map pulses across 24 hours while `pic_score` stays immutable.
- Curve source: `ml.v3/13_hourly_congestion.py` → `hourly_congestion.json` (per road
  class, modeled-typical). Backend `_hour_heat` applies it; the **govt Force-update**
  button (`POST /api/v3/recompute`) + the hourly cron re-bake the 24-hour cache
  (`heatmap_hourly.json`) in MongoDB.
- UI ramp is **green (low) → yellow (medium) → red (high)** for both the heatmap and
  the circles. Live-traffic *tiles* are unavailable on this Mappls account (only the
  typical-traffic ETA product is provisioned) — the hourly overlay is the honest
  congestion view.

## The three-number separation (operational layer)

Per **H3 cell**, kept strictly separate (`api/clearlane/v3.py`, mirrored offline in
`frontend.v3/src/lib/localStore.ts`):

- `historical_priority` — immutable ML output (pic_score).
- `live_adjustment` — transparent rule-based boost/cooldown that decays (`OP_RULES`).
- `operational_priority` — `clamp(historical + live_adjustment, 0..100)`.

## Repo map

| Path | What |
|------|------|
| `ml.v3/` | 13-stage H3 pipeline + `config.py` (SSOT) + Mappls cache. See `ml.v3/AGENTS.md`. |
| `api/clearlane/` | the FastAPI app (deployed via `api/index.py`). See `api/clearlane/AGENTS.md`. |
| `frontend.v3/` | React + TS + shadcn role apps (citizen/police/govt). See `frontend.v3/AGENTS.md`. |
| `data/processed/v3/` | v3 artifacts (parquet + JSON). |
| `frontend.v3/public/demo-v3/` | bundled artifacts for offline rendering. |
| `scripts/migrate_to_mongo.py` | push v3 artifacts + seed rosters into MongoDB. |
| `outputs/reports/v3/`, `docs/` | judge-facing reports + methodology. |

## Run it

```bash
python -m venv .venv && source .venv/bin/activate    # .\.venv\Scripts\Activate.ps1 on Windows

# 1. ML pipeline (regenerates data/processed/v3/*; ~75s; self-check on clean_rows)
pip install -r ml.v3/requirements.txt
python ml.v3/run_all.py
python frontend.v3/scripts/build_demo_v3.py          # refresh the offline demo bundle

# 2. MongoDB (state + artifacts; Vercel has no writable disk)
export MONGODB_URI="mongodb+srv://..."
python scripts/migrate_to_mongo.py

# 3. API (the same app Vercel runs)
pip install -r api/requirements.txt
uvicorn clearlane.main:app --reload --port 8000 --app-dir api

# 4. Frontend (VITE_API_BASE empty; Vite proxies /api -> :8000)
cd frontend.v3 && npm install && cp .env.example .env && npm run dev   # :5173

# Deploy: one repo -> one Vercel project (api/index.py + frontend.v3). See DEPLOY.md.
```

## Working norms for agents

- **`ml.v3/config.py` is the single source of truth** for every weight/threshold/
  window/curve. Never hard-code a tunable in a stage.
- Any new data dependency needs the full chain: `ml.v3` stage emit → demo bundle
  (`build_demo_v3.py`) → `api/clearlane/v3.py` route → `frontend.v3/src/lib/api.ts`
  reader (+ offline compose).
- Mirror any operational rule change between `api/clearlane/v3.py` (`OP_RULES`,
  `V3_REASONS`) and `frontend.v3/src/lib/localStore.ts`.
- Run `python ml.v3/run_all.py` end-to-end after pipeline changes; `npm run build`
  must pass `tsc` after frontend changes.
- Don't commit or push unless asked.
