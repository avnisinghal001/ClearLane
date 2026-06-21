# AGENTS.md — ML v3 (`ml.v3/`)

> Scope: the **v3 "live-first" rebuild** — H3 cell-centric, 12 stages, with a live
> Mappls cache layer and an online-learning loop. Read the root `AGENTS.md` and the
> honesty contract first. The full narrative + math lives in `ml.v3/README.md` and
> `docs/ML_ARCHITECTURE.v3.md`; this file is the agent working-norms summary.

## Relationship to v1 (`ml/pipeline/`)

v3 is a **separate, additive pipeline.** It writes to `data/processed/v3/` and
`outputs/reports/v3/` and **never touches** the v1 artifacts. The v1 pipeline
(zone-based, deployed) is untouched by v3 work and vice-versa. Pick the generation
the task targets — don't cross the streams.

| | v1 (`ml/pipeline/`) | v3 (`ml.v3/`) |
|---|---|---|
| spatial unit | ~500 m operational superzones | **H3 res-10 hexagons** (res-9 rollups, res-7 CV blocks) |
| hotspot model | percentile pillars | **exposure-offset Negative-Binomial GLM** + Getis-Ord Gi\* |
| time use | hour-of-day slider | **date granularity only** (day-of-week; timestamp is upload time) |
| live | served-side rerank | built-in PIC, predictive-ETA, MCLP+VRP dispatch, online learning |

## Design principles (same spine as v1)

1. **`config.py` is the single source of truth.** Every verified fact, weight,
   threshold, window, hyper-parameter and seed (`CV_RANDOM_STATE = 42`) lives there
   so the spatial-CV / sensitivity code can perturb it and a judge can audit in one
   file. Never hard-code a tunable in a stage.
2. **Deterministic & reproducible.** Fixed seeds; the NB fit is a deterministic
   statistical fit (no GPU/epochs). With no Mappls key, POI distances become a fixed
   far-sentinel so every run is byte-reproducible.
3. **Honesty guardrails in code.** Each stage docstring states its guardrail. The
   data is **tickets, not congestion**; `congestion_source` is always labelled
   `modeled` / `mappls_typical` / `live`. Exposure correction is cell-level only —
   **never per officer**. The timestamp is upload time → used at **date** granularity
   only (day-of-week), never hour-of-day.

## The 12 stages (run order = `run_all.STAGES`)

Each file exposes `run()`. `python ml.v3/run_all.py` runs them in order then prints a
self-check; `--only <stage>` re-runs one.

| Phase | Stage | Does | Key output |
|---|---|---|---|
| 1 | `01_clean` | 24-col load → IST → parse violations → drop rejected/dup + non-parking + out-of-bbox → weights | `events_clean.parquet` |
| 1 | `02_h3_bin` | H3 r10/r9 bin; **exposure = distinct(device×date)**; adjacency; concentration | `cells_r10.parquet`, `h3_*.json` |
| 1 | `03_features` | every usable column → per-cell feature (mix, repeat, quality, junction, road, spatial-lag, POI) | `cell_features.parquet` |
| 1 | `04_exposure_nb` | **NB GLM w/ log-exposure offset** + Gi\* + Moran's I + spatial-block CV | `hotspots.json/.parquet`, `nb_metrics.json` |
| 2 | `05_pic` | Parking-Induced-Congestion proxy (joins live/typical Mappls corridor stress) | `pic.json/.parquet` |
| 3 | `06_forecast_daily` | daily violation-pressure forecaster (validated vs Poisson baseline) | `forecast_daily.json`, `forecaster_daily_metrics.json` |
| 3 | `07_forecast_eta` | tomorrow's predictive-ETA curves (`api_unavailable` w/o Mappls Predictive) | `forecast_eta.json` |
| 4 | `08_dispatch` | MCLP + VRP officer placement / routing | `dispatch_plan.json`, `dispatch_metrics.json` |
| 5 | `09_online` | **Gamma-Poisson** online-rate update / emerging-cell detection | `online_state.*`, `online_metrics.json` |
| 6 | `10_causal` | quasi-causal enforcement panel (exposure→Δviolations(t+1) with placebo) | `causal.json` |
| 7 | `11_evaluate` | capability scorecard → `outputs/reports/v3/EVALUATION.md` | `evaluation.json` |
| 8 | `12_sim_rl` | sim dispatch policy (random/greedy/LinUCB vs oracle) | `sim_rl.json` |

The closed-form Gamma-Poisson update in `09_online` is what the live API
(`api/clearlane/v3.py`) reuses online — keep the math in sync if you change it.

## The model in one paragraph (stage 04)

`citations_h ~ NegBinom(mu_h)`, `log(mu_h) = β0 + β·X_h + log(exposure_h)` (offset
coef fixed at 1). Predicting with `offset=0` gives the **bias-corrected rate** = what
we rank on (`intensity`, 0–100 percentile). NB not Poisson because counts are
over-dispersed (Pearson dispersion ≫ 1; alpha via Cameron-Trivedi aux regression).
Effects reported as **IRR = exp(β)**. **Gi\*** gives per-cell significance
(`sig_hot`); **Moran's I on residuals ≈ 0** is the leakage check.
`rank_divergence = rank_naive − rank_bias` surfaces **under-policed** cells a count
map would miss.

## No-leakage splits

- Hotspots are cross-sectional → **spatial-block CV** (`GroupKFold` over H3 res-7
  blocks, `CV_FOLDS = 5`) so a cell + neighbours never straddle train/test.
- The forecaster's temporal split is pre-declared in `config.py`
  (`FORECAST_FEATURE_MONTHS` → `FORECAST_TARGET_MONTHS`).

## Mappls cache layer (`ml.v3/cache/`)

Two-tier cache behind an event bus so we never re-pay for a call and live values stay
fresh. **Static** (POI/geocode/snap/place) → local JSON then MongoDB, never expires;
**Live** (ETA/isochrone/along-route) → MongoDB only, TTL (`CACHE_LIVE_TTL_S`, 15 min).
Lookup order: in-process memo → local JSON → MongoDB → fetch. Files: `bus.py`,
`local_store.py`, `mongo_store.py`, `cache.py` (singleton `cache`). Sync/inspect:
`python ml.v3/sync_cache.py [--stats]`. Auth/connection from `ml.v3/.env`
(`MYMAPINDIA_API_KEY` or OAuth `MAPPLS_CLIENT_ID`/`SECRET`, `MONGOURI`, `MONGO_DB`).
Offline-first: no Mongo → static still works via local JSON, live falls to memo.

## Self-check (the gate)

`run_all.py` **hard-gates only `clean_rows` (±15%)** and exits non-zero on drift;
every other Phase-1+ number prints as INFO (we don't pre-commit exact targets for
brand-new H3 artifacts). Treat the hard gate as a real regression to explain — don't
loosen it. Expected full run: ~75 s, exit 0, `clean_rows = 248,374`.

## When you change something

- Tunable (weight/threshold/window/hyper-param) → edit **`config.py` only**, re-run,
  confirm the gate passes.
- New/changed artifact field → emit it in the right stage, then wire the full chain:
  `api/clearlane/v3.py` route → `frontend.v3/src/lib/api.ts` reader → demo bundle
  (`python frontend.v3/scripts/build_demo_v3.py`).
- Run end-to-end (`python ml.v3/run_all.py`) before declaring done.

## Dependencies

`pip install -r ml.v3/requirements.txt` (h3, statsmodels, pandas, numpy, scikit-learn,
scipy, pyarrow, …) inside the repo-root `.venv`. Fast dev path: point
`CLEARLANE_RAW_CSV` at `data/raw/sample_500.csv`.
