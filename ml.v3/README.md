# ClearLane v3 — ML pipeline (Phase 0 + Phase 1)

The live-first rebuild from [`docs/ML_ARCHITECTURE.v3.md`](../docs/ML_ARCHITECTURE.v3.md).
This commit ships **Phase 0 (scaffold)** + **Phase 1 (offline science core)**: clean
→ H3 bin → features → **exposure-corrected Negative-Binomial hotspot model** with
Getis-Ord Gi\* significance and spatial-block cross-validation.

> It writes to `data/processed/v3/` and `outputs/reports/v3/`, so it never touches
> the original `ml/pipeline` artifacts. `config.py` is the single source of truth.

---

## 0. What Phase 1 produces (and why it's the winning idea)

A naive ticket heatmap shows **where police patrol**, not where illegal parking is
(Lum & Isaac 2016 feedback loop). Phase 1 removes that bias by dividing violations
by **enforcement exposure** and proving which hotspots are statistically real.

| Output (`data/processed/v3/`) | What it is |
|---|---|
| `events_clean.parquet` | cleaned tickets (24-col aware), IST, weights |
| `events_h3.parquet` | each ticket tagged with its H3 r10/r9 cell |
| `cells_r10.parquet` | per-cell count, **exposure**, raw rate, centroid, block |
| `h3_adjacency.json` | 6-neighbour hex graph (spatial-lag + Gi\* weights) |
| `h3_concentration.json` | "top X% of cells = Y% of violations" pitch stat |
| `cell_features.parquet` | every usable column → per-cell feature |
| `hotspots.json` / `hotspots.parquet` | **bias-corrected intensity + Gi\* z/p** per cell |
| `nb_metrics.json` | dispersion, alpha, IRRs, Moran's I, spatial-CV scores |

---

## 1. Setup

```bash
# from repo root (C:\ClearLane)
python -m venv .venv
.\.venv\Scripts\Activate.ps1            # Windows ;  source .venv/bin/activate on mac/linux
pip install -r ml.v3/requirements.txt
```

Optional env vars:

| Variable | Effect | Default |
|---|---|---|
| `CLEARLANE_RAW_CSV` | point at a CSV (e.g. `data/raw/sample_500.csv`) for a fast check | auto-detect largest non-sample CSV in `data/raw/` |
| `MYMAPINDIA_API_KEY` | enable live Mappls POI distances in stage 03 | unset → offline far-sentinel (fully reproducible) |

> Phase 1 runs **fully offline**: with no Mappls key, POI distances become a fixed
> sentinel so every run is byte-reproducible.

---

## 2. Run / "train" commands

Phase 1's "training" is fitting the **Negative-Binomial GLM** in stage 04 (plus the
spatial-CV refits). There is no GPU/epoch training; it's a deterministic statistical
fit (fixed seed `config.CV_RANDOM_STATE = 42`).

```bash
# fast sanity check on the 500-row sample (~10s; numbers are tiny but the code path runs)
$env:CLEARLANE_RAW_CSV = "$PWD\data\raw\sample_500.csv"   # PowerShell
python ml.v3/run_all.py
Remove-Item Env:CLEARLANE_RAW_CSV

# FULL build + train on the real dataset (regenerates every v3 artifact)
python ml.v3/run_all.py

# run / re-train ONE stage (e.g. just refit the model after a config change)
python ml.v3/run_all.py --only 04_exposure_nb

# or run a stage directly
python ml.v3/01_clean.py
python ml.v3/02_h3_bin.py
python ml.v3/03_features.py
python ml.v3/04_exposure_nb.py      # <-- the model fit ("training")
```

