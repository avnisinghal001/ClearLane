from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from clearlane.phase1.fingerprint import sha256_file


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture
def sample_phase2_df() -> pd.DataFrame:
    rows = [
        {
            "id": "A1",
            "record_id_normalized": "A1",
            "latitude_numeric": 12.9716,
            "longitude_numeric": 77.5946,
            "created_date": "2024-01-01",
            "device_id": "D1",
            "created_by_id": "O1",
            "vehicle_number_normalized": "KA01AA0001",
            "vehicle_type_normalized": "CAR",
            "violation_labels": ["WRONG PARKING"],
            "primary_violation_label": "WRONG PARKING",
            "contains_parking_related_label": True,
            "police_station_normalized": "central",
            "junction_name_normalized": "junction-a",
            "validation_status_normalized": "approved",
            "is_approved": True,
            "is_rejected": False,
            "record_usable_for_spatial_analysis": True,
            "record_usable_for_exposure_analysis": True,
        },
        {
            "id": "A2",
            "record_id_normalized": "A2",
            "latitude_numeric": 12.9717,
            "longitude_numeric": 77.5947,
            "created_date": "2024-01-01",
            "device_id": "D1",
            "created_by_id": "O1",
            "vehicle_number_normalized": "KA01AA0002",
            "vehicle_type_normalized": "BIKE",
            "violation_labels": ["WRONG PARKING"],
            "primary_violation_label": "WRONG PARKING",
            "contains_parking_related_label": True,
            "police_station_normalized": "central",
            "junction_name_normalized": "junction-a",
            "validation_status_normalized": "approved",
            "is_approved": True,
            "is_rejected": False,
            "record_usable_for_spatial_analysis": True,
            "record_usable_for_exposure_analysis": True,
        },
        {
            "id": "A3",
            "record_id_normalized": "A3",
            "latitude_numeric": 12.9720,
            "longitude_numeric": 77.5950,
            "created_date": "2024-01-02",
            "device_id": "D2",
            "created_by_id": "O1",
            "vehicle_number_normalized": "KA01AA0003",
            "vehicle_type_normalized": "CAR",
            "violation_labels": ["NO PARKING"],
            "primary_violation_label": "NO PARKING",
            "contains_parking_related_label": True,
            "police_station_normalized": "central",
            "junction_name_normalized": "junction-b",
            "validation_status_normalized": "rejected",
            "is_approved": False,
            "is_rejected": True,
            "record_usable_for_spatial_analysis": True,
            "record_usable_for_exposure_analysis": True,
        },
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def phase2_test_root(tmp_path, sample_phase2_df):
    root = tmp_path
    parquet = root / "data" / "interim" / "violations_cleaned.parquet"
    parquet.parent.mkdir(parents=True, exist_ok=True)
    sample_phase2_df.to_parquet(parquet, index=False)

    artifact = root / "artifacts" / "phase1" / "test_phase1"
    reports = artifact / "reports"
    checksums = artifact / "checksums"
    reports.mkdir(parents=True)
    checksums.mkdir(parents=True)

    write_json(artifact / "manifest.json", {
        "run_id": "test_phase1",
        "phase": "phase1",
        "status": "PASS",
        "raw_file_unchanged": True,
    })
    write_json(reports / "phase1_final_report.json", {
        "run_id": "test_phase1",
        "status": "PASS",
        "summary": {
            "accepted_rows": len(sample_phase2_df),
            "quarantined_rows": 0,
            "row_reconciliation_passed": True,
            "parking_related_percentage": 100.0,
        },
        "outputs": {"cleaned_parquet": str(parquet)},
    })
    write_json(reports / "row_reconciliation.json", {
        "raw_rows": len(sample_phase2_df),
        "accepted_rows": len(sample_phase2_df),
        "quarantined_rows": 0,
        "exact_duplicate_rows_removed": 0,
        "passed": True,
    })
    pd.DataFrame({"column_name": sample_phase2_df.columns}).to_csv(reports / "data_dictionary.csv", index=False)
    pd.DataFrame([{
        "claim_name": "parking_related_percentage",
        "document_reference_value": 97.3,
        "recomputed_value": 100.0,
        "status": "DIFFERENT",
    }]).to_csv(reports / "document_claims_comparison.csv", index=False)
    write_json(checksums / "dataset_checksums.json", {
        "cleaned_parquet_sha256": sha256_file(parquet),
    })

    config_path = root / "configs" / "phase2.yaml"
    config = {
        "_config_path": str(config_path),
        "phase1": {
            "run_id": "test_phase1",
            "artifact_dir": "artifacts/phase1/test_phase1",
            "cleaned_parquet": "data/interim/violations_cleaned.parquet",
            "required_status": "PASS",
            "require_row_reconciliation": True,
        },
        "population": {"production_population": "population_all_accepted"},
        "spatial": {"resolution": 10, "parent_resolution": 9},
        "exposure": {"minimum_device_days": 1},
        "raw_baseline": {"top_k_values": [1, 2], "concentration_percentiles": [0.5]},
        "gamma_poisson": {
            "prior_strength": 2.0,
            "credible_interval": 0.95,
            "sensitivity_prior_strengths": [2.0, 5.0],
            "sensitivity_top_k": 2,
        },
        "negative_binomial": {"fit_enabled": False, "feature_columns": []},
        "spatial_significance": {"enabled": False, "minimum_present_neighbors": 1},
        "superzones": {"enabled": False, "definitions_path": "data/reference/superzones.geojson"},
        "outputs": {"artifact_root": "artifacts/phase2"},
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_to_write = {k: v for k, v in config.items() if k != "_config_path"}
    config_path.write_text(yaml.safe_dump(config_to_write, sort_keys=False), encoding="utf-8")
    return root, config, parquet
