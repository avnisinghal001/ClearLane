# TraFix v3 — self-learning (online recompute) & the H3 closed loop

This documents the **self-learning** half of the v3 backend (`api/clearlane/v3.py`):
the hourly weight-adjustment cron, the 24-hour lazy fallback, and the per-cell
online learning that they drive. It is an **operational layer** — it NEVER edits
the historical ML scores (`pic_score` from `pic.json`). Read the root `AGENTS.md`
honesty contract first.

## The three numbers (per H3 cell, never per officer)

Every cell carries three **separate** numbers, exactly like the v1 zone loop:

| number | source | mutable? |
|---|---|---|
| `historical_priority` | `pic_score` (pic.json); falls back to bias-corrected `intensity` for non-top cells | **immutable** ML output |
| `live_adjustment` | transparent rule boost/cooldown in `OP_RULES`, decays toward 0 (`1.0/hour`, capped at `40`) | yes (operational) |
| `operational_priority` | `clamp(historical_priority + live_adjustment, 0, 100)` | derived |

`live_adjustment` lives in the Mongo collection **`v3_cell_state`**. The historical
score is read-only and is never written by this layer.

## Persisted models + the manifest (what you can "see")

The heavy models are trained by the **offline** `ml.v3/run_all.py` and written as real
files under **`data/processed/v3/models/`** (NOT trained in the serverless function):

| file | model | trained by | predicts |
|---|---|---|---|
| `nb_model.pkl` | exposure-corrected Negative-Binomial GLM | stage 04 | bias-corrected hotspot **rate** |
| `forecast_daily.lgb` | LightGBM Poisson day-of-week forecaster | stage 06 | future violation **propensity** |
| `reranker_lambdamart.lgb` | LightGBM **LambdaMART challenger** (visibility only) | stage 08 | dispatch ranking |
| `online_state.json` | closed-form **Gamma-Poisson** online model | stage 09 | expected violations/day (λ) |

