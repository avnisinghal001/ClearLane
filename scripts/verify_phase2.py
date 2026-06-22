from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_ROOT_OUTPUTS = [
    "data/interim/phase2_ticket_h3_mapping.parquet",
    "data/interim/phase2_h3_exposure.parquet",
    "data/processed/phase2_h3_features.parquet",
    "data/processed/phase2_h3_hotspots.parquet",
    "data/processed/phase2_h3_hotspots.csv",
    "data/processed/phase2_h3_hotspots.geojson",
    "data/processed/raw_hotspot_rankings.csv",
    "data/processed/corrected_hotspot_rankings.csv",
    "data/processed/spatial_significance.csv",
    "data/processed/police_station_hotspot_intelligence.csv",
]

REQUIRED_REPORTS = [
    "phase1_lineage_validation.json",
    "phase2_lineage_validation.json",
    "phase1_parking_classification_reconciliation.json",
    "input_population_report.json",
    "h3_assignment_report.json",
    "h3_neighbor_report.json",
    "exposure_invariant_report.json",
    "enforcement_exposure_report.json",
    "raw_hotspot_concentration.json",
    "spatial_concentration.json",
    "count_distribution_report.json",
    "gamma_poisson_report.json",
    "gamma_poisson_spot_check.json",
    "prior_sensitivity_report.json",
    "gamma_poisson_prior_sensitivity.json",
    "rank_turnover_report.json",
    "raw_vs_corrected_rank_report.json",
    "h3_neighbor_graph_report.json",
    "h3_geometry_report.json",
    "spatial_significance_report.json",
    "local_moran_report.json",
    "superzone_report.json",
    "quality_weight_sensitivity_report.json",
    "monthly_stability_report.json",
    "temporal_holdout_validation.json",
    "count_model_overdispersion_report.json",
    "poisson_model_report.json",
    "negative_binomial_model_report.json",
    "count_model_comparison_report.json",
    "poisson_vs_negative_binomial.json",
    "poisson_model_summary.txt",
    "negative_binomial_summary.txt",
    "police_station_summary.json",
    "station_summary.csv",
    "station_summary_report.json",
    "phase2_audit_report.json",
    "output_contract_report.json",
    "phase2_final_report.json",
]


def latest_run() -> Path | None:
    base = ROOT / "artifacts" / "phase2"
    if not base.exists():
        return None
    runs = sorted([p for p in base.iterdir() if p.is_dir()], reverse=True)
    for run in runs:
        final_path = run / "reports" / "phase2_final_report.json"
        manifest_path = run / "manifest.json"
        if final_path.exists() and manifest_path.exists():
            return run
    return None


def main() -> int:
    run = latest_run()
    if run is None:
        print("FAIL: no artifacts/phase2/<RUN_ID> directory found")
        return 1

    missing = []
    for path in REQUIRED_ROOT_OUTPUTS:
        if not (ROOT / path).exists():
            missing.append(path)
    if not (run / "manifest.json").exists():
        missing.append(str((run / "manifest.json").relative_to(ROOT)))
    for report in REQUIRED_REPORTS:
        if not (run / "reports" / report).exists():
            missing.append(str((run / "reports" / report).relative_to(ROOT)))

    final_path = run / "reports" / "phase2_final_report.json"
    lineage_path = run / "reports" / "phase2_lineage_validation.json"
    final = json.loads(final_path.read_text(encoding="utf-8")) if final_path.exists() else {}
    lineage = json.loads(lineage_path.read_text(encoding="utf-8")) if lineage_path.exists() else {}

    if final.get("mode") == "lineage_only":
        required_for_lineage = [
            run / "manifest.json",
            run / "reports" / "phase2_lineage_validation.json",
            run / "reports" / "phase1_parking_classification_reconciliation.json",
            run / "reports" / "input_population_report.json",
            run / "reports" / "phase2_final_report.json",
        ]
        missing = [str(p.relative_to(ROOT)) for p in required_for_lineage if not p.exists()]

    if missing:
        print("FAIL: missing Phase 2 deliverables")
        for path in missing:
            print(f"  - {path}")
        return 1
    if final.get("status") not in {"PASS", "WARN"}:
        print(f"FAIL: final status is {final.get('status')}")
        return 1
    if lineage.get("status") != "PASS":
        print(f"FAIL: lineage status is {lineage.get('status')}")
        return 1
    if lineage.get("forbidden_inputs_used"):
        print("FAIL: forbidden raw/old inputs were used")
        return 1
    if lineage.get("raw_csv_used"):
        print("FAIL: raw CSV was used by Phase 2")
        return 1
    if lineage.get("checksum_match") is not True:
        print("FAIL: Phase 2 input checksum did not match Phase 1")
        return 1
    if lineage.get("row_count_match") is not True:
        print("FAIL: Phase 2 input row count did not match Phase 1")
        return 1

    contract_path = run / "reports" / "output_contract_report.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8")) if contract_path.exists() else {}
    if contract.get("status") != "PASS":
        print("FAIL: output contract incomplete")
        for path in contract.get("missing", []):
            print(f"  - {path}")
        return 1

    print(f"PASS: Phase 2 latest run {run.name} status={final.get('status')}")
    print(f"Artifacts: {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
