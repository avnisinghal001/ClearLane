from __future__ import annotations

import pytest

from clearlane.phase2.lineage import LineageError, validate_phase1_lineage


def test_lineage_accepts_verified_phase1_handoff(phase2_test_root):
    root, config, _ = phase2_test_root
    lineage = validate_phase1_lineage(config, root=root)
    assert lineage.phase1_run_id == "test_phase1"
    assert lineage.phase1_status == "PASS"
    assert lineage.row_reconciliation_passed is True
    assert lineage.expected_rows == lineage.loaded_rows == 3
    assert lineage.checksum_source == "checksums/dataset_checksums.json"


def test_lineage_rejects_checksum_mismatch(phase2_test_root, sample_phase2_df):
    root, config, parquet = phase2_test_root
    modified = sample_phase2_df.copy()
    modified.loc[0, "vehicle_type_normalized"] = "TRUCK"
    modified.to_parquet(parquet, index=False)

    with pytest.raises(LineageError) as exc:
        validate_phase1_lineage(config, root=root)
    assert exc.value.code == "PHASE2_INPUT_NOT_VERIFIED"
    assert "checksum mismatch" in str(exc.value).lower()