`models/model_manifest.json` (also copied to `data/processed/v3/model_manifest.json`
so it's served + migrated) lists, per model: **name, type, file, train timestamp,
feature list, headline metrics**. It is exposed at **`GET /api/v3/models`** and
included in `/api/health`.

> The **shipped** dispatch score stays the **transparent M4 config-weight blend**
> (`RERANK_WEIGHTS`, served by `v3.py`). The LambdaMART is a trained *challenger*
> kept for comparison/visibility — it does **not** drive dispatch unless promoted.

### Retrain vs. online update (the split)

- **Heavy retrain** (NB GLM + LightGBM forecaster + LambdaMART) = the **offline
  `run_all.py`** on a workstation/CI. It is NOT run in the serverless function.
- **Online update** = the **closed-form Gamma-Poisson** posterior, folded **every
  cron** (below). This is the genuine live learner — no model is refit, ever.

The crons **load** the persisted `online_state.json` base posterior (`_online_base`)
and the manifest for provenance, then log the version used:

```
[v3.cron] models=manifest@<train-timestamp> online_updated=<N cells>
```

`v3_meta.state.models_version` records the same stamp on each recompute.

## What "online learning" means here

Each cell keeps a **Gamma-Poisson** betting line on its daily violation rate λ — the
same conjugate model as the offline `ml.v3/09_online.py` stage:

```
prior      λ ~ Gamma(s0, r0)                  # s0 = r0 = 1  (weak)
offline    λ ~ Gamma(shape, rate)             # from online_state.json (the 151-day record)
online     λ ~ Gamma(shape + Σy, rate + n)    # fold NEW verified outcomes
estimate   E[λ] = (shape + Σy) / (rate + n)
```

A new verified outcome updates the posterior by **adding two numbers** (`Σy`, `n`) —
no model is refit, ever. `Σy` = count of officer-**verified** ticket resolutions
(`resolution: true`) in that cell since the last recompute; `n` = elapsed days
(capped at 7 so a long gap can't swamp the line). The updated `online_e_lambda`,
`online_shape`, `online_rate` are written back to `v3_cell_state` and surfaced on
`GET /api/v3/online` (as `online_e_lambda_live`) and in the dispatch rerank.

> HONESTY: λ is **expected violations per day** — a real, observed quantity — never
> congestion. All state is cell-level. We fold only **verified** outcomes, so an
> unverified citizen complaint nudges `live_adjustment` but does **not** move the
> learned rate until an officer confirms it.

## The recompute (the hourly "weight adjustment")

`POST /api/v3/cron/recompute?token=<CLEARLANE_CRON_SECRET>` (also accepts `GET`)
runs a **lightweight** online refresh — **NOT** the full `ml.v3` pipeline:

1. **Load** the persisted online model (`online_state.json` base posterior via
   `_online_base`) + the `model_manifest.json` version stamp.
2. Pull new complaints + newly-closed tickets since `v3_meta.last_calc`.
3. Fold each cell's verified outcomes into its Gamma-Poisson posterior (above).
4. Recompute `operational_priority` for every live cell and a **dispatch rerank**
   (candidates = `dispatch_plan` stops ∪ cells with live state, scored by
   `operational_priority + 0.2 × online-lift%`).
5. Write `last_calc` + a summary (incl. `models_version`) to **`v3_meta`**
   (`_id:"state"`), and log `[v3.cron] models=manifest@<ts> online_updated=N`.

The hourly `/api/v3/rerank` and daily `/api/v3/cron/plan-next-day` log the same
`[v3.cron] models=manifest@<ts> …` provenance line.

Response: `{ "updated": <n_cells>, "last_calc": <epoch>, "summary": {...} }`.

It is idempotent and cheap (iterates only cells with activity), so it is safe to
call as often as hourly. Recompute-only — it never edits the historical ML scores.

### Auth on the cron endpoint

The endpoint accepts **either**:

- `?token=` query param equal to env **`CLEARLANE_CRON_SECRET`** (the manual webhook
  form), **or**
- an `Authorization: Bearer <secret>` header equal to `CLEARLANE_CRON_SECRET` **or**
  Vercel's automatic **`CRON_SECRET`** (Vercel attaches this header to cron calls).

If no secret env is set the endpoint returns **503** (fail-closed). A wrong/missing
token returns **401**.

## Lazy 24-hour fallback (read path)

If no cron is wired, the read path self-heals. `GET /api/v3/map` calls
`_maybe_lazy_recompute()`: if `v3_meta.last_calc` is older than **24h** (or missing),
it runs **one** recompute inline, guarded by a Mongo lock (`v3_meta._id:"lock"`,
TTL 180s) so two cold readers don't both fire. It is best-effort and never fails the
map request. This guarantees the online state is at most ~24h stale even with zero
external scheduling.

## Freshness probe

`GET /api/v3/online/status` →
```json
{ "mongo": true, "last_calc": 1782049004.1, "age_hours": 0.001,
  "due": false, "interval_hours": 1.0, "lazy_max_age_hours": 24.0,
  "last_summary": { "reason": "cron", "n_new_complaints": 2, "n_new_closed": 4,
                    "n_cells_updated": 1, "duration_ms": 1582.8 } }
```
`due` is `true` once `age_hours ≥ interval_hours` (hourly).

## Wiring the Vercel Cron (do NOT deploy here — the parent coordinates that)

Already added to `vercel.json`:

```json
"crons": [
  { "path": "/api/v3/cron/recompute", "schedule": "0 * * * *" }
]
```

Vercel hits this path hourly and **automatically** attaches
`Authorization: Bearer $CRON_SECRET`, so the cron authenticates without a secret in
the URL. Set these in the Vercel project **Environment Variables**:

- `CLEARLANE_CRON_SECRET` — used by the `?token=` manual webhook form, and
- (optional) `CRON_SECRET` — Vercel's built-in cron auth header (recommended).

> Note: Vercel **Hobby** runs crons at most once/day; **Pro** is required for the
> hourly `0 * * * *` schedule. The 24h lazy fallback keeps Hobby honest regardless.

### Manual / external trigger (any scheduler)

```bash
curl -X POST "https://<deployment>/api/v3/cron/recompute?token=$CLEARLANE_CRON_SECRET"
# local dev:
curl -X POST "http://127.0.0.1:8000/api/v3/cron/recompute?token=dev-cron-secret"
```

## New Mongo collections

| collection | holds |
|---|---|
| `v3_complaints` | citizen reports (`kind:"complaint"`, open→closed) |
| `v3_tickets` | police chalan/action tickets (`kind:"chalan"\|"action"`) |
| `v3_cell_state` | per-cell `live_adjustment` (boost/decay/state) + online posterior |
| `v3_meta` | `_id:"state"` recompute summary + `last_calc`; `_id:"lock"` lazy lock |
| `v3_officer_feedback` | officer outcome log (cell-level) |

All reads fall back to the filesystem (`data/processed/v3/`); **writes require
MongoDB** and return **503** when it is absent, exactly like `operational.py` /
`force.py`.
