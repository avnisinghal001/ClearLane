# ClearLane Phase 3 — Commands to run yourself

Run these from the repo root: `/Users/avnisinghal001/Documents/ClearLane/ClearLane`.
Live traffic steps need a Mappls key; the offline steps (A–E, replay, tests) do not.

---

## 0. One-time setup

```bash
source .venv/bin/activate
pip install -r requirements-phase3.txt        # httpx, python-dotenv, tenacity, polyline

# Add your Mappls static REST key/access token (live modes only). Never commit .env.
cp .env.example .env        # if you don't already have a .env
# then edit .env and set:   MAPPLS_REST_KEY=<your key>
# (optional OAuth: MAPPLS_CLIENT_ID / MAPPLS_CLIENT_SECRET / MAPPLS_ACCESS_TOKEN)
#
# Phase 3 sends MAPPLS_REST_KEY as the `access_token` query parameter to:
#   https://route.mappls.com/route/...
#   https://search.mappls.com/search/...
```

---

## A. Tests (no API key, no credits)

```bash
python -m pytest tests/phase1 tests/phase2 -q     # expect: 57 passed
python -m pytest tests/phase3 -q                   # expect: 108 passed
python -m pytest tests/phase1 tests/phase2 tests/phase3 -q   # expect: 165 passed
```

## B. Lineage only (no Mappls calls)

```bash
python scripts/run_phase3.py --mode lineage-only
python scripts/verify_phase3.py
```

## C. Regenerate candidate selection (no live calls)

```bash
python scripts/run_phase3.py --mode select-candidates
# Confirm (read from generated data, not hardcoded):
#   Whitefield 161 · eligible 47 · eligible TESTED 40 · excluded 1 · primary 20 · reserve 10
```

## D. Replay (no API key, no credits) — exercises the full live path offline

```bash
python scripts/run_phase3.py --mode replay --fixture-dir tests/phase3/fixtures/mappls
python scripts/verify_phase3.py
python scripts/inspect_phase3.py
```

## E. Standalone Phase 3 dashboard (new frontend, no npm)

```bash
python scripts/build_phase3_dashboard.py          # stage latest outputs into frontend.phase3/data
cd frontend.phase3 && python -m http.server 4399
# open http://localhost:4399    (then: cd ..)
```

---

## LIVE steps (require MAPPLS_REST_KEY + spend a few credits)

## F. Probe Mappls capabilities

```bash
python scripts/run_phase3.py --mode capability-probe
# Expect AVAILABLE: Route ADV/ETA, Distance Matrix(+ETA), Reverse Geocode, Snap to Road
# Expect ACCESS_DENIED / UNAVAILABLE: Route/Matrix/Predictive Traffic, native tiles
```

## G. Credit-safe segment smoke test (5 cells)

```bash
python scripts/run_phase3.py --mode prepare-segments --limit 5
```

## H. Credit-safe live poll (5 cells)

```bash
python scripts/run_phase3.py --mode poll-once --limit 5
python scripts/inspect_phase3.py

# Proof that the run hit Mappls live APIs:
LATEST=$(ls -td artifacts/phase3/*_phase3 | head -1)
cat "$LATEST/reports/mappls_request_summary.json"
cat "$LATEST/reports/polling_report.json"
```

## I. Full Whitefield segment preparation (only after G passes)

```bash
python scripts/run_phase3.py --mode prepare-segments --limit 20
```

## J. Full Whitefield one-cycle live poll

```bash
python scripts/run_phase3.py --mode poll-once --limit 20
python scripts/verify_phase3.py
python scripts/inspect_phase3.py
python scripts/build_phase3_dashboard.py     # refresh the dashboard with live data
```

For a real live dashboard, confirm:

```bash
LATEST=$(ls -td artifacts/phase3/*_phase3 | head -1)
grep '"data_mode": "LIVE"' "$LATEST/reports/phase3_final_report.json"
grep '"live_mappls_api_calls_attempted"' "$LATEST/reports/mappls_request_summary.json"
```

If `data_mode` is `REPLAY`, the dashboard is showing fixture output, not live Mappls output.

## K. Finite 15-minute live collection (start this yourself when ready)

```bash
python scripts/run_phase3.py --mode collect --interval-minutes 15 --cycles 8 --limit 20
```

This runs 8 cycles, 15 minutes apart, then stops. It is **not** an infinite loop.
Each cycle issues only Distance Matrix ETA calls; reference durations are cached.
```
