# ClearLane

**Parking enforcement that clears the lane.** ClearLane turns Bengaluru's raw parking-violation tickets into a **bias-corrected, hour-aware, multi-model deployment plan** — for citizens, police stations, and government.

> **Honesty contract:** we never claim to *measure* congestion from tickets (it's *modeled, not measured*), and we never rank individual officers. Everything is H3 cell- / station-level.

The data is **5 months of parking-violation tickets** (298k rows, Nov 2023 → Apr 2024) — no flow/speed/delay signal. A naive hotspot map just reproduces where police already patrol, so ClearLane **proves that bias, corrects for it**, and extracts operational intelligence on **H3 res-10 cells (~65 m)**.

- **Citizen** — parking hotspots near you + one-tap report of a lane-blocking vehicle.
- **Police** — **Force Dispatch**: where to deploy now, live patrol board, auto-allocation, ticket queue.
- **Government** — city-wide analytics, per-station view, model evidence scorecard.

Pitch deck: [`PRESENTATION.md`](./PRESENTATION.md) · Plain-language explainer: [`SIMPLE.md`](./SIMPLE.md) · Deploy: [`DEPLOY.md`](./DEPLOY.md).

---

## Architecture

### System design (cron + caching)

Offline ML bakes JSON artifacts → FastAPI serves them and merges **live operational** state (tickets, dispatch, Mappls ETA) → React renders. Cron jobs keep it fresh; lazy caches keep it cheap.

```mermaid
flowchart LR
  RAW[("Parking tickets — 298k rows")] --> PIPE
  subgraph PIPE["Offline ML — ml.v3 / run_all.py (stages 01–14)"]
    direction TB
    S1[01 clean → 02 H3 bin → 03 features]
    S2[04 NB + Gi* → 05 PIC]
    S3[06–07 forecaster → 08 dispatch]
    S4[09 online → 10 causal → 11 eval → 12 sim → 13 hourly → 14 cell-detail]
    S1 --> S2 --> S3 --> S4
  end
  PIPE -->|JSON artifacts| ART[("data/processed/v3/*.json  +  Mongo v3_artifacts")]
  ART --> API
  MONGO[("MongoDB — tickets · cell_state · roster · TTL caches")] <--> API
  MAPPLS[["Mappls ETA / Route ADV"]] --> API
  subgraph API["FastAPI — api/clearlane"]
    direction TB
    E1["/api/v3/map  (24h day×hour heatmap cache)"]
    E2["/api/v3/cell/:h3  — historical + live merge"]
    E3["/dispatch/queue · /force/* · /tickets"]
    E4["/police/live-traffic  (15-min lazy TTL cache)"]
  end
  API --> FE["frontend.v3 — React + Vite  (Citizen · Police · Govt)"]
  subgraph CRON["Cron jobs (Vercel schedules)"]
    direction TB
    C1["/cron/recompute — daily<br/>Gamma-Poisson fold → M4 rerank → rebake 24h heatmap"]
    C2["/cron/plan-next-day — next-day deployment plan"]
  end
  CRON --> API
```

**Caching & freshness**
- **24-hour heatmap cache** — the day×hour PIC composite is baked per recompute, so map scrubbing is instant.
- **Live traffic — 15-minute lazy TTL** — Mappls ETA per station is fetched on demand and cached in MongoDB for 15 min (never blindly polled).
- **Recompute cron (daily)** — folds new verified outcomes into the Gamma-Poisson posterior, re-runs the M4 reranker, and re-bakes the heatmap.
- **Offline-first** — every frontend read falls back to a bundled demo bundle (`frontend.v3/public/demo-v3/`), so the app always renders.

### ML architecture (techniques)

Eight models, one transparent number.

```mermaid
flowchart TD
  T[("Parking tickets")] --> C[Clean + H3 res-10 bin]
  C --> F["Features: road class · junction density · spatial lag · enforcement exposure"]
  F --> H["Bias-corrected hotspots<br/>Negative-Binomial + Getis-Ord Gi* + Moran's I"]
  H --> PIC["PIC score (0..100)<br/>violation intensity × congestion severity<br/>percentile-normalized → P1–P4 tiers"]
  PIC --> FCAST["Forecaster<br/>LightGBM Poisson · held-out months"]
  PIC --> ONLINE["Online learning<br/>Gamma-Poisson conjugate update (daily fold)"]
  PIC --> CAUSAL["Quasi-causal panel<br/>enforcement → Δviolations + placebo test"]
  PIC --> SIM["Sim dispatch policy<br/>LinUCB contextual bandit"]
  FCAST --> RR
  ONLINE --> RR
  SIM --> RR
  PIC --> RR
  RR["M4 Reranker — transparent linear blend<br/>forecast · pressure · under-observed · live-delay · reachability"]
  RR --> OUT["Dispatch queue · Force Dispatch · reason codes"]
  PIC --> DETAIL["Place detail (stage 14)<br/>per-cell mix · hourly · weekday×hour · repeat-share"]
  DETAIL --> MODAL["Place-analysis modal (all roles)"]
```

| Technique | Where | What it gives |
|-----------|-------|---------------|
| Negative-Binomial exposure model + Getis-Ord Gi* / Moran's I | `ml.v3/04_exposure_nb.py` | hotspots corrected for patrol exposure (finds under-watched cells) |
| PIC = intensity × congestion severity (percentile-normalized) | `ml.v3/05_pic.py` | immutable 0..100 pressure + P1–P4 tiers |
| LightGBM Poisson forecaster (held-out months) | `ml.v3/06_forecast_daily.py` | next-month propensity (beats baseline deviance) |
| Gamma-Poisson conjugate online update | `ml.v3/09_online.py` | emerging cells, daily learning lift |
| Quasi-causal enforcement panel + placebo | `ml.v3/10_causal.py` | does enforcement actually reduce violations |
| LinUCB contextual bandit (vs greedy/random/oracle) | `ml.v3/12_sim_rl.py` | dispatch-policy uplift |
| M4 linear reranker + reason codes | `api/clearlane/v3.py` (`_rerank_rows`) | one 0..100 dispatch score, per station & city |
| Per-cell aggregation of 248k tickets | `ml.v3/14_cell_detail.py` | place-analysis modal data |

---

## Repo layout

```
api/clearlane/      FastAPI backend (v3 API, force/roster, operational layer, Mappls)
ml.v3/              offline ML pipeline (stages 01–14, run_all.py)
frontend.v3/        React + Vite app (Citizen · Police · Govt)
data/processed/v3/  baked JSON + parquet artifacts the API serves
```

---

## Run it locally

### 1. Backend (FastAPI)

```bash
# from the repo root
python -m venv .venv
. .venv/Scripts/activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                 # fill in values (see table below)
uvicorn clearlane.main:app --reload --port 8000 --app-dir api
```

- **MongoDB is optional for local dev.** Without `MONGODB_URI` the API runs in *filesystem mode* (reads `data/processed/v3/*.json`); the map, place modal, dispatch and analytics all work. **Live tickets, dispatch state, and roster need MongoDB** — set `MONGODB_URI` to enable the operational layer.
- Artifacts in `data/processed/v3/` are already built. To regenerate: `python ml.v3/run_all.py`.

### 2. Frontend (React + Vite)

```bash
cd frontend.v3
npm install
npm run dev                          # http://localhost:5173
```

Vite proxies `/api` → `http://localhost:8000` (override with `VITE_BACKEND_PROXY`). The frontend is **offline-first**: if the backend is down it serves the bundled demo bundle, so it always renders.

Sign-in (demo): **Citizen** is open; **Police** logs in per station (`<station-slug>` / `<station-slug>`). The Government role exists but is hidden from the login for now.

### Environment (`.env` from `.env.example`)

| Var | Required | Purpose |
|-----|----------|---------|
| `MONGODB_URI` | prod / live ops | operational layer (tickets, cell state, roster, TTL caches) |
| `MONGODB_DB` | optional | DB name (default `clearlane`) |
| `MAPPLS_REST_KEY` | optional | live-traffic ETA / routing (else simulated fallback) |
| `USE_MAPPLE` | optional | `false` → CARTO/Leaflet basemap only (no Mappls SDK) |

Frontend (`frontend.v3/.env`, optional): `VITE_API_BASE` (absolute backend URL; empty = same-origin proxy) · `VITE_BACKEND_PROXY` (dev proxy target, default `http://localhost:8000`).

---

## Deploy

Vercel: serverless FastAPI (`api/`) + static frontend (`frontend.v3/`) + MongoDB Atlas, with Vercel Cron driving `/cron/recompute` (daily) and `/cron/plan-next-day`. See [`DEPLOY.md`](./DEPLOY.md).
