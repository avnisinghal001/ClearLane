# AGENTS.md — ML & Data Processing (`ml/`) — v1, DEPLOYED

> Scope: the data cleaning, feature engineering, scoring, modeling, and artifact
> generation pipeline. Read the root `AGENTS.md` first — especially the **honesty
> contract** and **verified dataset ground truth**, which this layer enforces.
>
> **This is the v1 (zone-based) pipeline and it is the one currently deployed** —
> its `data/processed/*.json` artifacts are what `api/clearlane/main.py` and the
> `frontend/` dashboard serve. The newer H3 cell-based rebuild lives in `ml.v3/`
> (see `ml.v3/AGENTS.md`); it writes to `data/processed/v3/` and does **not** touch
> these artifacts. Edits here affect production; edits in `ml.v3/` do not (yet).

## Canonical location

**`ml/pipeline/` is the one and only pipeline.** Run everything from there:

```bash
cd ml/pipeline && python run_all.py            # full run + self-check + demo bundle
cd ml/pipeline && python run_all.py --no-demo  # skip copying into frontend/public/demo
```

The old `ml/scripts/` (a.k.a. `legacy_scripts/`) carried **wrong framing** and has
been **removed**. Do not recreate it. If you ever resurrect old logic from git
history, port it carefully under the honesty rules — don't copy blindly.

## Design principles

1. **`config.py` is the single source of truth.** Every verified fact, weight,
   threshold, window, and random seed lives there. Reasons:
   - the sensitivity analysis (`07_validation.py`) perturbs these constants
     programmatically — they must be in one place;
   - a judge can audit every assumption in one file;
   - nothing "magic" is hidden inside a stage.
   Never hard-code a tunable constant in a stage file.
2. **Deterministic & precomputed.** Fixed random seeds everywhere. The backend
   never runs models — it serves what this pipeline writes. Re-running must
   reproduce the same numbers.
3. **Honesty guardrails are enforced in code**, not just docs. Each stage's
   docstring states its guardrail and its self-check target. Keep that pattern.
4. **Idempotent stages.** Stages 04 and 06 drop their own columns before re-adding
   them, so a standalone re-run doesn't collide. Preserve this when editing.
5. **Pure helpers.** `utils.py` holds only pure functions (IST conversion, JSON
   parsing, severity lookup, geo-bucketing, percentile norm, JSON-safe
   serialization). Every constant it uses comes from `config.py`.

## The 8 stages (run order = `run_all.STAGES`)

Each file exposes a `run()` function. `run_all.py` executes them in order, then
prints a self-check table and bundles the demo artifacts.

| Stage | File | Does | Key outputs |
|------|------|------|-------------|
| 01 | `01_clean.py` | load → IST-convert → parse violations → filter (drop rejected/duplicate + non-parking) → geo-bucket. Logs every filter step. | `events_clean.parquet/.csv`, `cleaning_summary.txt` |
| 02 | `02_superzones.py` | cluster occupied 100m buckets into ~500m operational superzones via deterministic grid-merge (snap to 0.0045° cell). | `superzones.parquet` |
| 03 | `03_scores.py` | the three pillars + Operational Priority + tiers. | `zone_scores.parquet` |
| 04 | `04_advanced.py` | bias correction, habitual offenders, responsiveness, intervention recs, typology (KMeans) + fingerprints, **Carriageway Impact Index** (flow-impact proxy from junction/road-class/demand context, uses `anchors.py`). | adds cols + `typology*.json`, `fingerprints.json`, `offender_stat.json` |
| 05 | `05_forecaster.py` | next-month obstruction-pressure forecaster (LightGBM) + SHAP. | `forecast.json`, `forecaster_metrics.json/.txt` |
| 06 | `06_timing_gap.py` | enforcement-timing gap, evening blind spots, coverage curve, station command. | `timing_gap.json`, `coverage_curve.json`, `stations.json` |
| 07 | `07_validation.py` | sensitivity (±20%, ~40 configs) + persistence backtest. | `validation.json`, `validation.txt` |
| 08 | `08_payload.py` | build serving payloads + KPIs + optional LLM briefings + replay/hourly/weekday data + repeat-vehicle logs. | `map_payload.json` (now incl. `dow`, `forecast_score` for the Today board), `zones_detail.json`, `evidence_points.json`, `search_index.json`, `emerging.json`, `briefings.json`, `replay_frames.json`, `offenders.json`, `daily.json` (per-zone P1–P3 + station + city daily series for the Time Lens & staffing) |

