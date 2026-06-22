from __future__ import annotations

import pandas as pd

from .conftest import EXPECTED_COLUMNS, make_row, run_clean


def _df(rows):
    df = pd.DataFrame(rows, columns=EXPECTED_COLUMNS)
    df.insert(0, "source_row_number", range(2, len(df) + 2))
    return df


def test_exact_duplicate_removed_once(tmp_path, phase1_config):
    row = make_row(id="A")
    result = run_clean(tmp_path, _df([row, row.copy()]), phase1_config)
    assert len(result.accepted) == 1
    assert len(result.exact_duplicates) == 1
    assert result.reports["row_reconciliation"]["passed"]


def test_same_id_conflicting_content_quarantined(tmp_path, phase1_config):
    rows = [make_row(id="A", latitude="12.9"), make_row(id="A", latitude="12.91")]
    result = run_clean(tmp_path, _df(rows), phase1_config)
    assert len(result.accepted) == 0
    assert len(result.quarantined) == 2
    assert result.quarantined["reason_code"].str.contains("CONFLICTING_DUPLICATE_ID").all()


def test_similar_records_with_different_ids_retained(tmp_path, phase1_config):
    rows = [make_row(id="A"), make_row(id="B")]
    result = run_clean(tmp_path, _df(rows), phase1_config)
    assert len(result.accepted) == 2

