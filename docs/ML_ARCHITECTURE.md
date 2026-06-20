# ClearLane AI — ML Architecture

> **Problem statement (Gridlock Hackathon 2.0 · PS1):** *Poor visibility on
> parking-induced congestion.* On-street illegal parking and spillover near
> commercial areas, metro stations, and events choke carriageways and
> intersections. Enforcement is patrol-based and reactive, there is no heatmap of
> violations vs. congestion impact, and it is hard to prioritise enforcement
> zones.
>
> **Our reframing (the honesty contract):** the only data we have is **298,450
> parking-enforcement tickets** (Nov 2023 – Apr 2024). It contains **zero**
> flow / speed / delay / congestion measurements — every row is a ticket an
> officer wrote. So we **never claim to measure congestion.** Instead we (1) build
> a bias-corrected map of *obstruction pressure*, (2) model *flow-impact* and
> *future obstruction* as clearly-labelled proxies validated on held-out months,
> and (3) turn that into a ranked, auditable enforcement deployment plan. The
> value is **correcting** the patrol-bias in raw ticket counts, not reproducing
> it.

---

## 1. How the architecture answers the problem statement

| PS1 requirement | What we do | Where |
|---|---|---|
| *Detect illegal-parking hotspots* | Cluster 298k tickets into ~1,543 operational **superzones**, score each on a 3-pillar **Obstruction Pressure** model. | Stages 02–03 |
| *…without just re-mapping where police already patrol* | **Enforcement-exposure bias correction** (exposure = distinct officers × active days) + a **positive-unlabeled blind-spot ranker** that surfaces high-context-risk, *under-ticketed* zones. | Stages 04, 06b |
| *Quantify impact on traffic flow* | **Carriageway Impact Index (CII)** — a modeled flow-impact proxy from junction criticality, road class, and demand proximity. Explicitly **not** measured congestion. | Stage 04 |
| *Targeted, proactive (not reactive) enforcement* | Next-month **obstruction-pressure forecaster** (Poisson GBM) + **dispatch reranker** + live **contextual bandit** that learns from officer outcomes. | Stages 05, 07b, serving |
| *Make it prioritisable / visible* | Tiers P1–P4, coverage curve (top-20 zones ≈ 17.5% of all pressure), per-station command view, reason codes per zone. | Stages 03, 06, 07b |
| *Trustworthy enough to deploy* | Sensitivity analysis (±20%, ~40 configs) + persistence backtest (Spearman ≈ 0.79) + a 13-metric self-check regression gate. | Stage 07 |

---

## 2. Data flow

```
data/raw/*.csv  (298,450 tickets, gitignored)
      │
      ▼  ml/pipeline/  (8 deterministic, precomputed stages)
01_clean → 02_superzones → 03_scores → 04_advanced → 04b_features →
05_forecaster → 06_timing_gap → 06b_blindspot → 07_validation →
07b_reranker → 08_payload
      │
      ├─► data/processed/*.json | *.parquet   (serving artifacts)
      │        │
      │        ├─► backend / api  (FastAPI: loads + serves; never trains)
      │        │        └─► frontend/  (React + Leaflet command center)
      │        └─► frontend/public/demo/  (offline fallback bundle)
      │
      └─► outputs/reports/*.txt  (judge-facing reports)
```

**Key architectural principle:** ML is **precomputed and deterministic** (fixed
seeds everywhere). The backend does not run models — it sanitises and serves the
JSON/parquet the pipeline produced. Re-running reproduces identical numbers.
`config.py` is the single source of truth for every weight, threshold, window,
and verified fact (so the sensitivity analysis can perturb them and a judge can
audit them in one file).

---

## 3. The model stack

