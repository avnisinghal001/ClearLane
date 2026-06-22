from __future__ import annotations

from clearlane.phase1.reporting import dataframe_fingerprint
from .conftest import run_clean


def test_cleaning_reproducible_on_same_input(tmp_path, sample_raw, phase1_config):
    a = run_clean(tmp_path / "a", sample_raw, phase1_config)
    b = run_clean(tmp_path / "b", sample_raw, phase1_config)
    assert len(a.accepted) == len(b.accepted)
    assert len(a.quarantined) == len(b.quarantined)
    assert dataframe_fingerprint(a.accepted) == dataframe_fingerprint(b.accepted)

