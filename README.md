# ClearLane AI

**Bias-corrected parking-enforcement intelligence for Bengaluru.**
Gridlock Hackathon 2.0 · Theme 1 (PS1) — Poor visibility on parking-induced congestion.

---

## The honest thesis

The only data available is **5 months of parking-violation tickets** (298,450 rows,
9 Nov 2023 → 8 Apr 2024). It contains **no traffic-flow, speed, congestion or delay
signal** — every row is a ticket an officer wrote, so a naive hotspot map just
reproduces where police already patrol.

ClearLane is the team that understood the data is *enforcement-shaped*, proved the
bias, corrected for it, and extracted operational intelligence:

- **Bias correction** — we don't just count tickets; we correct for enforcement
  exposure (distinct officers × active days per zone).
- **The evening blind spot** — enforcement peaks at **10am**; only **0.16%** of
  tickets fall in the 5–9pm congestion window, so the worst chronic zones go
  essentially unenforced exactly when congestion bites.
- **Habitual-offender detection** — **16.7% of tickets come from 4.6% of vehicles**;
  those zones need parking infrastructure, not more tickets.
- **Enforcement responsiveness** — which zones are *responding* to enforcement vs
  *resistant* (need a structural fix).
- **A validated next-month forecaster** — LightGBM, **R² 0.76**, top-20 precision
  **0.85**, on a *real observed* future target (violation pressure — never congestion).

> We never claim to measure congestion. The evening gap is an enforcement-**coverage**
> gap vs the city's known peaks, stated as an assumption. See `docs/METHODOLOGY.md`.

---

> **Deploying to Vercel?** It's a one-repo, one-project deploy (static Vite
> frontend + a Python serverless API backed by MongoDB). See **[DEPLOY.md](DEPLOY.md)**.

## Quick start (local)

### 1. Run the ML pipeline (regenerates every artifact)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-ml.txt          # heavy pipeline stack
cd ml/pipeline && python run_all.py          # ~11s; prints a self-check vs verified targets
```
The raw 110 MB CSV is gitignored (over the 50 MB limit). A 500-row sample is at
`data/raw/sample_500.csv`. Drop the full file in `data/raw/` to regenerate from scratch.

### 2. MongoDB (state + artifacts live here — Vercel has no writable disk)
```bash
pip install -r requirements.txt              # light: fastapi + pymongo + dnspython
export MONGODB_URI="mongodb+srv://..."        # MongoDB Atlas (or local mongo)
python scripts/migrate_to_mongo.py            # upload artifacts + seed rosters
```
Without `MONGODB_URI` the backend still serves reads from the bundled artifacts and
the frontend uses its offline engine — but live writes need Mongo.

### 3. API (the same app Vercel runs — serves v1 + v3 routers)
```bash
pip install -r api/requirements.txt
export MONGODB_URI="mongodb+srv://..."
uvicorn clearlane.main:app --reload --port 8000 --app-dir api
```
> The FastAPI app lives in `api/clearlane/` and deploys via `api/index.py`. The old
> `backend/app/` is gone — `backend/` is now just a Docker stub.

### 4. Frontend
```bash
cd frontend && npm install
cp .env.example .env          # VITE_API_BASE stays EMPTY; Vite proxies /api → :8000
npm run dev                   # http://localhost:5173
```
The dashboard **always renders** — if the backend is down it loads the bundled
`public/demo/*.json` fallback (the badge flips to "DEMO (offline)").

### One command (Docker)
```bash
docker compose up --build     # frontend :5173, backend :8000
```

---

## What's in here

| Path | What |
|------|------|
| `ml/pipeline/config.py` | **single source of truth** — every verified fact, weight, threshold |
| `ml/pipeline/01..08_*.py` | clean → superzones → scores → advanced → forecaster → timing-gap → validation → payload |
| `ml/pipeline/run_all.py` | one command; prints the **self-check table** (flags any metric >15% off) |
| `ml.v3/` | **v3** H3 cell-based pipeline (12 stages) → `data/processed/v3/` |
| `api/clearlane/main.py` | FastAPI serving precomputed artifacts (NaN-safe, gzip, CORS, demo mode); deploys via `api/index.py` |
| `api/clearlane/v3.py` | v3 cell APIs + H3 closed loop (`/api/v3/*`) |
| `frontend/` | **deployed** React + Vite + react-leaflet command center (JSX) |
| `frontend.v3/` | React + TypeScript + shadcn role-based app (not deployed yet) |
| `outputs/reports/` | cleaning summary, validation, forecaster metrics (judge-facing) |
| `docs/METHODOLOGY.md` | honesty statement, weights + rationale, validation, limitations |

## Verified self-check (latest run)

| metric | target | actual |
|---|---|---|
| clean rows | 248,374 | 248,374 |
| superzones | 1,543 | 1,555 |
| P1 / P2 / P3 / P4 | 151/382/250/760 | 153/378/262/762 |
| chronic | 618 | 623 |
| evening blind-spot | 516 | 515 |
| emerging | 279 | 298 |
| evening-peak share | 0.16% | 0.163% |
| coverage top-20 / top-50 | 17.5% / 36.6% | 16.8% / 40.4% |
| persistence Spearman | 0.79 | 0.804 |

All within ±15%. Sensitivity: top-20 overlap 80–100%, Spearman 0.96. Forecaster: R² 0.76,
Spearman 0.78, top-20 precision 0.85.

## Deployment extensions (labelled, optional)
Complaint intake, officer feedback, and the LLM **copilot** are field-rollout
extensions behind flags — the core analytics are fully deterministic and never
depend on a live external call. Enable the copilot with `CLEARLANE_LLM=1` + an
Anthropic key (used at inference only, not training).