| # | Stage | Model / method | Output | Honesty label |
|---|---|---|---|---|
| 03 | `03_scores.py` | 3-pillar percentile-normalised scoring | `priority`, `tier` (P1–P4) | obstruction *pressure*, not congestion |
| 04 | `04_advanced.py` | bias correction + KMeans typology + **CII** | `bias_adjusted`, `flow_impact`, `cluster` | flow-impact is a **modeled proxy** |
| 05 | `05_forecaster.py` | **PoissonRegressor** (GLM baseline) → **LightGBM `objective=poisson`** (main) → **CatBoost Poisson** (challenger) | `forecast_count`, `forecast_score` + SHAP | future **obstruction pressure**, not congestion |
| 06b | `06b_blindspot.py` | **context-residual Positive-Unlabeled** ranker | `under_observed_score`, `blind_spot_ml` | "high-risk under-observed", never "confirmed hotspot" |
| 07b | `07b_reranker.py` | transparent linear blend + **LightGBM LambdaMART** (learn-to-rank challenger) | `dispatch_priority`, `reason_codes` | auditable shipped score |
| live | `api/clearlane/bandit.py` | **LinUCB contextual bandit** (Thompson fallback) | online explore/exploit picks | never edits historical ML scores |

> Graceful degradation: if LightGBM/CatBoost are missing the pipeline falls back
> to `GradientBoostingRegressor` and skips the challenger, so it never hard-fails.

---

## 4. Stage-by-stage detail

### Stage 01 — Cleaning (`01_clean.py`)
Load → convert UTC→IST → parse violation tokens → drop `rejected`/`duplicate`
and non-parking rows → geo-bucket. 298,450 raw → ~248,374 clean parking events.
Every filter step is logged to `cleaning_summary.txt`. The 100%-empty columns
(`description`, `closed_datetime`, `action_taken_timestamp`) are **never** used
as features.

### Stage 02 — Superzones (`02_superzones.py`)
Cluster occupied 100m buckets into ~500m **operational superzones** via a
deterministic grid-merge (snap to a ~0.0045° cell). Deterministic grid-merge is
chosen over DBSCAN because density-chaining would fuse dense commercial corridors
into useless mega-blobs. Result: ~1,543 superzones — the unit every model scores.

### Stage 03 — Scoring (`03_scores.py`) — *the hotspot detector*
Three percentile-normalised pillars (robust to outliers):

```
Pillar A  Obstruction Pressure  = Σ(severity × footprint × confidence)  → percentile
Pillar B  Structural Recurrence = f(active_days, months, regularity)    → percentile
Pillar C  Emergence             = recent-vs-baseline growth (gated)      → percentile

Operational Priority = 0.50·A + 0.30·B + 0.20·C
Tiers: P1 ≥ 80, P2 ≥ 60, P3 ≥ 40, else P4
```

- **Severity** = carriageway-blocking weight (main road 1.00 … footpath 0.25).
- **Footprint** = physical lane occupancy by vehicle class (bus/HTV 1.00 …
  two-wheeler 0.25). Both tables justified in `docs/METHODOLOGY.md`.
- The **coverage curve** ranks by *priority first, then raw pressure* — ranking by
  raw pressure alone overweights one dense KR-Market/Safina cell (~5% of all
  pressure).

### Stage 04 — Advanced intelligence (`04_advanced.py`)
This is where we stop reproducing patrol bias.

- **Enforcement-exposure bias correction:** `bias_adjusted = pressure /
  exposure^0.5`, where `exposure = distinct officers × distinct active days`.
  Aggregated to **zone level only — we never profile or rank officers.**
  `rank_divergence` surfaces *under-recognized* zones (high real pressure, low
  patrol attention).
- **Habitual offenders:** repeat-vehicle share per zone (vehicle-level only;
  numbers are anonymised + stable, no identities).
