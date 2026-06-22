# ClearLane — Phase 3

## Whitefield Regional Live Traffic, Congestion Severity & Parking-Induced-Congestion (PIC) Ranking

Phase 3 adds a **live, regional traffic layer** on top of the verified citywide
Phase 2 hotspot model. It selects a geographically validated set of high-confidence
Whitefield hotspots, maps them to **real Mappls road segments**, caches non-traffic
reference durations, polls traffic-adjusted Matrix ETA, computes **congestion
severity**, and produces a **live Whitefield PIC ranking** every poll cycle.

It does this **without** re-running Phase 2, **without** reading the raw ticket
data, and **without** ever claiming to directly detect an illegally parked vehicle.

```
CITYWIDE HISTORICAL COVERAGE : BENGALURU        (6,805 H3 cells, from Phase 2)
LIVE TRAFFIC COVERAGE        : WHITEFIELD DEMO REGION (20 primary cells)
```

> **Judge-facing claim.** "This location has high historical illegal-parking
> propensity **and** is experiencing elevated traffic delay right now, so it
> receives high inspection priority." Nothing more is claimed.

---

## 1. The core idea (one formula, no hidden weights)

```
PIC_h(t) = normalized_propensity_h           ×   congestion_severity_h(t)
           └─ Phase 2 citywide value ─┘           └─ live, this poll cycle ─┘
```

`congestion_severity = clip(1 − reference_duration / live_eta_duration, 0, 1)`
(equivalently `clip(1 − 1/TTI, 0, 1)`). Missing ETA or baseline → **null**, never
zero. Propensity is the **citywide** Phase 2 value, used as-is (never re-normalized
inside Whitefield) so Whitefield stays comparable to the rest of Bengaluru.

Reference checkpoints (all pass): `ref 100 / eta 100 → 0.00`, `100/150 → 0.3333`,
`100/200 → 0.50`, `100/400 → 0.75`; and `PIC(0.8, 0.5) = 0.40`.

---

## 2. End-to-end flow

```
Verified Phase 2 hotspots (latest completed full WARN run, checksum-verified)
   ↓  filter mode_police_station == WHITEFIELD
   ↓  keep eligible_for_corrected_ranking == true AND spatial_test_status == TESTED
   ↓  drop the explicitly-excluded Carmelaram outlier (8a6189276627fff)
   ↓  order by corrected_rank ↑, h3_res10 ↑  →  20 PRIMARY + 10 RESERVE
   ↓  build ONE real road segment per primary (geodesic endpoints → Route ADV →
   ↓     decode polyline (precision 5) → validate → keep best → A_TO_B & B_TO_A)
   ↓  cache non-traffic reference duration (Distance Matrix / Route ADV)
   ↓  poll Distance Matrix ETA every 15 min (only the ETA call repeats)
   ↓  congestion severity → directional max → PIC = propensity × severity
   ↓  live Whitefield PIC ranking + localized slowdown signal + confidence
```

---

## 3. Verified foundation it consumes

| Item | Value (resolved dynamically, not hardcoded) |
|---|---|
| Phase 2 run used | `20260622_132248_phase2` (latest completed verified full run) |
| Phase 2 status | `WARN` (allowed) |
| Phase 2 warnings propagated | `PARKING_CLASSIFICATION_DISCREPANCY`, `SPATIAL_GRAPH_DISCONNECTED`, `SPATIAL_ISLANDS_PRESENT` |
| Hotspot input | `data/processed/phase2_h3_hotspots.parquet` |
| Checksum match | ✅ true |
| Row-count match | ✅ 6,805 cells |
| Phase 1 run (lineage only) | `20260622_130216_phase1` |
| Raw ticket CSV opened | ❌ never |

Phase 3 **never** reads `data/raw/*`, `data/interim/violations_cleaned.csv`, or
`…violations_cleaned.parquet`. Lineage validation (`phase2_lineage_validation.json`)
enforces status, empty errors, allowed-warnings-only, checksum, row count,
required columns, valid H3 IDs, and `normalized_propensity ∈ [0,1]` before any
selection or API call.

---

## 4. Whitefield selection (matches reference exactly)

| Metric | Count |
|---|---|
| Whitefield historical H3 cells | **161** |
| …eligible | **47** |
| …eligible **and** spatially TESTED | **40** |
| …explicitly excluded (Carmelaram) | **1** |
| Eligible TESTED after exclusions | **39** |
| **PRIMARY** selected | **20** |
| **RESERVE** selected | **10** |

