from __future__ import annotations

from clearlane.phase1.fingerprint import sha256_file


def test_raw_immutability_hash_unchanged_after_read(tmp_path):
    p = tmp_path / "raw.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    before = sha256_file(p)
    _ = p.read_text(encoding="utf-8")
    after = sha256_file(p)
    assert before == after