`run_all.py` prints a self-check: it **hard-gates `clean_rows` (±15%)** and exits
non-zero on drift; all other Phase-1 numbers (cells, dispersion, alpha, Gi\* count,
Moran's I, spatial-CV) print as INFO.

### Expected output (full dataset, ~75s, exit 0)

```text
clean_rows                     target 248,374  actual 248,374  +0.0%  ok
occupied H3 cells            : 6,483
cells holding 50% of tickets : 168 (2.6% of cells)      <- the pitch stat
model / dispersion / alpha   : NegativeBinomial / 9.22 / 0.1967   <- disp≫1 ⇒ NB, not Poisson
Gi* significant hot cells    : 499
Moran's I on residuals       : -0.0031 (≈0 desired)     <- model captured spatial structure
spatial-CV Spearman          : 0.369
under-policed (hidden) cells : 2,334                    <- cells a count-map would miss
top IRRs: repeat_share=2.61, double_parking_share=1.86, main_road_share=1.76, sev_mean=0.48
```

Reading it: dispersion **9.22 ≫ 1** confirms over-dispersion (so NB, not Poisson);
`repeat_share` **IRR 2.61** ⇒ cells with more repeat offenders have ~2.6× the
violation rate at equal exposure; **168 cells (2.6%)** hold half of all violations.

### Inspect the trained model

```bash
python -c "import json;m=json.load(open('data/processed/v3/nb_metrics.json'));print('family',m['model']['family']);print('dispersion',m['model']['dispersion'],'alpha',m['model']['alpha']);print('top IRRs',m['top_irr']);print('spatial CV',m['spatial_cv']);print('Gi* sig hot',m['significance']['n_sig_hot'],'Moran resid',m['significance']['moran_I_residuals'])"
```

---

## 3. The pipeline, stage by stage

| Stage | File | Does | Key output |
|---|---|---|---|
| 01 | `01_clean.py` | load 24 cols → IST → parse violations → drop rejected/dup + non-parking + out-of-bbox → weights | `events_clean.parquet` |
| 02 | `02_h3_bin.py` | H3 r10/r9 binning; **exposure = distinct(device×date)**; adjacency; concentration | `cells_r10.parquet` |
| 03 | `03_features.py` | every usable column → per-cell feature (mix, repeat, quality, junction, road, spatial-lag, POI) | `cell_features.parquet` |
| 04 | `04_exposure_nb.py` | **NB GLM w/ log-exposure offset** + Gi\* + Moran + spatial-CV | `hotspots.json`, `nb_metrics.json` |

> Note: the plan listed the model before features; we run **features (03) before the
> model (04)** because the model consumes them.

---

## 4. The math (with real example values)

**Exposure (the bias driver).** `exposure_h = # distinct (device_id × date) pairs`.
Two cells with **150 tickets** each: one patrolled by 3 officers over 12 days
(exposure 30 → raw rate 5.0/officer-day), the other over 30 days by many devices
(exposure 90 → raw rate 1.67). Same count, very different **true** intensity.

**The model (rate via offset).**

```text
citations_h ~ NegativeBinomial(mu_h)
log(mu_h)   = beta0 + beta·X_h + log(exposure_h)     # offset coef fixed = 1
```

Predicting with `offset = 0` (exposure = 1) gives the **bias-corrected rate** =
expected violations per unit of enforcement effort — what we rank on (`intensity`,
0–100 percentile).

**Why Negative Binomial.** Poisson assumes variance = mean; ticket counts are
over-dispersed (e.g. mean ≈ 35, variance ≈ 420 → dispersion ≈ 12 ≫ 1). We test the
Pearson dispersion; if > 1.2 we estimate the NB dispersion **alpha** by the
Cameron-Trivedi auxiliary regression `z = ((y-mu)² - y)/mu` on `mu` (slope = alpha,
e.g. ≈ 0.31) and refit as NB(alpha). Effects are reported as **IRR = exp(beta)**:
`beta_junction = 0.41 → IRR 1.51` ⇒ cells at a named junction have ~1.5× the
violation rate, holding exposure constant.

**Significance.** **Getis-Ord Gi\*** gives each cell a z-score + pseudo p; `z>0 &
p<0.05` = a statistically real hot cluster (`sig_hot=True`). **Moran's I** on the
model **residuals** should be ≈ 0 (the model captured the spatial structure — a
leakage check).

**Hidden hotspots.** `rank_divergence = rank_naive − rank_bias`. A large positive
value = a cell far more important than its raw ticket count suggests = **under-
policed** (the thing a count map would miss).

---

## 5. How the data is split (no leakage)

Hotspot detection is **cross-sectional** (one row per cell), so we use
**spatial-block cross-validation** (`config.CV_FOLDS = 5`): every cell is assigned to
a coarse **H3 res-7 block (~1.2 km)** and we K-fold over **blocks** with
`GroupKFold`, so a cell and its neighbours never appear in both train and test.
Held-out metrics: Poisson deviance, Spearman(predicted rate vs observed rate), and
precision@K (top-K predicted hotspots vs top-K observed). The **temporal** split for
the Phase-3 forecaster is pre-declared in `config.py`
(`FORECAST_FEATURE_MONTHS = Nov–Jan → FORECAST_TARGET_MONTHS = Feb–Mar`).

---

## 5b. Mappls cache layer (`ml.v3/cache/`)

Mappls results are cached in **two tiers** behind an **event bus**, so we never
re-pay for a call and live values stay fresh:

| Tier | Kinds | Where | Expiry |
|---|---|---|---|
| **Static** | POI (`nearby`), geocode, snap, place, aerial | **local JSON → then MongoDB** | never (deterministic) |
| **Live** | ETA (`eta`), isochrone, along-route | **MongoDB only** | TTL (`CACHE_LIVE_TTL_S`, 15 min) |

Flow: a cache miss calls Mappls, then `publish`es a `CacheEvent` onto the bus; the
**local-JSON sink** (static only) and the **MongoDB sink** (static→durable coll,
live→TTL coll) buffer it and bulk-write on `flush()`. Lookup order is in-process
memo → local JSON → MongoDB → fetch.

```text
ml.v3/cache/
  bus.py          # EventBus + CacheEvent (fan-out to sinks)
  local_store.py  # static -> data/processed/v3/cache/static/<ns>.json
  mongo_store.py  # static coll (durable) + live coll (TTL index on expireAt)
  cache.py        # get_or_fetch(ns, key, fetch_fn, live, ttl) facade  (singleton `cache`)
```

- Auth/connection from `ml.v3/.env`: `MYMAPINDIA_API_KEY` (or `MAPPLS_CLIENT_ID` +
  `MAPPLS_CLIENT_SECRET` for OAuth REST), `MONGOURI`, `MONGO_DB`. Offline-first:
  no Mongo → static still works via local JSON, live falls back to in-process memo.
- Mirror the local static cache into MongoDB / see stats:

```bash
python ml.v3/sync_cache.py            # push local static JSON -> MongoDB
python ml.v3/sync_cache.py --stats    # counts in memo + Mongo collections
```

> Mongo collections: `mappls_cache_static` (durable) and `mappls_cache_live`
> (TTL — Mongo auto-deletes lapsed docs via an `expireAt` index).

## 6. Next (Phase 2+)

Live ETA collector + PIC, tomorrow's Predictive-ETA curves, MCLP+VRP dispatch,
Gamma-Poisson online learning, and the causal panel — all specified in
[`docs/ML_ARCHITECTURE.v3.md`](../docs/ML_ARCHITECTURE.v3.md) §17–18.
