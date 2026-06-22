from __future__ import annotations

from pathlib import Path


def test_phase2_source_does_not_read_raw_or_old_processed_inputs():
    root = Path(__file__).resolve().parents[2]
    forbidden = [
        "data/raw",
        "events_clean.parquet",
        "processed/v3",
        "jan to may police",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in (root / "src" / "clearlane" / "phase2").glob("*.py"))
    for token in forbidden:
        assert token not in source
