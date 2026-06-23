from __future__ import annotations

import pandas as pd

from clearlane.phase1.schema import CRITICAL_COLUMNS, EXPECTED_COLUMNS, validate_schema


def test_schema_passes_when_critical_columns_present(sample_raw):
    report, missing, extra = validate_schema(sample_raw)
    assert missing == []
    assert set(CRITICAL_COLUMNS).issubset(set(report["column_name"]))
    assert not extra


def test_schema_fails_missing_critical_column(sample_raw):
    report, missing, _ = validate_schema(sample_raw.drop(columns=["device_id"]))
    assert missing == ["device_id"]
    row = report[report["column_name"] == "device_id"].iloc[0]
    assert row["validation_status"] == "FAIL"


def test_every_expected_source_column_reported(sample_raw):
    report, _, _ = validate_schema(sample_raw)
    assert set(EXPECTED_COLUMNS) == set(report["column_name"])