- **Responsiveness:** monthly trend Nov→Mar — is enforcement actually working?
- **Typology:** KMeans (k chosen by silhouette) + temporal fingerprints.
- **Carriageway Impact Index (CII)** — *the "impact on traffic flow" quantifier*:

  ```
  context_multiplier = clip( lo + (0.30·J + 0.40·R + 0.30·D)·(hi−lo), 0.8, 1.5 )
  flow_impact        = percentile( pressure_raw × context_multiplier )
  ```

  where **J** = junction criticality (share of tickets at named BTP junctions),
  **R** = road class (ring road 1.0 → local 0.3), **D** = demand proximity
  (distance to nearest metro / commercial hub). This estimates *how much an
  illegal park would disrupt movement* from static road context. It is a
  **modeled proxy, NOT measured congestion**, labelled as such in every emitter
  and UI string; it never alters `priority`, tiers, or the self-check targets.

### Stage 04b — Mappls context features (`04b_features.py`)
Offline-first enrichment (results cached to disk → deterministic, works with no
network/key): per-zone POI distances (metro/bus/school/hospital/market/parking)
and station reachability (`reach_km`). Feeds the forecaster, the PU ranker, and
the reranker.

### Stage 05 — Forecaster (`05_forecaster.py`) — *the legitimate ML centerpiece*
- **Features:** each zone's **Nov–Jan** signals (pressure, recurrence, vehicle
  mix, repeat share, exposure, trend, typology, junction) + Mappls context +
  auxiliary offence-code severity.
- **Target:** that zone's **Feb–Mar observed ticket COUNT** — a real, observed
  future count → modeled with a **Poisson** objective.
- **Models:** sklearn `PoissonRegressor` (interpretable GLM baseline) → **LightGBM
  `objective=poisson`** (main) → **CatBoost Poisson** (optional challenger).
- **Holdout:** temporal (Nov–Jan features → Feb–Mar target) + a spatial zone
  split for generalisation.
- **Metrics:** Poisson deviance, R², Spearman, top-K precision.
- **Explainability:** SHAP TreeExplainer (falls back to gain importance) →
  per-zone reason codes.
- Framed strictly as "forecasts which zones stay/become high-obstruction next
  month, validated on held-out months." **Never** congestion prediction.

### Stage 06 — Timing gap (`06_timing_gap.py`) — *the visibility differentiator*
- City hourly histogram (IST): enforcement peaks ~10am; the **assumed** evening
  congestion window (17:00–21:00) receives only **~0.16%** of tickets.
- Per-zone evening share; P1/P2 zones below 2% → `evening_blind_spot` (~516).
- **Coverage curve:** cumulative % of total weighted pressure captured by top-K
  zones (top-20 ≈ 17.5%, top-50 ≈ 36.6%) — the ROI headline.
- Per-station command view + recommended re-timing.

> The "evening blind spot" is an enforcement-**coverage** gap versus *assumed*
> congestion peaks — it is **not** measured evening congestion. The congestion
> windows are stated assumptions from domain knowledge.

### Stage 06b — Blind-spot ranker (`06b_blindspot.py`)
There are no inspected negatives ("checked and clean") in the data, so a plain
classifier would be wrong. We use a **context-residual Positive-Unlabeled** method:

1. Fit a model predicting observed pressure (Pillar A) from **context only**
   (location, junction/road/demand, Mappls POIs, reachability) — deliberately
   excluding enforcement history.
2. `residual = predicted_by_context − observed`. A large **positive** residual =
   "context says hotspot, but few tickets exist here" = high-risk
   **under-observed** zone.

Output: `under_observed_score` (0–100) + `blind_spot_ml`. We report a discovery
lift (how many top under-observed zones are currently low-tier P3/P4 — genuinely
hidden by count-based priority). Labelled "high-risk under-observed", never
"confirmed hotspot".

### Stage 07 — Validation (`07_validation.py`) — *the trust layer*
- **Sensitivity analysis:** ±20% perturbation across ~40 configs on the blend +
  weight tables → ranking stability.
- **Persistence backtest:** train Nov–Jan, test Feb–Apr (Spearman ≈ 0.79).

### Stage 07b — Dispatch reranker (`07b_reranker.py`)
Collapses the separate model outputs into **one operational number per zone**:

```
dispatch_priority = percentile( blend(
    0.30·forecast + 0.25·pressure + 0.15·under_observed
  + 0.20·live_delay + 0.10·reachability ) )
```