The 20 primary H3 cells are derived from station + eligibility + spatial status +
explicit exclusions + `corrected_rank` + deterministic `h3_res10` tie-break — the
known expected list is a **regression test only** (`test_real_phase2_selection.py`),
never embedded in production logic. `mode_police_station` is treated as the
*dominant ticket station of a cell*, **not** an official jurisdiction polygon; a
bbox `(12.93–13.00, 77.70–77.77)` is a demonstration safety boundary only.

---

## 5. Mappls capability boundary (honest)

| Available (verified) | Not allocated (must not block) |
|---|---|
| Static REST auth, Route ADV, Route ETA | Route Traffic API |
| Distance Matrix, Distance Matrix ETA | Distance Matrix Traffic API |
| Multi-location Matrix ETA batching | Predictive Traffic API |
| Reverse Geocode, Geocode, Snap to Road | Native live-traffic tiles |

```
selected live source     : distance_matrix_eta   (fallback: route_eta)
selected reference source : distance_matrix       (fallback: route_adv)
numeric_live_traffic_available = any(matrix_eta, route_eta) = true
native tiles / predictive unavailable → WARN, never BLOCKED
```

An HTTP-200 body of `Api Access Denied` or `Invalid Token` is treated as
**authentication/permission failure** regardless of status code, and such
responses are **never retried**.

---

## 6. Credit-aware execution & budgets

Only **20 primary + 10 reserve** cells ever touch Mappls — never all 6,805
Bengaluru cells, never all 161 Whitefield cells. One-time calls (Snap, Route ADV,
Matrix non-traffic, Reverse Geocode) run during preparation; **only Distance
Matrix ETA repeats** every 15 minutes. Every request is **counted before
execution**; if the next request would exceed any budget the caller gets
`BLOCKED_API_BUDGET` and the request is not issued.

```yaml
maximum_prepare_requests_per_run: 150
maximum_requests_per_poll_cycle:    8
maximum_route_eta_fallbacks_per_cycle: 3
maximum_requests_per_day:          400
```

Quota balance is unknown (Mappls exposes no rate-limit headers) — Phase 3 **never
invents remaining-credit numbers**. Matrix accounting is tracked explicitly
(`matrix_cells_returned`, `monitored_pairs_used`, `unused_matrix_cells`) because
charging behaviour is unknown; only the explicit within-segment cells
(`A→B`, `B→A`) are interpreted as monitored pairs — cross-matrix cells are counted
as unused, never mistaken for a segment.

---

## 7. Operating modes (CLI)

```bash
python scripts/run_phase3.py --mode lineage-only        # no Mappls calls
python scripts/run_phase3.py --mode select-candidates    # no live calls
python scripts/run_phase3.py --mode capability-probe     # one small probe segment
python scripts/run_phase3.py --mode prepare-segments --limit 5    # credit-safe smoke
python scripts/run_phase3.py --mode prepare-segments --limit 20   # full prep
python scripts/run_phase3.py --mode poll-once --limit 5           # credit-safe poll
python scripts/run_phase3.py --mode poll-once --limit 20          # full poll
python scripts/run_phase3.py --mode collect --interval-minutes 15 --cycles 8 --limit 20
python scripts/run_phase3.py --mode replay --fixture-dir tests/phase3/fixtures/mappls
```

`collect` is **finite** (`--cycles`) — there is no unavoidable infinite foreground
loop. `replay` reads sanitized fixtures, forces `data_mode = REPLAY`, and never
labels data live or updates the production baseline.

---

## 8. Status model

- **PASS** — lineage ✓, selection ✓, valid segments + numeric ETA + valid
  observations + usable baselines + congestion + PIC + reconciling outputs + no
  secret leak + tests + verifier.
- **WARN** — allowed degradations (provisional baselines, cold start, partial
  coverage, one-direction-only, reverse-geocode/snap/native-tile/predictive
  unavailable, propagated Phase 2 warnings, route-ETA fallback used).
- **BLOCKED** — `MAPPLS_REST_KEY_MISSING`, `MAPPLS_AUTHENTICATION_DENIED`,
  `NO_NUMERIC_ETA_SOURCE_AVAILABLE`, `API_BUDGET_EXCEEDED`,
  `ALL_PRIMARY_SEGMENTS_UNRESOLVED`.
- **REPLAY_PASS** — replay path completed (separate from live).
- **FAIL** — checksum mismatch, wrong run, missing columns, raw access,
  nondeterministic selection, Carmelaram leaking into primary/reserve, reversed
  coordinates, invalid geometry accepted, provider error parsed as valid ETA,
  reference/ETA mismatch, missing → zero congestion, PIC out of [0,1], stale or
  mixed-cycle rankings, replay labelled LIVE, silent budget overflow, credential
  leak, missing outputs, tests fail.

