from __future__ import annotations

import pandas as pd

from .conftest import EXPECTED_COLUMNS, make_row, run_clean


def test_row_reconciliation_equation(tmp_path, phase1_config):
    rows = [
        make_row(id="A"),
        make_row(id="B", latitude="91"),
        make_row(id="C"),
        make_row(id="C"),
    ]
    df = pd.DataFrame(rows, columns=EXPECTED_COLUMNS)
    df.insert(0, "source_row_number", range(2, len(df) + 2))
    result = run_clean(tmp_path, df, phase1_config)
    recon = result.reports["row_reconciliation"]
    assert recon["raw_rows"] == recon["accepted_rows"] + recon["quarantined_rows"] + recon["exact_duplicate_rows_removed"]
    assert recon["passed"]

