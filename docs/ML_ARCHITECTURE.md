# TraFix AI — ML Architecture

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

---
---

# Part II — Live-First Capability Addendum (verification + complete build spec)

> **Why this part exists.** Part I (§1–8, above, *unchanged*) describes what is
> **built today**. This part is an honest review answer to a direct challenge:
> *the current system is not yet an evaluated, live solution — it does not yet
> prove live illegal-parking detection, a causal congestion-impact model, a
> complete tomorrow-hourly forecast, or a fully specified dispatch system.* That
> challenge is correct. Below, for **each** missing capability, is (a) a blunt
> verdict, (b) whether it is achievable with **only this dataset + live Mappls
> APIs/SDKs**, and (c) the exact method, math, endpoint, features, evaluation and
> build steps to ship it. Every Mappls endpoint here is grounded in the docs in
> `uploads/` (file names cited inline).
>
> **Format:** 🔧 = what to build / the math / the API · 🟢 = explain-to-a-judge.
> **Verdict keys:** ✅ buildable now · ⚠️ buildable with honest caveats · ❌ not
> honestly possible from this data alone (and what we do instead).
>
> **The honesty contract still binds Part II.** We never claim ticket data
> measures congestion; the only *measured* live congestion signal is Mappls'
> travel-time ratio. We never profile officers. "Causal" is used only where a
> defensible identification strategy exists; elsewhere we say "associational."

---

## 9. Verdict table — does it solve each ask? (read this first)

| # | Capability asked for | Status **today** (Part I) | Achievable on dataset + live Mappls? | Live or historical | Section |
|---|---|---|---|---|---|
| C1 | **Genuine live illegal-parking detection** | ❌ only historical tickets | ⚠️ **live *risk* + live *report/verify* loop yes; live *sensor* detection no** (no camera/live feed in data) | Live (risk + reports) | §13 |
| C2 | **Causal quantification of congestion caused by parking** | ⚠️ static modeled proxy (CII) only | ⚠️ **live associational stress yes; quasi-causal via panel/event-study yes; pure causal no** | Live stress + historical ID | §14 |
| C3 | **Tomorrow's hour-by-hour traffic prediction** | ❌ not present | ✅ **traffic: yes via Mappls Predictive ETA**; ❌ hourly *violation counts* (timestamp artifact) → ✅ day-of-week violation *propensity* instead | Live/predictive | §15 |
| C4 | **Exact police deployment optimization** | ⚠️ greedy rerank + bandit | ✅ **MCLP coverage (isochrone) + VRP route-optimization (exact-ish) + sim-RL** | Live | §16 |
| C5 | **Full online learning across all models** | ⚠️ only the bandit is online | ✅ **Gamma-Poisson rates + drift alarm + online bandit + scheduled GBM refit** | Live | §17 |
| C6 | **Proper evaluation metrics** | ⚠️ forecaster only | ✅ **spatial-block CV, PR-AUC@k, calibration/PIT, NDCG, regret, event-study placebos** | Both | §18 |
| C7 | **Actual trained-model results** | ⚠️ forecaster numbers exist | ✅ **run the stages; fill the results template** | Both | §19 |
| C8 | **Exhaustive Mappls API usage** | ⚠️ 4 of ~15 APIs used | ✅ **full inventory mapped to features** | Live | §11 |
| C9 | **Full feature engineering from all 24 columns** | ⚠️ ~12 columns used | ✅ **every column mapped to a feature or a documented drop** | Both | §12 |

🟢 **One-paragraph honest summary.** Of the nine asks, **seven are buildable now**
(C3's traffic half, plus C4–C9), and **two carry an honest asterisk** (C1 and C2,
each only *partially* possible) that is itself a credibility win: you cannot *detect* illegal parking
live from a 5-month ticket archive, and you cannot prove *causation* from
observational data without a design — so we ship a **live risk + citizen/officer
verify loop** for C1 and a **panel/event-study quasi-causal** estimator for C2,
and we *say so on stage*. Everything else is a straight build on top of Part I.

---

## 10. Two rules that bound every "live" claim

