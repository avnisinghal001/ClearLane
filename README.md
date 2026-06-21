# ClearLane AI

**Bias-corrected, hour-aware parking-enforcement intelligence for Bengaluru.**
Gridlock Hackathon 2.0 · Theme 1 (PS1) — Poor visibility on parking-induced congestion.

---

## The honest thesis

The only data available is **5 months of parking-violation tickets** (298,450 rows,
9 Nov 2023 → 8 Apr 2024) — **no traffic-flow, speed, congestion or delay signal**.
Every row is a ticket an officer wrote, so a naive hotspot map just reproduces where
police already patrol.

ClearLane understood the data is *enforcement-shaped*, proved the bias, corrected for
it, and extracted operational intelligence on **H3 hexagon cells (~65 m)**:

- **Bias correction** — an exposure-offset Negative-Binomial rate model (Getis-Ord
  Gi\* significance) divides violations by enforcement exposure (distinct officers ×
  active days), surfacing the **true** hotspots incl. under-policed cells.
- **PIC — Parking-Induced Congestion** — bias-corrected intensity × congestion
  severity, ranking where illegal parking actually chokes a carriageway.
- **Hour-aware heatmaps** — historical PIC × a **modeled typical-congestion** curve,
  so the map pulses across all 24 hours (green→yellow→red) while ticket counts stay
  day-of-week. Congestion is modeled, never measured from tickets.
- **Day-ahead forecaster**, **MCLP+VRP dispatch**, a **Gamma-Poisson online loop**
  (citizen + officer feedback → emerging-hotspot drift), a quasi-causal panel, and a
  simulated dispatch policy — all graded by an auditable scorecard.

> We never claim to measure congestion. The ticket timestamp is *upload* time, not
> parking time — so per-hour variation comes only from the modeled congestion layer.
> See `docs/ML_ARCHITECTURE.v3.md` and `ml.v3/AGENTS.md`.

---

> **Deploying to Vercel?** One repo, one project: a static Vite frontend
> (`frontend.v3/`) + a Python serverless API (`api/index.py`) backed by MongoDB.
> See **[DEPLOY.md](DEPLOY.md)**.

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate     # .\.venv\Scripts\Activate.ps1 on Windows

# 1. ML pipeline -> data/processed/v3/*  (~75s; self-check on clean_rows)
pip install -r ml.v3/requirements.txt
python ml.v3/run_all.py
python frontend.v3/scripts/build_demo_v3.py           # refresh the offline demo bundle

# 2. MongoDB (state + artifacts; Vercel has no writable disk)
export MONGODB_URI="mongodb+srv://..."
python scripts/migrate_to_mongo.py

# 3. API
pip install -r api/requirements.txt
uvicorn clearlane.main:app --reload --port 8000 --app-dir api

# 4. Frontend (VITE_API_BASE stays EMPTY; Vite proxies /api -> :8000)
cd frontend.v3 && npm install && cp .env.example .env && npm run dev   # :5173
```

The three role apps (`/citizen`, `/police`, `/govt`) **always render** — if the
backend is down they load the bundled `public/demo-v3/*.json` fallback. RBAC: police
log in per station, government city-wide (offline creds `govt`/`govt`, or
`<station-slug>`/`<station-slug>`).

## What's in here

| Path | What |
|------|------|
| `ml.v3/config.py` | **single source of truth** — every verified fact, weight, threshold, curve |
| `ml.v3/01..13_*.py` | clean → H3 bin → features → NB hotspot → PIC → forecast → dispatch → online → causal → eval → sim → hourly congestion |
| `ml.v3/run_all.py` | one command; prints the self-check |
| `api/clearlane/` | FastAPI serving artifacts + the H3 closed loop + self-learning (NaN-safe, gzip, CORS) |
| `frontend.v3/` | React + TypeScript + shadcn role apps (citizen / police / govt) |
| `docs/ML_ARCHITECTURE.v3.md` | the full v3 design + math |

## Deployment extensions (labelled, optional)

Citizen complaints, officer feedback, the government **Force-update** recompute, and
the hourly cron are additive, MongoDB-backed features — the core analytics are
deterministic and the historical ML scores are **never** edited by the live loop.
