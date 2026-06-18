# ClearLane — Methodology & Honesty Statement

This is the judge-facing writeup. Every claim below is either computed from the
provided dataset or explicitly labelled an assumption. Nothing is fabricated.

---

## 1. What we claim — and what we do not

**We do NOT measure congestion, traffic flow, speed, or delay.** The dataset has
none. It is 298,450 parking-violation tickets (9 Nov 2023 → 8 Apr 2024; the
filename "jan to may" is a vendor mislabel). Critically, **ticket *times* reflect
officer shifts, not traffic** — so deriving deployment times from raw ticket times
would be reproducing the enforcement artifact, not measuring demand.

**We DO deliver:**
1. Bias-corrected ranking of chronic, structural obstruction zones.
2. The enforcement-timing gap (an enforcement-**coverage** gap vs known peaks).
3. Habitual-offender vs transient classification.
4. Enforcement responsiveness (working vs needs-structural-fix).
5. A validated next-month forecaster on a real observed future quantity.

---

## 2. Data cleaning (`01_clean.py`, see `outputs/reports/cleaning_summary.txt`)

- Drop `validation_status ∈ {rejected, duplicate}` (−50,074).
- Drop rows with no parking-relevant violation type (pure non-parking noise).
- Drop rows outside the Bengaluru bbox / missing coords (−2).
- Keep `approved` + NaN + `created1` + `processing`; tag confidence `high`
  (approved or SCITA-sent) vs `medium`.
- Never engineer features from the 100%-empty columns
  (`description`, `closed_datetime`, `action_taken_timestamp`).
- Timestamps are stored UTC → converted to IST (UTC+5:30); all times are IST.

**Result: 248,374 clean rows (16.8% removed).**

## 3. Superzones (`02_superzones.py`)

Occupied 100 m buckets (`round(lat,3)`) are merged into ~500 m operational
superzones by snapping to a deterministic **0.0045° grid**. We use a grid, not
DBSCAN: haversine DBSCAN density-chains dense commercial corridors (KR Market,
Chickpet) into a single mega-blob, destroying dispatchable meaning. **1,555 zones.**

## 4. The three pillars (`03_scores.py`)

