from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from clearlane.phase2.audit import output_contract_report, phase2_audit_report
from clearlane.phase2.exposure import independent_exposure_check
from clearlane.phase2.lineage import load_config, resolve_phase1_artifact_dir, validate_phase1_lineage
from clearlane.phase2.temporal_validation import chronological_holdout_validation


ROOT = Path(__file__).resolve().parents[2]


def test_latest_phase1_resolution_uses_newest_valid_pass_run():
    config = load_config("configs/phase2.yaml", ROOT)
    artifact = resolve_phase1_artifact_dir(config, ROOT)
    valid_runs = []
    for final_path in (ROOT / "artifacts" / "phase1").glob("*/reports/phase1_final_report.json"):
        run_dir = final_path.parents[1]
        recon_path = run_dir / "reports" / "row_reconciliation.json"
        manifest_path = run_dir / "manifest.json"
        if not (recon_path.exists() and manifest_path.exists()):
            continue
        final = json.loads(final_path.read_text(encoding="utf-8"))
        recon = json.loads(recon_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (final.get("status") or manifest.get("status")) == "PASS" and recon.get("passed") is True:
            valid_runs.append(run_dir)
    assert valid_runs
    assert artifact == sorted(valid_runs)[-1]
    lineage = validate_phase1_lineage(config, ROOT)
    assert lineage.phase1_run_id == artifact.name
    assert lineage.checksum_match is True
    assert lineage.row_count_match is True
    assert lineage.raw_csv_used is False


def test_phase2_audit_report_uses_allowed_status_values():
    report = phase2_audit_report(local_moran_enabled=False)
    allowed = set(report["allowed_status_values"])
    assert set(report["requirements"].values()).issubset(allowed)
    assert report["requirements"]["Local Moran's I, when enabled"] == "NOT_APPLICABLE"


def test_temporal_holdout_uses_chronological_split_without_late_period_in_train(sample_phase2_df):
    mapping = sample_phase2_df.copy()
    mapping["h3_res10"] = ["a", "a", "b"]
    mapping["created_date"] = ["2024-01-01", "2024-01-02", "2024-02-01"]
    report = chronological_holdout_validation(
        mapping,
        minimum_device_days=1,
        prior_strength=2.0,
        top_k_values=[1],
        train_fraction=0.67,
    )
    assert report["status"] == "PASS"
    assert report["train_date_max_exclusive"] == report["test_date_min_inclusive"]
    assert report["train_rows"] < len(mapping)
    assert "early period" in report["temporal_leakage_prevention"]


def test_no_hardcoded_benchmark_outputs_in_phase2_source():
    forbidden = ["2707", "743.5", "18 Top-50", "64% Top-50", "169 cells contain 50%"]
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "clearlane" / "phase2").glob("*.py"))
    for token in forbidden:
        assert token not in source


def test_real_data_exposure_recomputes_from_mapping_when_outputs_exist():
    mapping_path = ROOT / "data" / "interim" / "phase2_ticket_h3_mapping.parquet"
    exposure_path = ROOT / "data" / "interim" / "phase2_h3_exposure.parquet"
    if not (mapping_path.exists() and exposure_path.exists()):
        pytest.skip("Full Phase 2 outputs have not been generated yet.")
    mapping = pd.read_parquet(mapping_path)
    exposure = pd.read_parquet(exposure_path)
    if "active_dates" not in exposure.columns:
        pytest.skip("Existing Phase 2 exposure output predates active_dates validation.")
    report = independent_exposure_check(mapping, exposure, minimum_device_days=5)
    assert report["status"] == "PASS"


def test_output_contract_report_detects_missing_files(tmp_path):
    config = {
        "outputs": {
            "ticket_h3_mapping": "data/interim/phase2_ticket_h3_mapping.parquet",
            "h3_exposure": "data/interim/phase2_h3_exposure.parquet",
            "h3_features": "data/processed/phase2_h3_features.parquet",
            "h3_hotspots": "data/processed/phase2_h3_hotspots.parquet",
            "h3_hotspots_csv": "data/processed/phase2_h3_hotspots.csv",
            "h3_hotspots_geojson": "data/processed/phase2_h3_hotspots.geojson",
            "raw_hotspot_rankings_csv": "data/processed/raw_hotspot_rankings.csv",
            "corrected_hotspot_rankings_csv": "data/processed/corrected_hotspot_rankings.csv",
            "spatial_significance_csv": "data/processed/spatial_significance.csv",
            "police_station_hotspot_intelligence_csv": "data/processed/police_station_hotspot_intelligence.csv",
        }
    }
    report = output_contract_report(tmp_path, tmp_path / "artifacts" / "phase2" / "run", config)
    assert report["status"] == "FAIL"
    assert "phase2_h3_hotspots.parquet" in report["missing"]
