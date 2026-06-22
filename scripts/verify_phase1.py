from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_ROOT_OUTPUTS = [
    "data/interim/violations_cleaned.parquet",
    "data/interim/violations_cleaned.csv",
    "data/quarantine/invalid_coordinates.csv",
    "data/quarantine/invalid_datetimes.csv",
    "data/quarantine/conflicting_duplicate_ids.csv",
    "data/quarantine/missing_critical_fields.csv",
    "data/quarantine/all_quarantined_rows.csv",
]

REQUIRED_REPORTS = [
    "environment_report.json",
    "raw_profile.json",
    "raw_schema.csv",
    "raw_null_report.csv",
    "raw_unique_counts.csv",
    "schema_validation.csv",
    "coordinate_report.json",
    "datetime_report.json",
    "timestamp_consistency_report.csv",
    "category_normalization_report.csv",
    "violation_label_dictionary.csv",
    "unmapped_violation_labels.csv",
    "unparsed_offence_codes.csv",
    "duplicate_report.json",
    "cleaning_report.json",
    "row_reconciliation.json",
    "cleaned_profile.json",
    "data_dictionary.csv",
    "repeat_offender_summary.json",
    "validation_summary.json",
    "temporal_artifact_report.json",
    "capability_limitations.csv",
    "document_claims_comparison.csv",
    "phase1_final_report.json",
]


def latest_run() -> Path | None:
    root = ROOT / "artifacts" / "phase1"
    if not root.exists():
        return None
    runs = sorted([p for p in root.iterdir() if p.is_dir()])
    return runs[-1] if runs else None


def main() -> int:
    missing = [p for p in REQUIRED_ROOT_OUTPUTS if not (ROOT / p).exists()]
    run = latest_run()
    if run is None:
        print("FAIL: no artifacts/phase1/<RUN_ID> directory found")
        return 1
    manifest = run / "manifest.json"
    if not manifest.exists():
        missing.append(str(manifest.relative_to(ROOT)))
        data = {}
    else:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    for name in REQUIRED_REPORTS:
        if not (run / "reports" / name).exists():
            missing.append(str((run / "reports" / name).relative_to(ROOT)))

    final_path = run / "reports" / "phase1_final_report.json"
    final = json.loads(final_path.read_text(encoding="utf-8")) if final_path.exists() else {}
    recon_path = run / "reports" / "row_reconciliation.json"
    recon = json.loads(recon_path.read_text(encoding="utf-8")) if recon_path.exists() else {}

    if missing:
        print("FAIL: missing Phase 1 deliverables")
        for p in missing:
            print(f"  - {p}")
        return 1
    if not data.get("raw_file_unchanged"):
        print("FAIL: raw file changed during Phase 1")
        return 1
    if not recon.get("passed"):
        print("FAIL: row reconciliation did not pass")
        return 1
    if final.get("status") not in {"PASS", "WARN"}:
        print(f"FAIL: final status is {final.get('status')}")
        return 1

    print(f"PASS: Phase 1 latest run {run.name} status={final.get('status')}")
    print(f"Artifacts: {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