All pillars are **percentile-normalized** to 0–100 (robust to outliers, unlike
min-max — one mega-cell shouldn't crush the scale).

| Pillar | What | From |
|---|---|---|
| **A — Obstruction Pressure** | Σ(severity × vehicle-footprint × confidence) | weighted tickets |
| **B — Structural Recurrence** | active days × consistency × monthly spread | recurrence |
| **C — Emergence** | recent-vs-baseline growth, gated by min volume | 2024-03 vs Nov–Feb |

**Operational Priority = 0.50·A + 0.30·B + 0.20·C** → P1 ≥80, P2 ≥60, P3 ≥40, else P4.
`chronic` = recurrence ≥ 60.

### Defensible weight tables (`config.py`)

- **Severity (0–1)** maps to what blocks a moving lane: MAIN ROAD 1.0 · ROAD
  CROSSING / TRAFFIC LIGHT / ZEBRA 0.9 · DOUBLE PARKING 0.85 · OPPOSITE 0.8 ·
  BUS-STOP/SCHOOL/HOSPITAL 0.7 · WRONG PARKING 0.5 · NO PARKING 0.45 · FOOTPATH
  0.25 · non-parking 0.0.
- **Vehicle footprint (0–1):** PRIVATE BUS/HTV 1.0 · LGV/GOODS/VAN 0.8 ·
  CAR/MAXI-CAB 0.6 · PASSENGER AUTO 0.45 · two-wheelers 0.25.
- **Confidence:** high 1.0 · medium 0.7.

These are never defended by assertion — see §7 (sensitivity).

## 5. Advanced intelligence (`04_advanced.py`)

- **7.1 Enforcement-exposure bias correction.** `exposure = distinct officers ×
  distinct active days`; `bias_adjusted = pressure / exposure^0.5`. We report both
  the raw and bias-adjusted rank and flag **under-recognized** zones (bad relative
  to how little they're patrolled). Strictly zone-level — we never profile officers.
- **7.2 Habitual offenders.** Repeat vehicle = ticketed ≥3× anywhere or ≥2× in a
  zone. Zones with ≥30% repeat-share are **habitual** (structural parking demand →
  infrastructure) vs **transient** (enforcement presence works).
  Headline: **16.7% of tickets from 4.6% of vehicles.**
- **7.3 Responsiveness.** Monthly pressure trend Nov→Mar → *responding* (declining),
  *resistant* (flat/rising despite ticketing → escalate to structural fix), *stable*.
- **7.4 Intervention engine.** Concrete action per P1/P2 zone (towing readiness /
  no-parking infrastructure / corridor patrol / fixed board / evening sweep).
- **7.5 Typology.** KMeans on each zone's temporal × composition fingerprint
  (k chosen by silhouette), labelled interpretably; plus a weekday×hour fingerprint.
- **7.6 Carriageway Impact Index (CII).** A **modeled flow-impact proxy** that
  answers "quantify the impact on traffic flow" *without* claiming to measure
  congestion. `flow_impact = percentile(pressure × context_multiplier)`, where the
  bounded multiplier (clip 0.8–1.5) blends three **static, auditable** road-context
  signals: **junction criticality** (share of a zone's tickets at named BTP
  junctions — 45% of tickets carry one), **road class** (ring-road/arterial/
  main-road/commercial/local, parsed from the address), and **demand proximity**
  (distance to public Namma Metro / commercial-hub coordinates in
  `ml/pipeline/anchors.py`). Validated like everything else — under ±20% on the
  J/R/D blend the top-20 is **99.6%** stable, yet **22/50** flow-impact zones
  diverge from the pure-pressure ranking (e.g. Elite Junction: strategic #37 →
  flow-impact #1). It is a proxy for *how much a block here disrupts movement*,
  built from physical context — **never** a measurement of speed/delay/congestion.

## 6. Forecaster (`05_forecaster.py`)

- **Features:** each zone's Nov–Jan signals (pressure, recurrence, mix, repeat
  share, exposure, trend, typology, junction flag).
- **Target:** that zone's **Feb–Mar obstruction pressure** — a real, observed
  future quantity. This is why R²/precision are *legitimate* here; there is no
  fabricated congestion label.
- **Model:** LightGBM. Held-out **R² 0.76, Spearman 0.78, top-20 precision 0.85.**
- **SHAP:** top drivers are recurrence (active days), repeat-offender share, and
  ticket volume — a clean, intuitive story.

Framed as: *forecasts which zones stay / become high-obstruction next month* —
never as congestion prediction.

## 7. Validation = credibility (`07_validation.py`)

- **Sensitivity:** 40 configs, ±20% on the blend and the severity/vehicle tables.
  Top-20 overlap **80–100%**, top-50 Spearman **0.96**. The ranking is robust — the
  weights are not arbitrary. (Live widget in the dashboard.)
- **Persistence backtest:** rank on Nov–Jan, test Feb–Apr. Spearman **0.80**,
  top-quartile persistence **80%**. Hotspots are structural, not noise.

## 8. The timing gap (`06_timing_gap.py`)

Enforcement peaks at **10:00**; the 17:00–21:00 evening window (an assumption from
domain knowledge) holds only **0.163%** of tickets. **515 P1/P2 zones** are evening
blind spots. The morning (8–11) and evening (5–9pm) congestion windows are stated
as assumptions, never measured.

**Coverage (ROI headline):** deploying to the top-20 *priority* zones of 1,555
covers ≈**16.8%** of all weighted obstruction evidence (top-50 ≈40%). We rank by
deployment priority and measure *evidence-coverage* — never a counterfactual
"clearing this cuts congestion by X%".

## 8b. Operational serving features (deterministic, additive)

- **Today's emergency board.** A live, weekday + hour-aware ranking computed at
  request time from each zone's historical day/hour enforcement pattern
  (`map_payload` `dow` + `hourly`), the next-month forecast, the strategic priority,
  and any live citizen reports. It tells officers *where to go now, top-down*. It is
  **expected enforcement-demand, NOT a congestion prediction** — the underlying
  activity is recorded ticket times (officer shifts), labelled as such in the UI.
- **Repeat-vehicle tracing** (`offenders.json`). The most-ticketed vehicles, each
  with a time-wise log (timeline, peak hour, zones, mini-map). `vehicle_number` is
  anonymized and stable, so this is **vehicle-level only — no real identities** (and,
  as everywhere, never officer-level). Single-zone repeaters are surfaced as a
  structural-demand signal (needs infrastructure, not just repeat tickets).

## 9. Limitations (stated plainly)

- No flow/speed/delay data → no congestion measurement; the evening gap is a
  *coverage* gap vs assumed peaks.
- Ticket times are an enforcement artifact, not demand.
- Five months (one partial) limits long-horizon seasonality.
- `vehicle_number` is anonymized but stable, enabling repeat-offender analysis at
  the vehicle level only — no real identities.
- Officer-level signals are aggregated to zones for the bias correction; we never
  rank or profile individual officers.

---

*All numbers above are reproduced by `cd ml/pipeline && python run_all.py`, which
prints a self-check table against these verified targets and exits non-zero if any
metric drifts more than 15%.*
