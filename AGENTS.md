# AGENTS.md — ClearLane AI (root)

> Guidance for AI coding agents (and humans) working in this repo. Read this first,
> then the scoped `AGENTS.md` in `ml/`, `backend/`, and `frontend/`.

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

## Architecture (three layers, one data flow)

```
ml/pipeline/  ──(writes)──>  data/processed/*.json|*.parquet
                                   │
                                   ├──> backend/app/  (FastAPI serves artifacts)
                                   │         │
                                   │         └──> frontend/  (React dashboard)
                                   │
                                   └──> frontend/public/demo/  (offline fallback bundle)
```

- **ML is precomputed and deterministic.** The backend does not run models; it
  loads, sanitizes, and serves the JSON/parquet artifacts the pipeline produced.
- The pipeline copies a curated set of artifacts into
  `frontend/public/demo/` so the dashboard renders **even with no backend**.
- The frontend tries the live API, then transparently falls back to the demo
  bundle (badge flips to "DEMO (offline)").

## The three-number separation (operational layer)

Live/operational features add a closed loop (complaint → verify → dispatch →
clear) but must keep three numbers strictly separate per zone:

- `historical_priority` — immutable ML output from `map_payload.json`.
- `live_adjustment` — transparent rule-based boost/cooldown (decays over time).
- `operational_priority` — `historical + live_adjustment`, clamped 0–100.

Backend source of truth: `backend/app/operational.py` (SQLite). Offline mirror:
`frontend/src/lib/localOps.js` (same rules, in-memory).

## Repo map

| Path | What |
|------|------|
| `ml/pipeline/` | **canonical** 8-stage pipeline + `config.py` + `run_all.py`. See `ml/AGENTS.md`. |
| `ml/legacy_scripts/` | superseded old scripts (wrong framing) — do not use or revive. |
| `data/raw/` | raw CSV (gitignored) + `sample_500.csv`. |
| `data/processed/` | pipeline outputs (parquet + JSON artifacts). |
| `backend/app/` | FastAPI: `main.py` (read APIs) + `operational.py` (live loop). See `backend/AGENTS.md`. |
| `frontend/` | React + Vite + react-leaflet command center. See `frontend/AGENTS.md`. |
| `frontend/public/demo/` | bundled artifacts for offline rendering. |
| `outputs/reports/` | judge-facing text reports (cleaning, validation, forecaster). |
| `docs/` | `METHODOLOGY.md`, `PRODUCT_SCOPE.md`, `CURRENT_STATE_AUDIT.md`. |

## Run it

```bash
# 1. ML pipeline (regenerates every artifact; ~11s; prints self-check table)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd ml/pipeline && python run_all.py

# 2. Backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. Frontend
cd frontend && npm install && cp .env.example .env && npm run dev   # :5173

# One command
docker compose up --build     # frontend :5173, backend :8000
```

## Working norms for agents

- **`config.py` is the single source of truth.** Every weight, threshold, window,
  and verified fact lives there so the sensitivity analysis can perturb it and a
  judge can audit it in one file. Never hard-code a "magic" constant in a stage.
- After any pipeline change, run `python run_all.py` — it exits non-zero if any
  headline metric drifts >15% from the §2 targets. Treat a flag as a real
  regression to explain, not to silence.
- If you change an artifact's shape, update **all three** consumers: the pipeline
  emitter (`08_payload.py`), the backend route, and the frontend reader — plus
  re-bundle the demo (`run_all.py` does this unless `--no-demo`).
- Match the surrounding code's terse, comment-light-but-pointed style. The
  docstrings in each stage state the honesty guardrail and the self-check target —
  keep that pattern.
- Don't commit or push unless asked.
