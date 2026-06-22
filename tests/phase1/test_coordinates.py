from __future__ import annotations

import pandas as pd

from .conftest import EXPECTED_COLUMNS, make_row, run_clean


def _df(rows):
    df = pd.DataFrame(rows, columns=EXPECTED_COLUMNS)
    df.insert(0, "source_row_number", range(2, len(df) + 2))
    return df


def test_valid_bengaluru_coordinate_accepted(tmp_path, phase1_config):
    result = run_clean(tmp_path, _df([make_row(id="A")]), phase1_config)
    assert len(result.accepted) == 1
    assert bool(result.accepted.iloc[0]["coordinate_bengaluru_sanity_valid"])


def test_latitude_over_90_quarantined(tmp_path, phase1_config):
    result = run_clean(tmp_path, _df([make_row(id="A", latitude="91")]), phase1_config)
    assert len(result.accepted) == 0
    assert "INVALID_COORDINATE" in result.quarantined.iloc[0]["reason_code"]


def test_longitude_over_180_quarantined(tmp_path, phase1_config):
    result = run_clean(tmp_path, _df([make_row(id="A", longitude="181")]), phase1_config)
    assert "INVALID_COORDINATE" in result.quarantined.iloc[0]["reason_code"]


def test_non_numeric_coordinate_quarantined(tmp_path, phase1_config):
    result = run_clean(tmp_path, _df([make_row(id="A", latitude="not-a-lat")]), phase1_config)
    assert "INVALID_COORDINATE" in result.quarantined.iloc[0]["reason_code"]


def test_zero_zero_flagged_not_invalid_by_global_rule(tmp_path, phase1_config):
    result = run_clean(tmp_path, _df([make_row(id="A", latitude="0", longitude="0")]), phase1_config)
    assert len(result.accepted) == 1
    assert bool(result.accepted.iloc[0]["coordinate_zero_zero"])
    assert not bool(result.accepted.iloc[0]["coordinate_bengaluru_sanity_valid"])


def test_possible_swapped_coordinate_flagged(tmp_path, phase1_config):
    result = run_clean(tmp_path, _df([make_row(id="A", latitude="77.61", longitude="12.92")]), phase1_config)
    assert len(result.accepted) == 1
    assert bool(result.accepted.iloc[0]["possible_coordinate_swap"])

