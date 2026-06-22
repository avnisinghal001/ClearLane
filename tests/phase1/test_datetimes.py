from __future__ import annotations

import pandas as pd

from clearlane.phase1.datetime_utils import parse_timestamp_value, timestamp_has_timezone
from .conftest import EXPECTED_COLUMNS, make_row, run_clean


def _df(rows):
    df = pd.DataFrame(rows, columns=EXPECTED_COLUMNS)
    df.insert(0, "source_row_number", range(2, len(df) + 2))
    return df


def test_valid_naive_timestamp_uses_configured_timezone():
    ts = parse_timestamp_value(
        "2023-11-20 05:58:46",
        source_timezone="Asia/Kolkata",
        canonical_timezone="Asia/Kolkata",
    )
    assert ts.tzinfo is not None
    assert ts.hour == 5


def test_valid_aware_timestamp_converts_to_canonical_timezone():
    ts = parse_timestamp_value(
        "2023-11-20 00:28:46+00",
        source_timezone="Asia/Kolkata",
        canonical_timezone="Asia/Kolkata",
    )
    assert ts.hour == 5
    assert ts.minute == 58
    assert timestamp_has_timezone("2023-11-20 00:28:46+00")


def test_invalid_created_datetime_quarantined(tmp_path, phase1_config):
    result = run_clean(tmp_path, _df([make_row(id="A", created_datetime="bad-date")]), phase1_config)
    assert "INVALID_CREATED_DATETIME" in result.quarantined.iloc[0]["reason_code"]


def test_date_fields_and_hour_diagnostic_generated(tmp_path, phase1_config):
    result = run_clean(tmp_path, _df([make_row(id="A")]), phase1_config)
    row = result.accepted.iloc[0]
    assert row["created_date"] == "2023-11-20"
    assert row["created_day_of_week"] == 0
    assert "created_hour_diagnostic" in result.accepted.columns
    assert "violation_hour" not in result.accepted.columns

