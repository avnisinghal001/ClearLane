# ClearLane Phase 1 and Phase 2 Runbook

This repository now has two verified pipeline phases:

- **Phase 1:** trusted data foundation, cleaning, profiling, row reconciliation, and canonical cleaned dataset generation.
- **Phase 2:** spatial H3 hotspot intelligence, exposure correction, Gamma-Poisson smoothing, count-model diagnostics, spatial significance, stability checks, and output-contract verification.

Run commands from:

```bash
cd /Users/avnisinghal001/Documents/ClearLane/ClearLane
```

## Environment Setup

Use the project virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-phase2.txt
```

`requirements-phase2.txt` includes Phase 1 requirements, so this installs both phases.

## Run Full Phase 1

Phase 1 reads only the configured raw ticket CSV from `configs/phase1.yaml`.

It writes the canonical cleaned dataset:

```text
data/interim/violations_cleaned.parquet
data/interim/violations_cleaned.csv
data/quarantine/*.csv
artifacts/phase1/<RUN_ID>/
```

Run:

```bash
source .venv/bin/activate
python scripts/run_phase1.py
python scripts/verify_phase1.py
```

Expected successful verifier output:

```text
PASS: Phase 1 latest run <RUN_ID> status=PASS
```

Important Phase 1 checks:

- raw file SHA-256 before/after
- schema validation
- coordinate parsing
- datetime parsing
- duplicate/quarantine handling
- row reconciliation
- cleaned parquet/csv checksums
- data dictionary
- document-claim comparison

## Run Full Phase 2

Phase 2 consumes only:

```text
data/interim/violations_cleaned.parquet
```

It must not read the raw CSV or cleaned CSV fallback.

Phase 2 resolves the latest valid Phase 1 `PASS` run, verifies the Phase 1 checksum and accepted-row count, then runs the spatial pipeline.

Run:

```bash
source .venv/bin/activate
python scripts/run_phase2.py
python scripts/verify_phase2.py
```

Expected successful verifier output:

```text
PASS: Phase 2 latest run <RUN_ID> status=WARN
```

`WARN` is expected if only these structured warnings remain:

```text
PARKING_CLASSIFICATION_DISCREPANCY
SPATIAL_GRAPH_DISCONNECTED
SPATIAL_ISLANDS_PRESENT
```

Those are not silent failures:

- Phase 1 recomputes parking-related rows as `100.0%`, while the old project document said `97.3%`; Phase 2 records this discrepancy and does not filter records to reproduce the older number.
- The observed-ticket H3 graph is disconnected because only cells with observed tickets are included.
- Some H3 cells are spatial islands and are marked as insufficient for spatial tests instead of receiving fabricated p-values.

## Fast Phase 2 Lineage Check

Use this when you only want to validate Phase 1 handoff without generating all H3/model outputs:

```bash
source .venv/bin/activate
python scripts/run_phase2.py --lineage-only
python scripts/verify_phase2.py
```

## Run Automated Tests

Run all Phase 1 and Phase 2 tests:

```bash
source .venv/bin/activate
python -m pytest tests/phase1 tests/phase2
```

Optionally save a log:

```bash
python -m pytest tests/phase1 tests/phase2 | tee phase1_phase2_tests.log
```

Current expected result after the latest audit:

```text
56 passed
```

## Phase 2 Main Outputs

Generated tables:

```text
data/interim/phase2_ticket_h3_mapping.parquet
data/interim/phase2_h3_exposure.parquet
data/processed/phase2_h3_features.parquet
data/processed/phase2_h3_hotspots.parquet
data/processed/phase2_h3_hotspots.csv
data/processed/phase2_h3_hotspots.geojson
data/processed/raw_hotspot_rankings.csv
data/processed/corrected_hotspot_rankings.csv
data/processed/spatial_significance.csv
data/processed/police_station_hotspot_intelligence.csv
```

Run artifacts:

```text
artifacts/phase2/<RUN_ID>/manifest.json
artifacts/phase2/<RUN_ID>/reports/
```

Important reports include:

```text
phase2_lineage_validation.json
phase1_lineage_validation.json
input_population_report.json
phase1_parking_classification_reconciliation.json
h3_assignment_report.json
enforcement_exposure_report.json
gamma_poisson_report.json
poisson_model_report.json
negative_binomial_model_report.json
poisson_vs_negative_binomial.json
h3_neighbor_graph_report.json
spatial_significance_report.json
monthly_stability_report.json
temporal_holdout_validation.json
output_contract_report.json
phase2_final_report.json
```

## What We Fixed In Phase 2

The Phase 2 audit fixed these correctness issues:

- Phase 2 now resolves the latest valid Phase 1 `PASS` run instead of pinning an older run.
- Phase 2 lineage now records checksum match, row-count match, input path, input SHA-256, and `raw_csv_used=false`.
- Negative Binomial now estimates dispersion alpha from data using statsmodels discrete Negative Binomial with `offset=log(device_days)`.
- Poisson-vs-NB comparison now uses explicit log-likelihood-based BIC, not statsmodels deviance BIC.
- H3 disconnected components and islands are handled explicitly.
- Isolated cells do not receive fabricated Gi* p-values.
- Exposure is independently recomputed from ticket-level H3 mapping.
- Output-contract verification now checks all required tables and reports.
- Monthly stability and chronological holdout validation are generated from ticket-level records.
- No hardcoded benchmark result values are used as computed outputs.

## Latest Verified Reference

At the time this runbook was written, the latest verified complete run was:

```text
Phase 1: artifacts/phase1/20260621_223743_phase1
Phase 2: artifacts/phase2/20260622_003215_phase2
```

Key Phase 2 metrics from that run:

```text
input rows: 298445
production rows: 298445
unique H3 res-10 cells: 6805
eligible cells: 2707
connected components: 859
isolated cells: 433
NB alpha: 0.25985703733344223
preferred model: INCONCLUSIVE
```

## Notes

- Do not modify files in `data/raw/` when verifying these phases.
- Full Phase 1 and Phase 2 runs regenerate artifacts and overwrite current Phase 2 output tables in `data/interim/` and `data/processed/`.
- Some macOS sandbox environments print Arrow CPU-probing `sysctlbyname` messages. Those are environmental messages, not pipeline failures, as long as the scripts exit successfully and verifiers pass.