1. **Mappls' coloured traffic overlay is visual-only — but its ETA APIs return
   numbers.** The Web SDK `trafficLayer` (Traffic Visualizer) only paints
   green/orange/red and is *not* machine-readable. The **numeric** live/predictive
   signal comes from the **Distance-Time Matrix** family (§11). So "we read
   congestion from Mappls" = we read **travel-time ratios**, never the colour.
2. **Live ≠ trained-on-live.** Mappls gives *live inputs*; our *models* are still
   trained on the historical ticket archive (offline, deterministic) and on a
   **rolling store of Mappls observations we collect ourselves** (§20). "Live
   results" therefore means: scores recomputed every cycle from fresh Mappls
   inputs, not that a neural net retrains every minute.

---

## 11. Exhaustive Mappls API inventory (C8) — grounded in `uploads/`

Every row below is a real endpoint from the docs you uploaded. "Used today" =
already wired in Part I (`ml/pipeline/mappls.py`, `backend/app/mappls.py`,
`frontend .../TestMap.jsx`). "New" = add for Part II.

| Mappls capability | Endpoint (from the uploaded doc) | Doc | TraFix use | Status |
|---|---|---|---|---|
| **Web Maps JS SDK v3.0** | `https://sdk.mappls.com/map/sdk/web?v=3.0&access_token=<KEY>` → `new mappls.Map('map',{center:{lat,lng}})` | `Web_JS-0.md` | base map | used |
| **Traffic Visualizer** | `mappls.trafficLayer({map,...})` / `traffic:true` | `Web_JS-0.md` | live congestion **visual** layer | used (`/test`) |
| **Heatmap layer** | `mappls.HeatmapLayer({data,...})` | `heatMap-3.md`, `heatmap-1.md` | citation-density heatmap | new |
| **GeoJSON layer** | `new mappls.addGeoJson({map,data,...})` | `geoJson-2.md` | draw H3 / superzone polygons coloured by PIC | new |
| **Driving Distance-Time Matrix** | `https://route.mappls.com/route/dm/distance_matrix/driving/{lng,lat;…}?rtype=0&region=ind&access_token=` (≤100 pts; `sources=`/`destinations=`) | `readme-10.md` | **free-flow baseline** travel time | used (free-flow) |
| **Predictive / Optimal / Live ETA Matrix** | `https://route.mappls.com/routev2/dm/distance?source=lng,lat&target=lng,lat&profile=driving&speedTypes=predictive\|optimal\|traffic&date_time=1,YYYY-MM-DDThh:mm&access_token=` | `readme-16.md` | **C2 live stress** (`traffic`) + **C3 tomorrow** (`predictive`) + typical (`optimal`) | **new (core)** |
| **Driving Range Polygon (Isochrone)** | `https://route.mappls.com/routev2/optimization/isopolygon?locations=lat,lng&costing=auto&rangeType=time&contours=15,ff0000&speedTypes=predictive&date_time=1,…&access_token=` | `readme-22.md` | **C4 coverage (MCLP)** — what each station reaches in N min, time-aware | **new (core)** |
| **Trip / Route Optimization (VRP/TSP)** | `https://route.mappls.com/route/optimization/trip_optimization_eta/driving/{lng,lat;…}?region=ind&roundtrip=true&source=first&destination=last&access_token=` | `readme-12/13/14.md` | **C4 exact patrol route** ordering | **new (core)** |
| **Snap-to-Road (+ V2)** | `https://route.mappls.com/route/movement/snapToRoad?pts=lng,lat;…&access_token=` · V2 `routev2/movement/trace_route` | `readme-25.md`, `readme-15.md` | place the A→B congestion segment on the real carriageway | used (V2) |
| **Nearby / Nearby Record Finder** | `https://search.mappls.com/search/places/nearby/json?keywords=&refLocation=lat,lng&radius=&access_token=` | `Readme-18.md`, `readme-11.md` | POI distances/counts (metro, market, school…) | used |
| **Reverse Geocode** | `https://search.mappls.com/search/address/rev-geocode?lat=&lng=&access_token=` | `Readme-21.md` | locality / road context for each zone | used |
| **Place Details (eLoc)** | (Place Details API) | `Readme-20.md` | resolve a POI to attributes | optional |
| **Text Search / Autosuggest** | (Text Search API) | `readme-0.md` | operator "jump to place" search box | optional |
| **POI Along The Route** | (POI Along Route) | `readme-17.md` | POIs along a planned patrol route | optional |
| **Aerial Distance** | (Aerial Distance API) | `readme-23.md` | cheap straight-line fallback when matrix quota is tight | optional |
| **Address Analytics** | (Address Analytics API) | `readme-24.md` | enrich `location` column attributes | optional |

