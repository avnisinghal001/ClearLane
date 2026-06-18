# AGENTS.md — Backend (`backend/`)

> Scope: the FastAPI service. Read the root `AGENTS.md` first — the honesty
> contract and the three-number separation are enforced here too.

## What this layer is (and is NOT)

The backend is a **thin, stateless-ish serving layer over precomputed artifacts**.
It does NOT run any ML. The pipeline (`ml/pipeline/`) already produced every
number; this layer just:

- loads the JSON/parquet artifacts from `data/processed/` (or a demo/override dir),
- sanitizes `NaN`/`Inf` → `null` (`_scrub` / `_safe`) so the JSON is always valid,
- gzips large payloads, sets permissive CORS, and bbox-filters heavy layers,
- runs the **operational closed loop** (the only stateful part) in SQLite.

Keep the core read APIs **fully deterministic**. Anything that calls an external
service or LLM is a clearly-labelled **deployment extension** behind a flag.

## Run

```bash
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

`requirements.txt`: `fastapi`, `uvicorn[standard]`. `anthropic` is optional
(commented) — only needed for the LLM copilot extension.

## Files

- `app/main.py` — the read APIs (serve artifacts) + the copilot extension.
- `app/operational.py` — the live loop (`APIRouter` mounted by `main.py`), SQLite-backed.
- `data/clearlane.db` — SQLite store, created on startup (gitignored runtime state).
- `Dockerfile` — image that bundles only the artifacts (see `CLEARLANE_ARTIFACTS`).

## Artifact resolution (important)

`_art_dir()` in both `main.py` and `operational.py` resolves where artifacts live,
in priority order:

1. `CLEARLANE_ARTIFACTS` env var (used by the Docker image, which bundles only artifacts);
2. if `CLEARLANE_DEMO_MODE=1` → the `frontend/public/demo/` bundle;
3. else `data/processed/` if `map_payload.json` exists there, otherwise the demo bundle.

`load()` caches artifacts in `_CACHE` and last-resort-falls-back to the demo dir.
**If you add an artifact**, make sure it exists in both `data/processed/` and the
demo bundle (the pipeline's `_bundle_demo` handles the latter).

## Read endpoints (`main.py`)

| Route | Serves |
|------|------|
| `GET /health` | status, demo_mode, which artifacts are present |
| `GET /api/map/payload` | lean per-zone records + KPIs (the command map) |
| `GET /api/priority/queue` | sorted by rank; filter by `station`, `tier`, `limit` |
| `GET /api/flow-impact` | Carriageway Impact lens — zones sorted by `flow_impact_rank` (modeled proxy; rides on map_payload) |
| `GET /api/zone/{zone_id}` | full zone detail (404 if missing) |
| `GET /api/timing-gap` | timing histogram + evening blind-spot zones |
| `GET /api/coverage-curve` | cumulative pressure captured by top-K |
| `GET /api/emerging` | emerging zones |
| `GET /api/forecast` | next-month forecast |
| `GET /api/typology` | zone clusters |
| `GET /api/stations` | per-station command summary |
| `GET /api/validation` | sensitivity/backtest + offender stat |
| `GET /api/evidence-points` | raw points, optional `bbox=lonW,latS,lonE,latN` filter |
| `GET /api/search` | substring search over the search index (cap 25) |
| `GET /api/briefings` | per-station deterministic briefings |
| `GET /api/replay-frames` | per-zone monthly counts (historical replay) |
| `GET /api/offenders` | repeat-vehicle traces + time-wise logs (anonymized vehicle IDs only) |

All responses go through `ok()` → `_scrub()`. Use that wrapper for new routes.

## Operational loop (`operational.py`) — the stateful part

The live closed loop: **complaint → verify → dispatch → clear**, persisted in
SQLite. Mounted as an `APIRouter` with prefix `/api`; `main.py` calls
`operational.init_db()` on startup.

**HARD RULE: this layer NEVER modifies historical ML scores.** Every zone carries
three separate numbers (see root AGENTS.md): `historical_priority` (immutable,
from `map_payload.json`), `live_adjustment` (transparent rule-based boost/cooldown
that decays toward 0), and `operational_priority` = clamp(hist + boost, 0..100).

- All live adjustments are defined in **`OP_RULES`** — keep every boost/cooldown
  value there, transparent and auditable. `decay_per_hour` gently relaxes the
  boost; `max_adjustment` (40) caps it.
- Dispatch lifecycle = `DISPATCH_STATES`
  (recommended → assigned → en_route → on_site → action_taken → cleared /
  structural_escalation).
- Complaints are snapped to the **nearest historical zone within 600m**
  (`_nearest_zone`); coords must be inside the Bengaluru bbox (422 otherwise).

### Operational endpoints

| Route | Purpose |
|------|------|
| `GET /api/operational/snapshot` | live zones + complaints + dispatches + counts (decayed) |
| `GET /api/operational/changes?since=` | delta since a timestamp (for polling) |
| `POST /api/complaints` | citizen complaint → nearest zone, bumps boost |
| `POST /api/officer-feedback` | verified/needs_towing/action_taken/cleared/false_alarm/no_obstruction/structural_issue |
| `POST /api/dispatches` | create dispatch |
| `PATCH /api/dispatches/{id}/status` | advance dispatch state (cleared resets boost; escalation flags) |

Feedback `kind` accepts `no_obstruction` and its alias `no_obstruction_found`
(both treated as false_alarm → cooldown). Writes use a `Lock` + a `with _conn()`
transaction. Pydantic input models cap string lengths — keep that.

The frontend mirrors this exact rule set offline in
`frontend/src/lib/localOps.js`. **If you change `OP_RULES`, `BBOX`, the nearest-zone
radius, or the state machine here, change `localOps.js` to match** — otherwise the
offline demo diverges from the live backend.

## Copilot extension (labelled, optional)

`POST /api/copilot` returns the deterministic station briefing by default. Only if
`CLEARLANE_LLM=1` does it call Anthropic (model `claude-haiku-4-5-20251001`), and
even then it falls back to the briefing on any error. Responses carry
`"_extension": true`. This is inference-only, never used in training, and the demo
never depends on it. Keep it clearly labelled as a deployment extension.

## Conventions for new work

- Wrap every response in `ok()` so NaN/Inf scrubbing and JSON encoding stay uniform.
- Don't add ML/compute here — produce it in the pipeline and serve the artifact.
- Don't introduce statefulness outside `operational.py`'s SQLite store.
- Keep CORS/gzip middleware intact; the frontend relies on cross-origin + gzip.
