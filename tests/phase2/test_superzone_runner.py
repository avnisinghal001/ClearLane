from __future__ import annotations

import pytest

from clearlane.phase2.runner import run_phase2
from clearlane.phase2.superzone_mapping import superzone_status


def test_superzones_disabled_do_not_claim_missing_model(tmp_path):
    report = superzone_status(
        {"superzones": {"enabled": False, "definitions_path": "missing.geojson"}},
        tmp_path,
    )
    assert report["status"] == "DISABLED"


def test_superzones_enabled_missing_definitions_fail(tmp_path):
    with pytest.raises(FileNotFoundError):
        superzone_status(
            {
                "superzones": {
                    "enabled": True,
                    "definitions_path": "missing.geojson",
                    "fail_when_claimed_but_missing": True,
                }
            },
            tmp_path,
        )


def test_runner_lineage_only_writes_reports(phase2_test_root):
    root, config, _ = phase2_test_root
    result = run_phase2(config_path=config["_config_path"], root=root, lineage_only=True)
    assert result["status"] == "PASS"
    artifact = root / "artifacts" / "phase2" / result["run_id"]
    assert (artifact / "reports" / "phase2_lineage_validation.json").exists()
    assert (artifact / "reports" / "phase1_parking_classification_reconciliation.json").exists()