🟢 **In plain words:** today we use Mappls for the map, POIs, road-snapping and a
free-flow travel time. The three **new core** calls are the ones that make the
product *live*: the **ETA matrix with `speedTypes`** (live + tomorrow's traffic),
the **isochrone** (who-can-reach-what-in-15-min), and **trip optimization** (the
exact order to visit hotspots). All three are documented in the files you shared.

> **Quota math (still cheap).** The ETA matrix accepts ≤100 points/call. For ~25
> monitored corridors (50 endpoints) one call every 15 min = **~96 calls/day** for
> live stress (C2). Tomorrow's forecast (C3) = 25 corridors × 24 hours, batched ≤
> 100 pts/call ≈ **~12 calls**, run once nightly. Isochrones: one per station per
> refresh. Comfortably inside a hackathon key.

---

## 12. Full feature engineering from all 24 columns (C9)

Raw header (verified from the CSV): `id, latitude, longitude, location,
vehicle_number, vehicle_type, description, violation_type, offence_code,
created_datetime, closed_datetime, modified_datetime, device_id, created_by_id,
center_code, police_station, data_sent_to_scita, junction_name,
action_taken_timestamp, data_sent_to_scita_timestamp, updated_vehicle_number,
updated_vehicle_type, validation_status, validation_timestamp`.

| # | Column | Null? | Feature(s) engineered | Feeds |
|---|---|---|---|---|
| 1 | `id` | no | row key; per-zone ticket **count** (the Poisson target) | all |
| 2 | `latitude` | 0 missing | H3 r10/r9 cell; superzone; `lat` context feature | hotspot, PU |
| 3 | `longitude` | 0 missing | H3 cell; `lon`; A→B corridor endpoints | hotspot, C2/C3 |
| 4 | `location` | sparse | regex → road-class keyword (ring/arterial/main/local) for CII; locality string | CII, display |
| 5 | `vehicle_number` | no (anon, stable) | repeat-offender share per zone; chronic-vehicle flag; 55× offender log | offenders, FE |
| 6 | `vehicle_type` | no | **footprint weight**; per-zone vehicle-mix vector → typology + "what enforcement" | Pillar A, typology |
| 7 | `description` | **100% null** | **DROP** (documented empty column) | — |
| 8 | `violation_type` | no (JSON array) | explode → severity weight per token; per-zone violation-mix % | Pillar A, FE |
| 9 | `offence_code` | no (JSON array) | auxiliary offence-severity feature (display + forecast feature) | forecaster |
| 10 | `created_datetime` | no | **date-level only**: day-of-week, is_holiday, week-trend, month; **hour deliberately excluded** (upload artifact) | C3 propensity, online |
| 11 | `closed_datetime` | **100% null** | **DROP** | — |
| 12 | `modified_datetime` | mostly | `modified − created` lag = **processing latency** (ops-quality feature) | quality |
| 13 | `device_id` | ~3,070 | part of **exposure** = distinct(device×date) → NB **log-offset** (bias fix) | hotspot (C2) |
| 14 | `created_by_id` | ~2,666 | exposure (distinct officers×days), **zone-level only** | bias fix |
| 15 | `center_code` | no | admin grouping; staffing rollup | dispatch |
| 16 | `police_station` | no | dispatch grouping; LambdaMART group; per-station coverage | dispatch, eval |
| 17 | `data_sent_to_scita` | bool | escalation/quality flag per zone | quality |
| 18 | `junction_name` | no (`No Junction` sentinel) | junction-criticality **J** in CII; distinct-junction corridor boost | CII |
| 19 | `action_taken_timestamp` | **100% null** | **DROP** | — |
| 20 | `data_sent_to_scita_timestamp` | sparse | escalation latency where present | quality |
| 21 | `updated_vehicle_number` | sparse | data-correction signal; reconcile with `vehicle_number` | quality |
| 22 | `updated_vehicle_type` | sparse | corrected footprint when present | Pillar A |
| 23 | `validation_status` | mixed | **drop** `rejected`/`duplicate`; `approved`→ confidence=high (Pillar A multiplier); per-zone **approval-rate** quality weight | clean, Pillar A |
| 24 | `validation_timestamp` | sparse | validation latency; recency of last validated ticket | quality, online |

🟢 **In plain words:** three columns are 100% empty and are honestly dropped; the
other 21 each earn their place — the two "officer/device" columns are the *most*
important because they are how we divide out policing bias, and the timestamp is
used **only at day granularity** because its hour is fake.

---

## 13. C1 — Live illegal-parking detection (honest version) ⚠️

🔧 **What is *not* possible.** The dataset is a closed historical archive: no live
ticket stream, no camera, no sensor. You **cannot** truthfully show "illegal
parking happening right now at X" from it alone. Claiming otherwise fails the
honesty contract and a sharp judge.

🔧 **What *is* possible, live, three layers:**

1. **Live risk surface (model, live inputs).** Per zone per current time-slice:
   `live_risk = historical_propensity(dow, slot) × live_stress(Mappls)`, where
   `historical_propensity` is the bias-corrected rate (§14/§15) for this
   day-of-week + slot and `live_stress` is the Mappls ETA ratio (§14). Recomputed
   every cycle → it *is* live, and it's an honest "where illegal parking is most
   likely to be biting **now**," not a detection.
2. **Live report → verify loop (ground truth, live).** Reuse Part I's operational
   three-number model: a **citizen/officer report** (complaint) raises
   `live_adjustment` for that zone; an officer **verifies** (`verified_obstruction`
   / `no_obstruction`); the outcome feeds the bandit (§17) and the Gamma-Poisson
   updater. This is the only *true* live "detection," and it's human-in-the-loop.
3. **(Future, labelled as such) CV detection.** A camera/dashcam model (YOLO-class)
   would give sensor-grade live detection. Out of scope for the dataset; name it
   as the productionization path, do not fake it.

🟢 **Say on stage:** *"We don't pretend a 5-month ticket file can see live cars.
We predict, live, **where** illegal parking most likely chokes traffic right now,
and we close the loop with citizen/officer reports that the system learns from.
Camera detection is the obvious next sensor."*

**Acceptance criteria:** `/api/live/risk?slot=` returns per-zone `live_risk` that
visibly changes when (a) Mappls stress changes and (b) a report is filed.

---

## 14. C2 — Congestion impact of parking (live + quasi-causal) ⚠️

This is two different claims; keep them separate.

### 14.1 Live *associational* stress (✅ live, honest)
🔧 For each top hotspot define a snapped A→B segment (~300–600 m). Poll the ETA
matrix (`readme-16.md`):
```
live_time   = ETA(speedTypes=traffic)         # live
typical_time= ETA(speedTypes=optimal)         # historical-pattern baseline, same slot
free_flow   = rolling-min ETA ever seen (or speedTypes with empty-road proxy)
CongestionSeverity = 1 − free_flow / live_time          # 0 clear … →1 gridlock
StressVsTypical    = live_time / typical_time            # >1 = worse than usual
PIC = ViolationIntensity (bias-corrected, §2/Pillar A) × CongestionSeverity
```
🟢 *"How slow is this block right now vs. empty, and vs. a normal day?" — measured
by Mappls, multiplied by our bias-corrected parking propensity = the live PIC
ranking.* This is **associational**: the block is both jam-prone and parking-prone.

### 14.2 Quasi-causal attribution (⚠️ needs a design, honest)
🔧 "Congestion *caused by* parking" is a causal claim → needs identification, not
just correlation. Two defensible designs from observational data:

- **Panel / fixed-effects regression.** Build a zone×slot panel of
  `CongestionSeverity` (collected live over days, §20) on `parking_intensity`
  with **zone fixed effects** (controls for "this road is just always busy") and
  **slot fixed effects** (controls for rush hour citywide):
  `severity_{z,t} = α_z + γ_t + β·parking_intensity_{z,t} + ε`. `β` is the
  within-zone association net of fixed road/time confounders — the closest honest
  estimate of attributable delay.
- **Event study around enforcement.** When enforcement clears a chronic zone
  (a step change in tickets/exposure), compare that zone's `CongestionSeverity`
  before vs after against matched control zones (difference-in-differences). Check
  **parallel pre-trends**; run **placebo** dates. If severity drops post-clearance
  more than controls, that's quasi-causal evidence parking was choking it.

🔧 **Report it as:** "estimated attributable delay per zone (β·intensity),
fixed-effects model, ±CI" — never "parking caused X minutes" without the CI and
the design name.

🟢 **Say on stage:** *"Pure causation needs an experiment we don't have. So we use
the standard observational substitutes — fixed-effects panels and a
before/after-enforcement event study — and we report confidence intervals, not a
single hero number."*

**Acceptance criteria:** a `causal_impact.json` with per-zone `beta`,
`ci_low/high`, `design`, `parallel_trends_p`, plus a placebo that returns ~0.

---

## 15. C3 — Tomorrow's hour-by-hour forecast (split into two honest halves)

### 15.1 Tomorrow's hour-by-hour **traffic** — ✅ via Mappls Predictive ETA
🔧 Mappls **Predictive ETA** (`readme-16.md`) takes a future `date_time` and
returns numeric travel time:
```
for slot_hour in 0..23 of tomorrow:
  GET routev2/dm/distance?source=lng,lat&target=lng,lat&profile=driving
      &speedTypes=predictive&date_time=1,<YYYY-MM-DD(tomorrow)Thh:00>
  → time_s  ⇒  predicted_severity[h] = 1 − free_flow/time_s
```
Do this per monitored corridor → a **24-point predicted congestion curve per
hotspot for any day of the week**, straight from Mappls' own model. Validate it by
**collecting the realized live ETA the next day and computing MAPE** (§18).
🟢 *"For tomorrow at 6 PM on MG Road, Mappls' predictive engine says the trip will
take T — we turn that into a congestion curve for every hotspot, all 24 hours."*

### 15.2 Tomorrow's **violations** — ❌ hourly, ✅ day-of-week intensity
🔧 You **cannot** forecast hourly *violations* (timestamp = upload time, §1).
Forecast **expected violation intensity per zone per day, by day-of-week**, with a
count model:
```
expected_violations_{z,day} ~ NegativeBinomial / LightGBM(objective=poisson),
features: dow, is_holiday, week_trend, lags(1,7,14), spatial-lag(neighbor hexes),
          vehicle-mix, POI density (Mappls Nearby), exposure offset
```
Real day-of-week signal exists (Sun highest, Mon lowest). This **extends Part I's
next-month forecaster (Stage 05)** down to a **daily** target on the existing
`daily.json` series.
🟢 *"We predict which blocks will be parking hotspots next Sunday and how hard —
that's the deployable signal. We don't fake an hourly violation curve the data
can't support."*

**Acceptance criteria:** `forecast_daily.json` (per-zone dow curve, backtested
Spearman ≥ ~0.6 on held-out weeks) **and** `forecast_eta.json` (per-corridor 24h
predicted severity, with next-day MAPE logged).

---

## 16. C4 — Exact police deployment optimization ✅

Three honest tiers; ship 1 and 2, demo 3 in sim.

🔧 **Tier 1 — coverage (MCLP via isochrone).** Use the **Driving Range Polygon**
(`readme-22.md`, time-aware via `speedTypes=predictive&date_time`) to compute each
station's "reachable in 15 min" polygon. Solve a **Maximal Covering Location
Problem** (Church & ReVelle): pick the officer assignment that covers the maximum
PIC-weighted hotspots within the time budget. Small instance → solve **exactly**
with OR-Tools CP-SAT / PuLP.
```
maximize  Σ_h PIC_h · y_h
s.t.      y_h ≤ Σ_{j covers h} x_j ;  Σ_j x_j ≤ officers ;  x,y ∈ {0,1}
```

🔧 **Tier 2 — route order (VRP/TSP).** Once a station's target hotspots are chosen,
get the **exact visiting order + drive-time** from **Trip Optimization**
(`readme-12/13/14.md`, `route/optimization/trip_optimization_eta`,
`roundtrip=true&source=first`). That's the real shortest patrol loop on live
roads, not a toy graph.

🔧 **Tier 3 — sequential policy (sim-RL, honest).** No dispatch logs exist, so RL
is **simulation-based**: the environment samples violations from the NB/Poisson
rate model, congestion from collected Mappls curves, and officer movement from
Mappls drive-times; reward = PIC-weighted catches − travel − uncovered-penalty.
Train LinUCB (Part I, already online) / a tabular Q-learner; **show it beating the
greedy baseline inside the simulator** with a regret curve. Frame exactly as
"trained in a data-calibrated simulator because real logs don't exist."

🟢 *"Plan A: cover the most live-PIC hotspots each station can physically reach in
15 minutes — solved to optimality. Plan B: Mappls gives the exact patrol route.
Plan C: a simulator-trained controller that beats the greedy plan — and we're
upfront it lives in a simulator."*

**Acceptance criteria:** `/api/dispatch/plan?station=` returns the MCLP assignment
+ VRP-ordered stops with live drive-times; sim notebook shows RL ≥ greedy.

---

## 17. C5 — Full online learning across all models ✅

| Model | Online mechanism | How |
|---|---|---|
| **Per-zone rate** | **Gamma-Poisson conjugacy** (closed-form) | each zone stores `(shape s, rate r)`; new day adds count→`s`, 1→`r`; `E[λ]=(s+Σy)/(r+n)`; gives uncertainty free |
| **Emerging-hotspot alarm** | **drift detection** (ADWIN / Page-Hinkley, `River`) | recent counts deviate from posterior → flag emerging hotspot (new mall, works, festival) |
| **Dispatch** | **LinUCB bandit** (already online, Part I) | officer feedback updates per-arm `A,b` immediately; persist matrices to Mongo |
| **Live stress / ETA** | **rolling store** (§20) | each cycle appends to the zone×slot panel; free-flow = rolling-min; recomputes PIC |
| **Count forecaster (GBM)** | **scheduled incremental refit** | LightGBM warm-start / nightly refit on the growing daily panel; or `River`'s online GBM for a pure-stream variant |

🔧 Add `online_state.json` (the per-zone Gamma params + drift status) persisted to
MongoDB and updated by the collector cron. The bandit already updates online.
🟢 *"Every block keeps a running 'betting line' on its violation rate, updated by
adding two numbers a day — no retraining. If a quiet block spikes past its line,
we ring an 'emerging hotspot' alarm. The dispatcher learns from each officer's
feedback in real time."*

**Acceptance criteria:** filing outcomes / appending a day visibly moves
`E[λ]` and can trip the drift flag; bandit picks shift after rewards.

---

## 18. C6 — Proper evaluation metrics (turn it into an *evaluated* solution) ✅

| Model / claim | Metrics | Protocol |
|---|---|---|
| **Hotspot detection (C1/C2)** | PR-AUC & **precision@k** for "is true top-decile pressure"; **Getis-Ord Gi\*** z/p significance; **Moran's I** on residuals (spatial leakage check) | **spatial-block CV** (leave-one-grid-region-out) so neighbours don't leak |
| **Bias correction** | rank-divergence vs naive count; % of top-k that are low-patrol; IRR (`e^β`) from the NB offset model | held-out months |
| **Daily forecaster (C3)** | Poisson deviance, MAE, R², Spearman, top-K precision; **calibration / PIT histogram** | temporal holdout (train early weeks → test later) + spatial split |
| **Predictive-ETA (C3 traffic)** | **MAPE / RMSE** of predicted vs realized next-day ETA | collect realized next day, compare to the prediction logged |
| **Causal (C2)** | β with CI; **parallel-trends** test; **placebo** dates → ~0; sensitivity to controls | event-study / fixed-effects |
| **Reranker (C4)** | **NDCG@10**, MAP, Kendall-τ vs realized pressure | station-grouped split (Part I already does NDCG) |
| **Dispatch policy (C4)** | cumulative PIC-weighted catches; **regret curve** vs greedy & random | inside the simulator |
| **Whole system** | sensitivity (±20%, ~40 configs, Part I); 13-metric self-check gate | `run_all.py` |

🟢 *"We don't just build models, we grade them — with the right protocol for each:
spatial CV so we don't cheat with neighbours, calibration so the counts are
believable, MAPE on tomorrow's ETA against what actually happened, and placebo
tests so the causal number isn't a fluke."*

**Acceptance criteria:** an `evaluation.json` + a one-page `EVALUATION.md` table
filled with real numbers from a full run.

---

## 19. C7 — Actual trained-model results to produce ✅

Part I already yields real numbers (per `ML_COMPARISON.md`): forecaster **R² 0.80,
CV R² 0.829 ± 0.063, Spearman 0.79, top-20 precision 0.70, Poisson deviance 22.4
vs GLM 29.5**; persistence backtest Spearman 0.80; self-check 13/13. To make Part
II "evaluated," **run and fill** this template:

| Model | Metric | Value | Holdout |
|---|---|---|---|
| NB hotspot (offset) | dispersion α; top-10% IRR | _run_ | spatial CV |
| Daily forecaster | Poisson dev / MAE / Spearman | _run_ | temporal+spatial |
| Predictive-ETA | next-day MAPE | _run_ | live re-poll |
| Causal panel | β, CI, placebo | _run_ | event study |
| Reranker | NDCG@10 | _run_ (Part I has it) | station split |
| Sim dispatch | regret vs greedy | _run_ | simulator |

🔧 Command: `python ml/pipeline/run_all.py` (existing) + the new stages
(`09_daily_forecast`, `10_causal_panel`, `11_eta_collector`) write into
`evaluation.json`. Nothing is "trained results" until this table has numbers.

---

## 20. The live collector — why this is "live, not historical" ✅

🔧 A scheduled job (cron / APScheduler / Vercel cron) every ~15 min:
1. `ETA(speedTypes=traffic)` for all corridors → append `{zone, ts, live_time}` to
   the zone×slot panel (MongoDB) → updates `CongestionSeverity`, `PIC`, `live_risk`.
2. Nightly: `ETA(speedTypes=predictive, date_time=tomorrow×24h)` → `forecast_eta.json`.
3. Nightly: refresh station **isochrones** (time-aware) for the MCLP.
4. On each new day of tickets (if a feed exists): Gamma-Poisson update + drift check.
5. Re-poll yesterday's predicted slots → log realized vs predicted (ETA MAPE).

🔧 Everything caches to disk/Mongo (Part I's offline-first contract): no key / no
network → serve last good values + the demo bundle; with a key → live.
🟢 *"A heartbeat job keeps asking Mappls 'how bad is each block now, and how bad
will it be tomorrow,' stores the answers, and recomputes the rankings — so the map
is live, and we can later prove yesterday's forecast against what actually
happened."*

---

## 21. Exactly what to build — ordered, with acceptance criteria

Build top-down; you have a defensible, *evaluated, live* demo even if you stop after step 5.

1. **Spatial hotspot upgrade (C2/C6).** Add H3 r10/r9 binning + **NB model with
   `log(exposure)` offset** + **Getis-Ord Gi\*** alongside the existing superzones.
   *Done when:* `hotspots.json` has bias-corrected rate + Gi\* z/p, evaluated by
   spatial-block CV.
2. **Live ETA collector + PIC (C2/C5/C8).** Wire `speedTypes=traffic` matrix on
   snapped corridors; store the panel; compute live `CongestionSeverity` + `PIC`.
   *Done when:* `/api/live/pic` changes between polls.
3. **All-24-column features (C9).** Implement the §12 table in `04b`/`05`.
   *Done when:* `zone_features.parquet` contains every non-dropped column's feature.
4. **Tomorrow forecast, both halves (C3).** `09_daily_forecast.py` (daily NB/GBM)
   + nightly **Predictive-ETA** curves. *Done when:* `forecast_daily.json` +
   `forecast_eta.json` exist and backtest/MAPE are logged.
5. **Exact dispatch (C4).** Isochrone-MCLP (OR-Tools) + Trip-Optimization route.
   *Done when:* `/api/dispatch/plan` returns assignment + ordered live route.
6. **Online learning (C5).** Gamma-Poisson `online_state.json` + River drift alarm;
   persist bandit. *Done when:* appending a day moves `E[λ]` / trips drift.
7. **Causal panel (C2).** `10_causal_panel.py` fixed-effects + event study with
   placebo. *Done when:* `causal_impact.json` has β, CI, parallel-trends, placebo≈0.
8. **Evaluation pack (C6/C7).** `evaluation.json` + `EVALUATION.md` filled.
   *Done when:* every model in §19 has a real number.
9. **(Stretch) Sim-RL (C4 Tier 3).** Simulator + regret curve beating greedy.

### Deliberately NOT done (and say so — credibility)
- ❌ Live *sensor* detection of illegal parking (no camera/live feed in data).
- ❌ Hour-of-day *violation* forecasting (timestamp is upload-time).
- ❌ "Parking caused N minutes" without a design + CI.
- ❌ Reading congestion off the Mappls colour overlay (visual only — use ETA API).
- ❌ RL trained on "historical dispatch" (no such ground truth).

---

## 22. New artifacts + endpoints (additive — Part I stays byte-identical)

| New artifact | Stage | Carries |
|---|---|---|
| `hotspots.json` | `02b_h3_nb` | H3 cell, bias-corrected rate, Gi\* z/p |
| `live_panel` (Mongo) | collector | zone×slot live ETA history |
| `forecast_daily.json` | `09_daily_forecast` | per-zone day-of-week intensity + CI |
| `forecast_eta.json` | nightly collector | per-corridor 24h predicted severity |
| `causal_impact.json` | `10_causal_panel` | β, CI, design, placebo |
| `online_state.json` | collector | per-zone Gamma `(s,r)` + drift flag |
| `evaluation.json` | `12_evaluate` | every metric in §18 |

| New endpoint | Returns |
|---|---|
| `GET /api/live/pic` | live PIC ranking (recomputed each cycle) |
| `GET /api/live/risk?slot=` | live per-zone risk surface (C1) |
| `GET /api/forecast/eta?zone=` | tomorrow's 24h predicted congestion curve |
| `GET /api/forecast/daily?zone=` | next-day-by-dow violation intensity |
| `GET /api/dispatch/plan?station=` | MCLP assignment + VRP-ordered live route |
| `GET /api/causal/impact?zone=` | attributable-delay β + CI |

---

## 23. Added references (Part II)

- **Count models / offset:** Cameron & Trivedi, *Regression Analysis of Count
  Data* (Poisson/NB exposure-offset = rate models).
- **Bias / feedback loops:** Lum & Isaac (2016) *To Predict and Serve?*; Ensign et
  al. (2018) *Runaway Feedback Loops in Predictive Policing* (arXiv 1706.09847).
- **Spatial significance:** Getis & Ord (1992); Ord & Getis (1995) Gi\*; Anselin
  (1995) LISA/Local Moran's I.
- **Coverage / routing:** Church & ReVelle (1974) Maximal Covering Location
  Problem; Larson (1974) hypercube queueing.
- **RL dispatch (simulation):** Repasky, Wang & Xie (2024) arXiv 2409.02246; Joe &
  Lau (ICAPS 2022 / IJCAI 2023). *(The earlier "Delahoz & Celikel 2024" citation
  is unverifiable — treat as non-existent; do not cite.)*
- **Online / drift:** Gamma-Poisson conjugacy (Johnson, Ott & Dogucu, *Bayes
  Rules!* ch. 5); Bifet & Gavaldà (2007) ADWIN; `River` streaming-ML library.
- **Parking & congestion motivation:** Shoup (2006) *Cruising for Parking*;
  Hampshire & Shoup (2018); Schaller (2006).
- **Mappls APIs (your `uploads/`):** Distance-Time Matrix (`readme-10`), Predictive
  ETA (`readme-16`), Isochrone/Driving-Range (`readme-22`), Trip Optimization
  (`readme-12/13/14`), Snap-to-Road (`readme-25/15`), Nearby (`Readme-18`/`readme-11`),
  Reverse Geocode (`Readme-21`), Web JS SDK v3.0 + Traffic Visualizer (`Web_JS-0`),
  Heatmap (`heatMap-3`), GeoJSON (`geoJson-2`).

> **Bottom line.** With this dataset + the live Mappls APIs you already have docs
> for, **7 of the 9 asks are fully buildable and 2 are buildable with an honest
> caveat** that strengthens the pitch. The single biggest unlock is the **Predictive
> ETA matrix** (`readme-16`): it turns "we can't forecast traffic" into "Mappls
> forecasts tomorrow's traffic for us, hour by hour, and we grade it against
> reality." Build §21 in order; the solution becomes *evaluated and live*, not
> historical.