## Scoring model (stage 03) — memorize this

```
Pillar A  Obstruction Pressure  = Σ(severity × footprint × confidence)  → percentile
Pillar B  Structural Recurrence = f(active_days, months, regularity)    → percentile
Pillar C  Emergence             = recent-vs-baseline growth (gated)     → percentile

Operational Priority = 0.50·A + 0.30·B + 0.20·C        (PRIORITY_WEIGHTS)
Tiers: P1 ≥ 80, P2 ≥ 60, P3 ≥ 40, else P4             (TIER_THRESHOLDS)
```

- All pillars are **percentile-normalized** (robust to outliers; stated in
  methodology). Severity table = carriageway-blocking weight; vehicle table =
  physical lane footprint. Both justified in `docs/METHODOLOGY.md`.
- **Coverage curve ranks by PRIORITY first, then sum of `pressure_raw`** — not by
  pressure alone. Ranking by raw pressure gives a misleadingly high top-1 because
  one dense 500m KR-Market/Safina cell holds ~5% of all pressure. Keep this.
- Advanced intel (stage 04): bias-corrected pressure =
  `pressure / exposure**EXPOSURE_ALPHA` (alpha 0.5), exposure = distinct officers
  × distinct active days, **zone-level only — never per-officer**.
- **Carriageway Impact Index (stage 04):** `flow_impact = percentile(pressure_raw
  × context_multiplier)`, multiplier = `clip(lo + (wJ·J + wR·R + wD·D)·(hi-lo))`
  from junction criticality / road class / demand proximity (`CII_*` in config,
  static coords in `anchors.py`). It is a **modeled proxy, NOT measured
  congestion** — keep that label in every emitter and UI string. It rides on
  `map_payload.json`/`zones_detail.json` (no separate artifact) and never alters
  `priority`, tiers, or the self-check targets.

## Forecaster framing (stage 05)

- Features: each zone's **Nov–Jan** signals. Target: that zone's **Feb–Mar
  observed obstruction pressure**. Model: LightGBM. Metrics: R², Spearman, top-K
  precision. Explainability: SHAP (falls back to gain importance).
- Frame it as "forecasts which zones stay/become high-obstruction next month,
  validated on held-out months." **Never** as congestion prediction.

## Self-check (the regression gate)

`run_all.py` compares 13 headline metrics against `config.SELF_CHECK_TARGETS` and
flags any off by more than `SELF_CHECK_TOLERANCE` (15%). It **exits non-zero** if
anything flags. Treat a flag as a real regression to investigate and explain — do
not loosen the tolerance or edit the targets to make it pass. Current run sits
within ±15% on all 13 (see root README's table).

## When you change something

- Touching weights/thresholds/windows → edit **`config.py` only**, re-run, confirm
  self-check still passes, and update `docs/METHODOLOGY.md` if rationale changes.
- Adding/altering an artifact field → it's almost always emitted in `08_payload.py`.
  Then update the backend route + frontend reader, and re-run (re-bundles demo).
- The pipeline runs in ~11s. Always run end-to-end before declaring done.

## Dependencies

Python deps are in the repo-root `requirements.txt` (pandas, numpy, scikit-learn,
lightgbm, scipy, pyarrow, etc.). Run inside the repo venv.
