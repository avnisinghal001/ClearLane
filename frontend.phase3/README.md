# ClearLane Phase 3 — Standalone Live Dashboard

A **new, self-contained** frontend for Phase 3. It does **not** touch the existing
`frontend.v3/` app or any backend. No build step, no npm — just static files
(Leaflet via CDN) that read the generated Phase 3 outputs.

## What it shows
- A Whitefield map with monitored **road segments** and **PIC cells** coloured by
  live congestion severity (NORMAL / MODERATE / HIGH / SEVERE), sized by PIC score.
- The current **PIC priority ranking** table (click a row to fly to the cell).
- KPIs (ranked cells, max PIC, mean severity) and the live poll-cycle timestamp.
- A **DATA MODE** badge (LIVE or REPLAY) — replay data is never shown as live.
- An honesty panel: high inspection priority ≠ confirmed parked-car detection.

## Run it
```bash
# 1. Produce Phase 3 outputs (replay needs no API key / credits):
python scripts/run_phase3.py --mode replay
#    …or a real live cycle once segments are prepared:
#    python scripts/run_phase3.py --mode poll-once --limit 20

# 2. Stage the latest outputs into ./data:
python scripts/build_phase3_dashboard.py

# 3. Serve and open:
cd frontend.phase3 && python -m http.server 4399
# open http://localhost:4399
```

`./data/` is populated by `build_phase3_dashboard.py` from `data/processed/`.
It is safe to delete; regenerate any time.