---

## 9. What was built

**Package** — `src/clearlane/phase3/` (31 modules): `common` (paths, IST time,
credential redaction), `lineage`, `schema` (explicit adapter), `candidate_selection`,
`region_validation`, `geometry_utils` (geodesic + polyline encode/decode @ prec 5),
`segment_builder`, `segment_validation`, `mappls_auth`, `mappls_client`
(HTTP + replay transport + retry + budget + redaction), six adapters
(`route_adv`, `route_eta`, `matrix_normal`, `matrix_eta`, `snap_to_road`,
`reverse_geocode`), `response_parsers`, `capability_probe`, `api_budget`,
`retry_policy`, `polling`, `observation_store` (partitioned + idempotent),
`baselines`, `congestion`, `localized_anomaly`, `pic`, `confidence`, `exports`,
`reporting`, `runner`.

**Scripts** — `scripts/run_phase3.py`, `scripts/verify_phase3.py`,
`scripts/inspect_phase3.py`, `scripts/build_phase3_dashboard.py`.

**Config / deps** — `configs/phase3.yaml`, `requirements-phase3.txt`
(`httpx`, `python-dotenv`, `tenacity`, `polyline` on top of Phase 2 deps),
`.env.example` (adds `MAPPLS_REST_KEY` + optional OAuth fields).

**Tests** — `tests/phase3/` (19 test modules, **108 tests**): lineage, candidate
selection, real-data selection match, region validation, segment builder, geometry
decoding (real fixture, precision 5, lng/lat order, wrong-precision rejection),
auth, capability probe, response parsers, api budget, retry policy, observation
store, baselines, congestion, pic, localized anomaly, replay, output contract,
no-secret-leakage. Sanitized Mappls replay fixtures live in
`tests/phase3/fixtures/mappls/`.

**Frontend** — `frontend.phase3/` — a **new, standalone** Leaflet dashboard
(no build step, no npm, CDN only). It reads the generated Phase 3 GeoJSON/JSON,
maps PIC cells coloured by severity and sized by PIC, lists the live ranking,
shows a LIVE/REPLAY badge, and carries the honesty panel. The existing
`frontend.v3/` and all backend code are **untouched**.

---

## 10. Outputs produced

```
data/interim/  phase3_whitefield_candidates.parquet
               phase3_whitefield_road_segments.parquet
data/processed/phase3_whitefield_candidates.csv
               phase3_whitefield_segment_catalog.csv / .geojson
               phase3_whitefield_live_congestion.parquet / .csv
               phase3_whitefield_live_pic.parquet / .csv / .json / .geojson
               phase3_citywide_historical_layer_manifest.json   (live = WHITEFIELD_DEMO_ONLY)
data/live/     mappls_traffic_observations/observation_date=YYYY-MM-DD/part.parquet
               phase3_whitefield_segment_baselines.parquet
               phase3_whitefield_latest_valid_observations.parquet
artifacts/phase3/<RUN_ID>/reports/   (20 reports incl. phase3_final_report.json)
artifacts/phase3/<RUN_ID>/manifest.json
```

The final report aggregates real values (lineage, coverage, candidate selection,
segments, Mappls, API usage, poll cycle, baselines, congestion, PIC, localized
anomaly, warnings, errors) — not just output paths.

---

## 11. Honesty guarantees (enforced in code + tests)

- Allowed language: *live congestion measurement, live parking-related risk
  inference, live PIC priority, localized slowdown signal, recommended inspection
  priority.*
- Forbidden (never emitted): *illegally parked vehicle detected, Mappls confirmed
  illegal parking, parking definitely caused this traffic.*
- Live coverage is **Whitefield only**; `live_citywide_claimed = false`.
- Credentials are redacted from every log/report/exception/output; a
  no-secret-leakage test scans all generated artifacts for known sample secrets.
- Localized slowdown is a **signal**, requiring ≥2 valid monitored ring-1
  neighbours — never "proof of illegal parking".
- Confidence fields are reported **separately** and never multiplied into PIC.

---

## 12. Test status

```
tests/phase1 + tests/phase2 : 57 passed   (unchanged)
tests/phase3                : 108 passed
total                       : 165 passed
verifier                    : PASS (latest run, REPLAY_PASS)
```

See `RUN_COMMANDS.md` for the exact commands to reproduce everything (including the
live 15-minute collection command) yourself.