`live_delay` is 0 offline and filled at serving from the Mappls ETA-delta proxy;
`reachability` rewards zones a station can reach fast. Each zone gets human
**reason codes** for the "why this zone" panel. The shipped score is the
**transparent linear blend** (auditable + offline); a **LightGBM LambdaMART**
learn-to-rank challenger (grouped by station, NDCG@10) is trained alongside as the
phase-2 path.

### Stage 08 — Payload (`08_payload.py`)
Builds the serving artifacts: `map_payload.json`, `zones_detail.json`,
`evidence_points.json`, `search_index.json`, `emerging.json`, briefings,
replay/hourly/weekday frames, repeat-vehicle logs, and per-zone daily series for
the Time Lens + staffing estimator. Re-bundles the demo fallback.

---

## 5. Live serving layer — contextual bandit

`api/clearlane/bandit.py` implements **LinUCB** (per-arm ridge regression with an
upper-confidence bonus; context = `[bias, forecast, pressure, under_observed,
dispatch_priority]`), with a **Thompson-sampling Beta** fallback when numpy is
unavailable. Dispatch is an explore/exploit problem: keep sending units to known
hotspots (exploit) while occasionally probing high-context-risk, under-observed
zones (explore) so the system **discovers** blind spots instead of re-confirming
existing patrol patterns. It updates online from officer feedback
(`verified_obstruction`/`needs_towing` = 1.0 … `false_alarm` = 0.0) and **never
edits the historical ML scores**.

### The three-number separation (operational layer)
Per zone, three numbers stay strictly separate:

- `historical_priority` — immutable ML output from `map_payload.json`.
- `live_adjustment` — transparent rule-based boost/cooldown (decays over time).
- `operational_priority` = `historical + live_adjustment`, clamped 0–100.

This keeps the live complaint→verify→dispatch→clear loop from ever corrupting the
audited ML layer.

---

## 6. Serving endpoints (what the dashboard consumes)

| Endpoint | Returns |
|---|---|
| `GET /api/dispatch/queue?station=&tier=&live=&limit=` | reranked zones (`dispatch_priority` + `reason_codes`); `live=1` adds a Mappls ETA-delta proxy |
| `GET /api/dispatch/next?station=&n=` | LinUCB contextual-bandit picks (explore/exploit) |
| `POST /api/dispatch/reward` `{zone_id, kind\|reward}` | online bandit update from an outcome |
| `POST /api/dispatch/route` `{ids, station, live}` | nearest-neighbour stop ordering over live drive-times |
| `GET /api/zone/{id}/why` | reason codes + SHAP drivers + the model used |

---

## 7. The regression gate (self-check)

`run_all.py` compares 13 headline metrics against `config.SELF_CHECK_TARGETS` and
**exits non-zero** if any drifts >15%. A flag is treated as a real regression to
investigate, never silenced. Tracked metrics: clean rows (248,374), superzones
(1,543), tier counts (P1 151 / P2 382 / P3 250 / P4 760), chronic (618), evening
blind spots (516), emerging (279), evening peak share (0.16%), coverage top-20
(17.5%) / top-50 (36.6%), and backtest Spearman (0.79).

---

## 8. What makes this defensible for PS1

1. **Honest framing beats overclaiming.** We explicitly separate *measured*
   (ticket counts), *modeled* (CII flow-impact, forecast), and *assumed*
   (congestion windows) quantities — judges can trust every number.
2. **We correct the bias instead of reproducing it.** A naive ticket-count
   heatmap just shows where police already are; exposure correction + the PU
   blind-spot ranker surface where they *aren't but should be*.
3. **Everything is auditable and deterministic.** One config file, fixed seeds,
   a 13-metric self-check, sensitivity analysis, and a backtest.
4. **It closes the loop.** Forecaster → reranker → contextual bandit converts
   visibility into a proactive, self-improving deployment plan — directly
   answering "enable targeted enforcement."
