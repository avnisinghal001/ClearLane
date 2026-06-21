# ClearLane AI — ML Architecture v3 (the live-first master spec)

### Live illegal-parking hotspot intelligence + congestion impact + targeted enforcement, built on Mappls only

*Theory-backed, dataset-grounded, hackathon-buildable. Every method is tied to (a)
a real signal in the ClearLane dataset, (b) a real Mappls API/SDK you already have
docs for in `uploads/`, and (c) a real published paper. This v3 supersedes the
"Master Plan" by verifying which goals it actually meets and adding the missing,
**live** pieces — without ever claiming the ticket data measures congestion.*

> **What changed from the Master Plan → v3.** The Master Plan said "Mappls live
> traffic is visual-only, you can't read a number." That is true **only of the
> colored overlay**. Your uploaded docs reveal a numeric **Predictive ETA Matrix**
> (`readme-16.md`) that returns live, typical, *and future-hour* travel times — the
> single unlock that turns three "impossible" goals into shipped features.

---

## Table of contents

1. [Abstract](#1-abstract)
2. [How to read this doc](#2-how-to-read-this-doc)
3. [The 30-second pitch](#3-the-30-second-pitch)
4. [Verdict at a glance](#4-verdict-at-a-glance)
5. [The dataset truth](#5-the-dataset-truth)
6. [Architecture in one picture](#6-architecture-in-one-picture)
7. [The intellectual core: real hotspots, not policed ones](#7-the-intellectual-core-real-hotspots-not-policed-ones)
8. [C1: Live illegal-parking detection](#8-c1-live-illegal-parking-detection)
9. [C2: Causal congestion impact](#9-c2-causal-congestion-impact)
10. [C3: Tomorrow, hour by hour](#10-c3-tomorrow-hour-by-hour)
11. [C4: Exact police deployment](#11-c4-exact-police-deployment)
12. [C5: Full online learning](#12-c5-full-online-learning)
13. [C6: Proper evaluation metrics](#13-c6-proper-evaluation-metrics)
14. [C7: Actual trained-model results](#14-c7-actual-trained-model-results)
15. [C8: Exhaustive Mappls API usage](#15-c8-exhaustive-mappls-api-usage)
16. [C9: All 24 columns, fully engineered](#16-c9-all-24-columns-fully-engineered)
17. [The live collector](#17-the-live-collector)
18. [Complete ML specification: what to build](#18-complete-ml-specification-what-to-build)
19. [New artifacts and endpoints](#19-new-artifacts-and-endpoints)
20. [References](#20-references)

---

## 1. Abstract

**In one breath:** Bengaluru's 298k parking tickets only tell you *where police
already stand*, not *where illegal parking actually chokes traffic*. ClearLane (1)
statistically removes that enforcement bias to find the **true** hotspots, (2)
multiplies them by **live Mappls congestion** to rank the spots costing the city
the most road capacity **right now**, (3) forecasts **tomorrow's** pressure and
traffic, and (4) tells each station exactly **where to go and in what order** — and
learns from every outcome.

**The honesty spine (never break it):** the ticket data has **zero** speed/flow
columns, so we never say it *measures* congestion. The only *measured* congestion
signal is the **Mappls travel-time ratio**. The only *true live* "detection" is a
human report/verify loop. We say all of this out loud — it reads as rigor.

**Verdict in one line:** of the nine hard goals, **seven are fully buildable** on
this dataset + live Mappls, and **two (live detection, causation) are buildable
with an honest caveat** that strengthens the pitch. See [§4](#4-verdict-at-a-glance).

---

## 2. How to read this doc

Every technical section has two layers:

- 🔧 **Technical** — what to build, the math, the exact Mappls endpoint.
- 🟢 **In plain words** — how to explain it to a judge in one sentence.

**Verdict keys** (used in [§4](#4-verdict-at-a-glance) and each capability):

- ✅ **Buildable now** — dataset + live Mappls fully support it.
- ⚠️ **Buildable with an honest caveat** — possible, but say the limit out loud.
- ❌ **Not honestly possible from this data alone** — and what we do instead.

**Three words we keep separate, always:**

- *Measured* = counted in the data (ticket counts) or returned by Mappls (ETA).
- *Modeled* = our estimate (hotspot rate, forecast, attributable delay).
- *Assumed* = domain knowledge (congestion windows). Never dressed up as measured.

---

## 3. The 30-second pitch

> *"Parking tickets show where police patrol, not where parking chokes traffic. We
> remove that bias statistically, overlay Mappls' live travel-time congestion, and
> produce a ranked, live map of the parking hotspots costing Bengaluru the most
> road capacity right now — plus tomorrow's forecast and the exact patrol route to
> fix them. 2.5% of the city holds 50% of the problem; we send enforcement there."*

---

## 4. Verdict at a glance

This is the direct answer to *"does the Master Plan actually solve all of this?"*


| #   | Goal                                       | Master Plan?     | v3 verdict                                                                               | Live or historical          | Detail                                        |
| --- | ------------------------------------------ | ---------------- | ---------------------------------------------------------------------------------------- | --------------------------- | --------------------------------------------- |
| C1  | Genuine **live illegal-parking detection** | partial          | ⚠️ live *risk* + report/verify loop YES; live *sensor* detection NO                      | live (risk + reports)       | [§8](#8-c1-live-illegal-parking-detection)    |
| C2  | **Causal** congestion caused by parking    | named, not built | ⚠️ live *association* YES; *quasi-causal* (panel/event-study) YES; *pure causal* NO      | live stress + historical ID | [§9](#9-c2-causal-congestion-impact)          |
| C3  | **Tomorrow's hour-by-hour traffic**        | said impossible  | ✅ traffic YES via Mappls Predictive ETA; ❌ hourly *violations* → ✅ day-of-week intensity | live / predictive           | [§10](#10-c3-tomorrow-hour-by-hour)           |
| C4  | **Exact** police deployment                | greedy only      | ✅ MCLP coverage + VRP route + sim-RL                                                     | live                        | [§11](#11-c4-exact-police-deployment)         |
| C5  | **Full online learning**                   | partial (rates)  | ✅ Gamma-Poisson + drift + online bandit + scheduled refit                                | live                        | [§12](#12-c5-full-online-learning)            |
| C6  | **Proper evaluation**                      | mentioned        | ✅ spatial CV, PR-AUC@k, calibration, NDCG, regret, placebos                              | both                        | [§13](#13-c6-proper-evaluation-metrics)       |
| C7  | **Actual trained results**                 | none             | ✅ run + fill the results table (some already exist)                                      | both                        | [§14](#14-c7-actual-trained-model-results)    |
| C8  | **Exhaustive Mappls usage**                | ~3 APIs          | ✅ ~15 APIs mapped to features                                                            | live                        | [§15](#15-c8-exhaustive-mappls-api-usage)     |
| C9  | **All 24 columns engineered**              | ~12              | ✅ every column → feature or documented drop                                              | both                        | [§16](#16-c9-all-24-columns-fully-engineered) |


🟢 **Plain summary:** the Master Plan is a strong, honest *plan* but it is **not yet
an evaluated, live, fully-specified solution**. v3 closes that: it specifies the
live data loop, the exact models, the Mappls calls, the metrics, and the build
order so the result is **live (not historical) and graded**.

---

## 5. The dataset truth

The five signals that win, verified against the 298,450-row file.


| Fact                            | Detail                                                                                             | Why it matters                                                                                 |
| ------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| **Not "Jan–May"**               | real range **2023-11-09 → 2024-04-08**, Bengaluru only                                             | don't mislabel it on slides                                                                    |
| **Genuinely parking**           | ~**97%** of tags are parking (WRONG/NO PARKING dominate, then MAIN ROAD, FOOTPATH, DOUBLE PARKING) | the problem statement fits perfectly                                                           |
| **Timestamp = upload artifact** | hour pattern near-identical monthly, peaks ~10 AM; evening window tiny                             | you **cannot** forecast hourly violations — but it reveals an *evening enforcement gap*        |
| **Extreme concentration**       | a tiny share of cells holds ~half of all violations                                                | this IS the prioritization pitch                                                               |
| **Repeat offenders**            | ~**34%** of tickets from repeat vehicles; one vehicle 55×                                          | chronic-violator angle                                                                         |
| **Quality signal**              | a large share of validated tickets are *rejected*/*duplicate*                                      | weight tickets by confidence; drop the bad ones                                                |
| **Hotspots have types**         | car-heavy vs scooter/auto-heavy zones                                                              | recommend *what kind* of enforcement                                                           |
| **Exposure proxy exists**       | `device_id` (~~3,070), `created_by_id` (~~2,666)                                                   | the key to **bias correction** ([§7](#7-the-intellectual-core-real-hotspots-not-policed-ones)) |
| **No dispatch ground truth**    | `closed_datetime`, `action_taken_timestamp` **100% NULL**                                          | RL must be **simulation-based** ([§11](#11-c4-exact-police-deployment))                        |
| **No traffic data**             | zero speed/flow columns                                                                            | congestion must come **live from Mappls** ([§9](#9-c2-causal-congestion-impact))               |


🟢 **Plain words:** a clean, dense, Bengaluru-only ticket log. Biggest trap: the
timestamp records *upload* time, not when the car parked. Biggest gift: illegal
parking is absurdly concentrated — a sliver of the city is the whole problem.

---

## 6. Architecture in one picture

```text
              HISTORICAL                          LIVE  (Mappls only)
   298k Bengaluru parking tickets        ┌─────────────────────────────────┐
              │                          │ Web SDK trafficLayer (visual)    │
   ┌──────────┼───────────┐              │ ETA matrix speedTypes=traffic    │ → live stress
   ▼          ▼           ▼              │ ETA matrix speedTypes=predictive │ → tomorrow
 H3 bins   exposure   features(§16)      │ isochrone (driving-range polygon)│ → coverage
   │       (dev×date)     │              │ trip_optimization (VRP)          │ → patrol order
   └────┬───────┘         │              └───────────────┬─────────────────┘
        ▼                 │                              │
 NB model w/ log-exposure OFFSET  ◄───────┘              │
 + Getis-Ord Gi* significance  → ViolationIntensity_h    │
        │                                                │
        ▼                                                ▼
   PIC_h = ViolationIntensity_h  ×  CongestionSeverity_h (live)
        │
   ┌────┼──────────────┬────────────────────┬───────────────────┐
   ▼    ▼              ▼                    ▼                   ▼
 map  live risk    forecast (C3)        dispatch (C4)       online (C5)
 (§8) surface      daily NB + ETA       MCLP + VRP + RL     Gamma-Poisson
                   curves                                   + drift alarm
        └──────────────────── evaluation (C6) wraps everything ──────────┘
```

🟢 **Plain words:** the left half is computed once from history; the right half is
polled live from Mappls every cycle; PIC fuses them; the bottom row is the four
products (map, forecast, dispatch, learning) — all graded by the evaluation layer.

---

## 7. The intellectual core: real hotspots, not policed ones

This is the section that wins, because it's the one thing other teams get wrong.

### 7.1 The trap (with the theory that names it)

If you count tickets per area and color the map, you find **where police patrol**,
not where illegal parking is. The literature names this failure:

- **Lum & Isaac (2016)** — predictive policing on enforcement data = *"selection
bias meets confirmation bias"*: police go where they went, write more tickets,
"confirm" the hotspot. A feedback loop.
- **Ensign et al. (2018)** — proved it formally; fix = reweight by how much each
area was sampled (patrolled).

🟢 *If a street gets 700 tickets only because an officer sits there all day, a naive
heatmap screams "hotspot" — but it's an "officer-spot." We divide out the policing.*

### 7.2 The fix — H3 bins + exposure-corrected count model + significance

🔧 **Step A — Hexagon binning (Uber H3).** Bin each ticket to an H3 **res-10** cell
(`h3.latlng_to_cell(lat, lon, 10)`, ~~65.9 m edge ≈ one block). Hexagons beat
squares (every neighbor equidistant). Use res-9 (~~174 m) for the city zoom.

🔧 **Step B — Exposure proxy.** Per cell, `exposure_h = distinct (device_id × date) pairs` = how much enforcement effort the cell received.

🔧 **Step C — Negative-Binomial with a log-exposure offset.**

```text
citations_h ~ NegativeBinomial(μ_h)
log(μ_h)    = β0 + β·X_h + log(exposure_h)      # offset: coefficient fixed at 1
```

The `log(exposure_h)` **offset** converts "count" → "rate per unit of effort." Use
**NB not Poisson** because ticket counts are over-dispersed (variance ≫ mean); run a
dispersion test and, if α≈0, fall back to Poisson and say so. Report **Incidence
Rate Ratios** = `e^β`. (Offset/exposure = textbook count regression, Cameron &
Trivedi; motivation = Lum-Isaac / Ensign.)

🔧 **Step D — Significance (Getis-Ord Gi).** Run **Gi** on the corrected rates →
each cell gets a **z-score + p-value** (which hotspots are statistically real).
Companion: **Local Moran's I / LISA** flags spatial outliers (a hot block ringed by
cold ones). Use **KDE** only for the smooth visual.

🟢 *We compute violations-per-unit-of-policing, then prove the hotspots are hotter
than chance — so we find real illegal parking, including where nobody patrols.*

> **Relation to the shipped repo:** the current pipeline already does an exposure
> correction (`bias_adjusted = pressure / exposure^0.5`) on ~500 m superzones. v3
> upgrades this to the **statistically standard NB-offset + Gi** on H3 cells and
> runs both side by side (superzones for ops, H3 for the science claim).

---

## 8. C1: Live illegal-parking detection

**Verdict ⚠️ — partial, and honesty here is a feature.**

🔧 **What is NOT possible.** A closed 5-month ticket archive has no live feed, no
camera, no sensor. You **cannot** truthfully show "a car is illegally parked at X
right now" from it. Claiming so fails the honesty spine.

🔧 **What IS possible, live, in three layers:**

1. **Live risk surface (model, live inputs).** Per cell, per current slot:
  `live_risk = propensity(dow, slot) × live_stress(Mappls)`, recomputed every
   cycle. It changes when Mappls stress changes → genuinely live. It's an honest
   *"where illegal parking is most likely biting now,"* not a detection.
2. **Report → verify loop (true live ground truth, human-in-the-loop).** A citizen
  or officer files a report → raises that cell's `live_adjustment`; an officer
   verifies (`verified_obstruction` / `no_obstruction`) → the outcome trains the
   bandit ([§11](#11-c4-exact-police-deployment)) and the rate updater
   ([§12](#12-c5-full-online-learning)). This is the only *true* live detection.
3. **(Future, labeled) CV detection.** A camera/dashcam YOLO-class model gives
  sensor-grade detection. Out of scope for this dataset — name it, don't fake it.

🟢 *We don't pretend a ticket file sees live cars. We predict, live, where illegal
parking most likely chokes traffic now, and we confirm it with citizen/officer
reports the system learns from. Cameras are the obvious next sensor.*

**Acceptance:** `GET /api/live/risk?slot=` returns per-cell `live_risk` that visibly
moves when (a) Mappls stress changes and (b) a report is filed.

---

## 9. C2: Causal congestion impact

**Verdict ⚠️ — live *association* is easy and honest; *causation* needs a design.**

Keep two different claims apart.

### 9.1 Live associational stress (✅ live)

🔧 For each top hotspot, snap a short A→B segment (~300–600 m) to the road
([§15](#15-c8-exhaustive-mappls-api-usage) Snap-to-Road), then poll the ETA matrix:

```text
live_time    = ETA(speedTypes=traffic)      # live
typical_time = ETA(speedTypes=optimal)      # historical-pattern baseline, same slot
free_flow    = rolling-min ETA ever seen for that segment
CongestionSeverity = 1 − free_flow / live_time      # 0 clear … →1 gridlock
StressVsTypical    = live_time / typical_time        # >1 = worse than usual
PIC_h = ViolationIntensity_h (bias-corrected, §7) × CongestionSeverity_h
```

🟢 *"How slow is this block now vs. empty, and vs. a normal day?" — measured by
Mappls — times our bias-corrected parking propensity = the live PIC ranking.*

### 9.2 Quasi-causal attribution (⚠️ design required)

🔧 "Caused by parking" is causal → needs identification. Two defensible designs on
observational data (collected live over days, [§17](#17-the-live-collector)):

- **Fixed-effects panel.** Build a cell×slot panel of `CongestionSeverity` on
`parking_intensity` with **cell** and **slot** fixed effects:
`severity_{z,t} = α_z + γ_t + β·parking_intensity_{z,t} + ε`. `β` = within-cell
association net of "this road is always busy" and "it's rush hour citywide" — the
closest honest "attributable delay."
- **Event study around enforcement.** When a chronic cell gets cleared (a step
change in tickets/exposure), compare its `CongestionSeverity` before/after vs.
matched control cells (**difference-in-differences**). Check **parallel
pre-trends**; run **placebo** dates.

🔧 Report as *"estimated attributable delay (β·intensity), fixed-effects, ±CI,"*
never "parking caused N minutes" without the CI and design name.

🟢 *Pure causation needs an experiment we don't have. So we use the standard
substitutes — fixed-effects panels and a before/after-enforcement study — and we
report confidence intervals and placebo tests, not a single hero number.*

**Acceptance:** `causal_impact.json` with per-cell `beta`, `ci_low/high`, `design`,
`parallel_trends_p`, and a placebo that returns ≈0.

---

## 10. C3: Tomorrow, hour by hour

**Verdict: ✅ traffic (via Mappls) · ❌ hourly violations → ✅ daily violations.**

### 10.1 Tomorrow's hour-by-hour TRAFFIC — ✅ via Mappls Predictive ETA

🔧 The **Predictive ETA Matrix** (`readme-16.md`) takes a future `date_time` and
returns a numeric travel time:

```bash
# per corridor, per hour of tomorrow
GET https://route.mappls.com/routev2/dm/distance
    ?source=<lng,lat>&target=<lng,lat>&profile=driving
    &speedTypes=predictive&date_time=1,<YYYY-MM-DD(tomorrow)Thh:00>
    &access_token=<KEY>
# → time(s) ⇒ predicted_severity[h] = 1 − free_flow / time
```

Loop hours 0–23 → a **24-point predicted congestion curve per hotspot for any day
of the week**, straight from Mappls' own model. `speedTypes=optimal` gives the
typical-day curve without waiting. Validate by re-polling the realized live ETA the
next day and computing **MAPE** ([§13](#13-c6-proper-evaluation-metrics)).

🟢 *"For tomorrow 6 PM on MG Road, Mappls' predictive engine says the trip takes T."
We turn that into a congestion curve for every hotspot, all 24 hours — and we grade
it against what actually happens.*

### 10.2 Tomorrow's VIOLATIONS — ❌ hourly, ✅ day-of-week intensity

🔧 You **cannot** forecast hourly violations (timestamp = upload time, [§5](#5-the-dataset-truth)).
Forecast **expected intensity per cell per day, by day-of-week**:

```text
expected_violations_{z,day} ~ NegativeBinomial / LightGBM(objective=poisson)
features: day-of-week, is_holiday, week-trend, lags(1,7,14),
          spatial-lag (neighbor cells), vehicle-mix, POI density (Mappls Nearby),
          exposure offset
```

The real day-of-week signal (Sun high, Mon low) is robust at date level. This
*extends* the repo's existing next-month Poisson forecaster down to a **daily**
target. Deep ST nets (ST-ResNet, DCRNN, Graph WaveNet, STGCN) need dense 30-min
feeds for months — overkill here; name them as future work.

🟢 *We predict which blocks will be hotspots next Sunday and how hard — the
deployable signal — and we don't fake an hourly violation curve the data can't
support.*

**Acceptance:** `forecast_daily.json` (per-cell dow curve, backtested Spearman) +
`forecast_eta.json` (per-corridor 24h predicted severity + next-day MAPE).

---

## 11. C4: Exact police deployment

**Verdict ✅ — three honest tiers; ship 1 and 2, demo 3 in simulation.**

🔧 **Tier 1 — coverage (MCLP via isochrone).** Use the **Driving Range Polygon /
isochrone** (`readme-22.md`, time-aware with `speedTypes=predictive&date_time`) to
get each station's "reachable in 15 min" polygon, then solve a **Maximal Covering
Location Problem** (Church & ReVelle 1974) **exactly** with OR-Tools CP-SAT / PuLP:

```text
maximize  Σ_h PIC_h · y_h
s.t.      y_h ≤ Σ_{j covers h} x_j ;   Σ_j x_j ≤ officers ;   x,y ∈ {0,1}
```

```bash
# isochrone per station (15-min drive polygon, tomorrow 18:00)
GET https://route.mappls.com/routev2/optimization/isopolygon
    ?locations=<lat,lng>&costing=auto&rangeType=time&contours=15,ff0000
    &speedTypes=predictive&date_time=1,<YYYY-MM-DDT18:00>&access_token=<KEY>
```

🔧 **Tier 2 — route order (VRP/TSP).** Once a station's targets are chosen, get the
exact visiting order + drive-time from **Trip Optimization** (`readme-12/13/14.md`):

```bash
GET https://route.mappls.com/route/optimization/trip_optimization_eta/driving/
    <lng,lat;lng,lat;...>?region=ind&roundtrip=true&source=first&destination=last
    &access_token=<KEY>
```

🔧 **Tier 3 — sequential policy (sim-RL, honest).** No dispatch logs exist → RL is
**simulation-based**: violations sampled from the NB rate model, congestion from
collected Mappls curves, officer movement from Mappls drive-times; reward =
PIC-weighted catches − travel − uncovered-penalty. Train LinUCB (already online in
the repo) / a Q-learner; **show it beating greedy in-sim** with a regret curve.
Frame exactly as "trained in a data-calibrated simulator because real logs don't
exist." (Repasky 2024; Joe & Lau 2022/2023. The "Delahoz & Celikel 2024" citation
is **non-existent** — do not cite it.)

🟢 *Plan A: cover the most live-PIC hotspots each station can physically reach in 15
min — solved to optimality. Plan B: Mappls gives the exact patrol route. Plan C: a
simulator-trained controller that beats greedy — and we're upfront it's a simulator.*

**Acceptance:** `GET /api/dispatch/plan?station=` returns the MCLP assignment + VRP-
ordered stops with live drive-times; a notebook shows RL ≥ greedy.

---

## 12. C5: Full online learning

**Verdict ✅ — every model has an online path.**


| Model                      | Online mechanism                                    | How                                                                                                 |
| -------------------------- | --------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| **Per-cell rate**          | **Gamma-Poisson conjugacy** (closed-form)           | store `(shape s, rate r)`; each new day: `s += Σy`, `r += n`; `E[λ]=(s+Σy)/(r+n)`; uncertainty free |
| **Emerging-hotspot alarm** | **drift detection** (ADWIN / Page-Hinkley, `River`) | recent counts deviate from posterior → flag emerging hotspot                                        |
| **Dispatch**               | **LinUCB bandit** (already online)                  | officer feedback updates per-arm `A,b` instantly; persist to Mongo                                  |
| **Live stress / ETA**      | **rolling store** ([§17](#17-the-live-collector))   | each cycle appends to the cell×slot panel; free-flow = rolling-min; recompute PIC                   |
| **Daily forecaster (GBM)** | **scheduled incremental refit**                     | LightGBM warm-start / nightly refit on the growing panel; or `River` online GBM for a pure stream   |


🔧 The Gamma-Poisson math (no retraining, ever):

```text
prior:     λ_h ~ Gamma(s, r)
observe:   counts y over n new days
posterior: λ_h ~ Gamma(s + Σy, r + n)
estimate:  E[λ_h] = (s + Σy) / (r + n)
```

Persist `online_state.json` (per-cell Gamma params + drift flag) to MongoDB; update
it from the collector cron.

🟢 *Each block keeps a running "betting line" on its violation rate, updated by
adding two numbers a day — no retraining. If a quiet block spikes past its line, we
ring an "emerging hotspot" alarm. The dispatcher learns from each officer outcome
in real time.*

**Acceptance:** appending a day visibly moves `E[λ]` and can trip the drift flag;
bandit picks shift after rewards.

---

## 13. C6: Proper evaluation metrics

**Verdict ✅ — this is what turns a plan into an *evaluated solution*.**


| Model / claim                                                                         | Metrics                                                                                                | Protocol                                         |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------ |
| **Hotspot detection** ([§7](#7-the-intellectual-core-real-hotspots-not-policed-ones)) | PR-AUC & **precision@k** for "true top-decile"; **Gi** z/p; **Moran's I** on residuals (leakage check) | **spatial-block CV** (leave-one-grid-region-out) |
| **Bias correction**                                                                   | rank-divergence vs naive count; % of top-k that are low-patrol; IRR (`e^β`)                            | held-out months                                  |
| **Daily forecaster** ([§10](#10-c3-tomorrow-hour-by-hour))                            | Poisson deviance, MAE, R², Spearman, top-K precision; **calibration / PIT histogram**                  | temporal holdout + spatial split                 |
| **Predictive-ETA** ([§10](#10-c3-tomorrow-hour-by-hour))                              | **MAPE / RMSE** predicted vs realized next-day ETA                                                     | re-poll next day vs logged prediction            |
| **Causal** ([§9](#9-c2-causal-congestion-impact))                                     | β + CI; **parallel-trends** test; **placebo** ≈ 0; control sensitivity                                 | event-study / fixed-effects                      |
| **Reranker** ([§11](#11-c4-exact-police-deployment))                                  | **NDCG@10**, MAP, Kendall-τ vs realized pressure                                                       | station-grouped split                            |
| **Dispatch policy** ([§11](#11-c4-exact-police-deployment))                           | cumulative PIC-weighted catches; **regret curve** vs greedy & random                                   | inside simulator                                 |
| **Whole system**                                                                      | sensitivity (±20%, ~40 configs); self-check regression gate                                            | full pipeline run                                |


🟢 *We don't just build models, we grade them — spatial CV so neighbors don't leak,
calibration so counts are believable, MAPE on tomorrow's ETA vs reality, and
placebo tests so the causal number isn't a fluke.*

**Acceptance:** `evaluation.json` + a one-page `EVALUATION.md` table filled with
real numbers from a full run.

---

## 14. C7: Actual trained-model results

**Verdict ✅ — some already exist; run the rest and fill the table.**

The shipped next-month forecaster already reports real numbers (from the repo's
comparison notes): **R² ≈ 0.80, CV R² ≈ 0.83 ± 0.06, Spearman ≈ 0.79, top-20
precision ≈ 0.70, Poisson deviance ≈ 22.4 vs GLM ≈ 29.5**; persistence backtest
Spearman ≈ 0.80; self-check 13/13. To make **v3** "evaluated," run the new stages
and fill this:


| Model               | Metric                       | Value    | Holdout          |
| ------------------- | ---------------------------- | -------- | ---------------- |
| NB hotspot (offset) | dispersion α; top-10% IRR    | *run*    | spatial CV       |
| Daily forecaster    | Poisson dev / MAE / Spearman | *run*    | temporal+spatial |
| Predictive-ETA      | next-day MAPE                | *run*    | live re-poll     |
| Causal panel        | β, CI, placebo               | *run*    | event study      |
| Reranker            | NDCG@10                      | *exists* | station split    |
| Sim dispatch        | regret vs greedy             | *run*    | simulator        |


🔧 Until this table has numbers, it is *not* "trained results." The pipeline run +
the new stages ([§18](#18-complete-ml-specification-what-to-build)) write them into
`evaluation.json`.

---

## 15. C8: Exhaustive Mappls API usage

**Verdict ✅ — every row is a real endpoint from the docs in `uploads/`.**


| Capability                              | Endpoint (from your uploaded doc)                                                                                                                                             | Doc                            | ClearLane use                             |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ | ----------------------------------------- |
| **Web Maps JS SDK v3.0**                | `https://sdk.mappls.com/map/sdk/web?v=3.0&access_token=<KEY>` → `new mappls.Map('map',{center:{lat,lng}})`                                                                    | `Web_JS-0.md`                  | base map                                  |
| **Traffic Visualizer**                  | `mappls.trafficLayer({map,...})` / `traffic:true`                                                                                                                             | `Web_JS-0.md`                  | live congestion **visual** layer          |
| **Heatmap layer**                       | `mappls.HeatmapLayer({data,...})`                                                                                                                                             | `heatMap-3.md`                 | citation-density heatmap                  |
| **GeoJSON layer**                       | `new mappls.addGeoJson({map,data,...})`                                                                                                                                       | `geoJson-2.md`                 | H3 / zone polygons colored by PIC         |
| **Distance-Time Matrix (free-flow)**    | `https://route.mappls.com/route/dm/distance_matrix/driving/<lng,lat;…>?rtype=0&region=ind&access_token=` (≤100 pts)                                                           | `readme-10.md`                 | free-flow baseline                        |
| **Predictive / Optimal / Live ETA**     | `https://route.mappls.com/routev2/dm/distance?source=&target=&profile=driving&speedTypes=predictive|optimal|traffic&date_time=1,YYYY-MM-DDThh:mm&access_token=`               | `readme-16.md`                 | **core**: live stress (C2), tomorrow (C3) |
| **Isochrone (Driving Range Polygon)**   | `https://route.mappls.com/routev2/optimization/isopolygon?locations=lat,lng&costing=auto&rangeType=time&contours=15,ff0000&speedTypes=predictive&date_time=1,…&access_token=` | `readme-22.md`                 | **core**: MCLP coverage (C4)              |
| **Trip / Route Optimization (VRP/TSP)** | `https://route.mappls.com/route/optimization/trip_optimization_eta/driving/<lng,lat;…>?region=ind&roundtrip=true&source=first&destination=last&access_token=`                 | `readme-12/13/14.md`           | **core**: exact patrol route (C4)         |
| **Snap-to-Road (+V2)**                  | `https://route.mappls.com/route/movement/snapToRoad?pts=<lng,lat;…>&access_token=` · V2 `routev2/movement/trace_route`                                                        | `readme-25/15.md`              | place A→B segment on the carriageway      |
| **Nearby / Record Finder**              | `https://search.mappls.com/search/places/nearby/json?keywords=&refLocation=lat,lng&radius=&access_token=`                                                                     | `Readme-18.md`, `readme-11.md` | POI distances/counts                      |
| **Reverse Geocode**                     | `https://search.mappls.com/search/address/rev-geocode?lat=&lng=&access_token=`                                                                                                | `Readme-21.md`                 | locality / road context                   |
| **Place Details (eLoc)**                | Place Details API                                                                                                                                                             | `Readme-20.md`                 | resolve a POI to attributes               |
| **Text Search / Autosuggest**           | Text Search API                                                                                                                                                               | `readme-0.md`                  | operator "jump to place" box              |
| **POI Along The Route**                 | POI Along Route                                                                                                                                                               | `readme-17.md`                 | POIs along a patrol route                 |
| **Aerial Distance**                     | Aerial Distance API                                                                                                                                                           | `readme-23.md`                 | cheap straight-line fallback              |
| **Address Analytics**                   | Address Analytics API                                                                                                                                                         | `readme-24.md`                 | enrich `location` attributes              |


> **Quota math (cheap).** Live stress: ~~25 corridors × 1 call / 15 min ≈ **~~96
> calls/day**. Tomorrow forecast: 25 corridors × 24 h, batched ≤100 pts ≈ **~12
> calls/night**. Isochrones: one per station per refresh. Comfortable on a hackathon
> key. Everything is cached to disk/Mongo (offline-first), so no key = last-good
> values + demo bundle.

🟢 *Today we use Mappls for the map, POIs, road-snapping and a free-flow time. The
three new **core** calls make it live: the ETA matrix with `speedTypes` (live +
tomorrow), the isochrone (who-reaches-what-in-15-min), and trip optimization (the
exact route). All documented in the files you shared.*

---

## 16. C9: All 24 columns, fully engineered

**Verdict ✅ — every column earns a feature or a documented drop.**

Raw header (verified): `id, latitude, longitude, location, vehicle_number, vehicle_type, description, violation_type, offence_code, created_datetime, closed_datetime, modified_datetime, device_id, created_by_id, center_code, police_station, data_sent_to_scita, junction_name, action_taken_timestamp, data_sent_to_scita_timestamp, updated_vehicle_number, updated_vehicle_type, validation_status, validation_timestamp`.


| #   | Column                         | Null?              | Feature(s)                                                                      | Feeds              |
| --- | ------------------------------ | ------------------ | ------------------------------------------------------------------------------- | ------------------ |
| 1   | `id`                           | no                 | row key; per-cell ticket **count** (Poisson target)                             | all                |
| 2   | `latitude`                     | 0 miss             | H3 r10/r9 cell; `lat` context; A→B endpoint                                     | hotspot, C2/C3     |
| 3   | `longitude`                    | 0 miss             | H3 cell; `lon`; corridor endpoint                                               | hotspot, C2/C3     |
| 4   | `location`                     | sparse             | regex → road-class (ring/arterial/main/local); locality                         | CII, display       |
| 5   | `vehicle_number`               | no (anon)          | repeat-offender share; chronic flag; 55× log                                    | offenders, FE      |
| 6   | `vehicle_type`                 | no                 | **footprint weight**; vehicle-mix vector → typology                             | Pillar A, typology |
| 7   | `description`                  | **100% null**      | **DROP** (documented empty)                                                     | —                  |
| 8   | `violation_type`               | no (JSON)          | explode → severity weight; violation-mix %                                      | Pillar A, FE       |
| 9   | `offence_code`                 | no (JSON)          | auxiliary offence-severity feature                                              | forecaster         |
| 10  | `created_datetime`             | no                 | **date-level only**: dow, is_holiday, week-trend, month; **hour excluded**      | C3, online         |
| 11  | `closed_datetime`              | **100% null**      | **DROP**                                                                        | —                  |
| 12  | `modified_datetime`            | mostly             | `modified − created` = processing latency                                       | quality            |
| 13  | `device_id`                    | ~3,070             | part of **exposure** = distinct(device×date) → NB **offset**                    | bias fix           |
| 14  | `created_by_id`                | ~2,666             | exposure (officers×days), **zone-level only**                                   | bias fix           |
| 15  | `center_code`                  | no                 | admin grouping; staffing rollup                                                 | dispatch           |
| 16  | `police_station`               | no                 | dispatch grouping; LambdaMART group; coverage                                   | dispatch, eval     |
| 17  | `data_sent_to_scita`           | bool               | escalation/quality flag                                                         | quality            |
| 18  | `junction_name`                | no (`No Junction`) | junction-criticality **J**; multi-junction boost                                | CII                |
| 19  | `action_taken_timestamp`       | **100% null**      | **DROP**                                                                        | —                  |
| 20  | `data_sent_to_scita_timestamp` | sparse             | escalation latency where present                                                | quality            |
| 21  | `updated_vehicle_number`       | sparse             | data-correction signal                                                          | quality            |
| 22  | `updated_vehicle_type`         | sparse             | corrected footprint when present                                                | Pillar A           |
| 23  | `validation_status`            | mixed              | drop `rejected`/`duplicate`; `approved`→ confidence; per-cell **approval-rate** | clean, Pillar A    |
| 24  | `validation_timestamp`         | sparse             | validation latency; recency                                                     | quality, online    |


🟢 *Three columns are 100% empty and honestly dropped; the other 21 each earn a
spot. The two officer/device columns are the most important — they're how we divide
out policing bias — and the timestamp is used only at day level because its hour is
fake.*

---

## 17. The live collector

**This is why v3 is "live, not historical."** A scheduled job (cron / APScheduler /
Vercel cron) every ~15 min:

1. `ETA(speedTypes=traffic)` for all corridors → append `{cell, ts, live_time}` to
  the cell×slot panel (MongoDB) → recompute `CongestionSeverity`, `PIC`,
   `live_risk`.
2. **Nightly:** `ETA(speedTypes=predictive, date_time = tomorrow × 24h)` →
  `forecast_eta.json`.
3. **Nightly:** refresh station **isochrones** (time-aware) for the MCLP.
4. On each new day of tickets (if a feed exists): Gamma-Poisson update + drift check.
5. Re-poll yesterday's predicted slots → log realized vs predicted (ETA MAPE).

Everything caches to disk/Mongo (offline-first): no key → serve last-good values +
demo bundle; with a key → live.

🟢 *A heartbeat keeps asking Mappls "how bad is each block now, and how bad will it
be tomorrow," stores the answers, and recomputes the rankings — so the map is live,
and we can later prove yesterday's forecast against what actually happened.*

---

## 18. Complete ML specification: what to build

Build top-down. You have a defensible, **evaluated, live** demo even if you stop
after step 5. Each step lists its acceptance criterion.

1. **Spatial hotspot core** ([§7](#7-the-intellectual-core-real-hotspots-not-policed-ones)).
  H3 r10/r9 binning + **NB model with `log(exposure)` offset** + **Getis-Ord Gi**.
   *Done when:* `hotspots.json` has bias-corrected rate + Gi z/p, evaluated by
   spatial-block CV.
2. **Live ETA collector + PIC** ([§9](#9-c2-causal-congestion-impact), [§17](#17-the-live-collector)).
  Wire `speedTypes=traffic` on snapped corridors; store the panel; compute live
   `CongestionSeverity` + `PIC`. *Done when:* `/api/live/pic` changes between polls.
3. **All-24-column features** ([§16](#16-c9-all-24-columns-fully-engineered)).
  Implement the feature table. *Done when:* the feature store has every non-dropped
   column's feature.
4. **Tomorrow forecast, both halves** ([§10](#10-c3-tomorrow-hour-by-hour)).
  Daily NB/GBM + nightly Predictive-ETA curves. *Done when:* `forecast_daily.json`
  - `forecast_eta.json` exist with backtest/MAPE logged.
5. **Exact dispatch** ([§11](#11-c4-exact-police-deployment)).
  Isochrone-MCLP (OR-Tools) + Trip-Optimization route. *Done when:*
   `/api/dispatch/plan` returns assignment + ordered live route.
6. **Online learning** ([§12](#12-c5-full-online-learning)).
  Gamma-Poisson `online_state.json` + River drift; persist bandit. *Done when:*
   appending a day moves `E[λ]` / trips drift.
7. **Causal panel** ([§9](#9-c2-causal-congestion-impact)).
  Fixed-effects + event study with placebo. *Done when:* `causal_impact.json` has
   β, CI, parallel-trends, placebo ≈ 0.
8. **Evaluation pack** ([§13](#13-c6-proper-evaluation-metrics), [§14](#14-c7-actual-trained-model-results)).
  `evaluation.json` + `EVALUATION.md` filled. *Done when:* every model has a real
   number.
9. **(Stretch) Sim-RL** ([§11](#11-c4-exact-police-deployment)).
  Simulator + regret curve beating greedy.

### Deliberately NOT done (say so — it's a credibility win)

- ❌ Live *sensor* detection of illegal parking (no camera/live feed in data).
- ❌ Hour-of-day *violation* forecasting (timestamp is upload time).
- ❌ "Parking caused N minutes" without a design + CI.
- ❌ Reading congestion off the Mappls color overlay (visual only — use ETA API).
- ❌ RL trained on "historical dispatch" (no such ground truth).
- ❌ Heavy graph-deep ST nets (data too sparse/short — overkill).

---

## 19. New artifacts and endpoints


| New artifact          | Stage             | Carries                                                 |
| --------------------- | ----------------- | ------------------------------------------------------- |
| `hotspots.json`       | H3 + NB           | H3 cell, bias-corrected rate, Gi z/p                    |
| `live_panel` (Mongo)  | collector         | cell×slot live ETA history                              |
| `forecast_daily.json` | daily forecaster  | per-cell dow intensity + CI                             |
| `forecast_eta.json`   | nightly collector | per-corridor 24h predicted severity                     |
| `causal_impact.json`  | causal panel      | β, CI, design, placebo                                  |
| `online_state.json`   | collector         | per-cell Gamma `(s,r)` + drift flag                     |
| `evaluation.json`     | evaluate          | every metric in [§13](#13-c6-proper-evaluation-metrics) |



| New endpoint                      | Returns                                   |
| --------------------------------- | ----------------------------------------- |
| `GET /api/live/pic`               | live PIC ranking (recomputed each cycle)  |
| `GET /api/live/risk?slot=`        | live per-cell risk surface (C1)           |
| `GET /api/forecast/eta?zone=`     | tomorrow's 24h predicted congestion curve |
| `GET /api/forecast/daily?zone=`   | next-day-by-dow violation intensity       |
| `GET /api/dispatch/plan?station=` | MCLP assignment + VRP-ordered live route  |
| `GET /api/causal/impact?zone=`    | attributable-delay β + CI                 |


---

## 20. References

**Parking & congestion** — Shoup (2006) *Cruising for Parking* (8–74% of downtown
traffic cruising, ~30% avg, ~8 min/search); Hampshire & Shoup (2018, 15% Stuttgart);
Schaller (2006, 28% Manhattan).

**Hotspot detection** — Getis & Ord (1992) and Ord & Getis (1995) Gi; Anselin
(1995) LISA / Local Moran's I; Kulldorff (1997) spatial scan.

**Bias / feedback loops** — Lum & Isaac (2016) *To Predict and Serve?*; Ensign et
al. (2018) *Runaway Feedback Loops in Predictive Policing* (arXiv 1706.09847);
Cameron & Trivedi, *Regression Analysis of Count Data* (Poisson/NB offset).

**Causal (observational)** — fixed-effects panels and difference-in-differences are
standard; report β with CI, parallel-trends, and placebos.

**Coverage / routing / RL** — Church & ReVelle (1974) Maximal Covering Location
Problem; Larson (1974) hypercube queueing; Repasky, Wang & Xie (2024) arXiv
2409.02246; Joe & Lau (ICAPS 2022 / IJCAI 2023). ⚠️ *"Delahoz & Celikel (2024)" is
unverifiable — treat as non-existent; do not cite it.*

**Forecasting (named as future work)** — Zhang, Zheng & Qi (2017) ST-ResNet; Li et
al. (2018) DCRNN; Wu et al. (2019) Graph WaveNet; Yu et al. (2018) STGCN.

**Online learning** — Gamma-Poisson conjugacy (Johnson, Ott & Dogucu, *Bayes
Rules!* ch. 5); Bifet & Gavaldà (2007) ADWIN; `River` streaming-ML library.

**Spatial indexing** — Uber H3 (res-10 ≈ 65.9 m edge); Woźniak & Szymański (2021)
Hex2Vec (optional).

**Mappls APIs (your `uploads/`)** — Distance-Time Matrix (`readme-10`), Predictive
ETA (`readme-16`), Isochrone / Driving-Range (`readme-22`), Trip Optimization
(`readme-12/13/14`), Snap-to-Road (`readme-25/15`), Nearby (`Readme-18`,
`readme-11`), Reverse Geocode (`Readme-21`), Place Details (`Readme-20`), Text
Search (`readme-0`), POI Along Route (`readme-17`), Aerial Distance (`readme-23`),
Address Analytics (`readme-24`), Web JS SDK v3.0 + Traffic Visualizer (`Web_JS-0`),
Heatmap (`heatMap-3`), GeoJSON (`geoJson-2`).

---

> **Bottom line.** On this dataset + the live Mappls APIs you already have docs for,
> **7 of 9 goals are fully buildable and 2 are buildable with an honest caveat.**
> The biggest unlock is the **Predictive ETA matrix** (`readme-16`): it turns "we
> can't forecast traffic" into "Mappls forecasts tomorrow's traffic for us, hour by
> hour, and we grade it against reality." Build [§18](#18-complete-ml-specification-what-to-build)
> in order and the solution becomes **evaluated and live**, not historical.

