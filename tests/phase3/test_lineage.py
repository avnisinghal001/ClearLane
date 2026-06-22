import json

import pytest

from clearlane.phase3 import lineage as lin


def test_resolves_latest_verified_full_run(config, root):
    artifact, manifest, final = lin.resolve_latest_phase2(config, root)
    assert (artifact / "manifest.json").exists()
    assert "h3_hotspots" in final.get("outputs", {})
    assert final.get("status") in {"PASS", "WARN"}


def test_validate_passes_on_real_data(config, root):
    result = lin.validate(config, root)
    assert result.loaded_h3_rows > 0
    assert result.checksum_match is True
    assert result.raw_phase1_data_used is False
    assert result.required_columns_present is True
    # all warnings are allowed
    allowed = set(config["phase2"]["allowed_warnings"])
    assert all(w in allowed for w in result.phase2_warnings)


def test_incomplete_newer_run_ignored(config, root, tmp_path, monkeypatch):
    # Point artifact root at a temp dir with one incomplete newer run + symlink real
    import shutil

    real_artifact, _, _ = lin.resolve_latest_phase2(config, root)
    fake_root = tmp_path / "phase2"
    fake_root.mkdir()
    # incomplete newer run (lexicographically larger)
    newer = fake_root / "99999999_999999_phase2"
    (newer / "reports").mkdir(parents=True)
    (newer / "manifest.json").write_text(json.dumps({"status": "WARN", "run_id": "x"}))
    # missing final report -> incomplete
    # copy the real run in
    shutil.copytree(real_artifact, fake_root / real_artifact.name)
    cfg = dict(config)
    cfg["phase2"] = dict(config["phase2"])
    cfg["phase2"]["artifact_root"] = str(fake_root.relative_to(root)) if str(fake_root).startswith(str(root)) else str(fake_root)

    # use absolute by monkeypatching repo_root resolution: pass artifact_root absolute
    cfg["phase2"]["artifact_root"] = str(fake_root)
    artifact, _, _ = lin.resolve_latest_phase2(cfg, root)
    assert artifact.name == real_artifact.name  # not the incomplete 9999 run


def test_disallowed_warning_blocks(config, root, tmp_path):
    # Build a synthetic artifact root with ONE full run carrying a disallowed warning.
    fake_root = tmp_path / "phase2"
    run = fake_root / "20260622_999999_phase2"
    (run / "reports").mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({
        "status": "WARN", "run_id": "synthetic", "warnings": ["TOTALLY_UNAPPROVED_WARNING"], "errors": [],
    }))
    (run / "reports" / "phase2_final_report.json").write_text(json.dumps({
        "status": "WARN", "run_id": "synthetic",
        "warnings": ["TOTALLY_UNAPPROVED_WARNING"], "errors": [],
        "outputs": {"h3_hotspots": "x"},
    }))
    cfg = dict(config)
    cfg["phase2"] = dict(config["phase2"])
    cfg["phase2"]["artifact_root"] = str(fake_root)
    with pytest.raises(lin.LineageError):
        lin.resolve_latest_phase2(cfg, root)


def test_allowed_warnings_pass(config, root):
    # The real latest run carries only allowed warnings and must resolve.
    artifact, _, final = lin.resolve_latest_phase2(config, root)
    assert artifact is not None


def test_no_raw_phase1_paths_listed():
    assert "data/raw" in lin.FORBIDDEN_INPUTS
    assert "data/interim/violations_cleaned.parquet" in lin.FORBIDDEN_INPUTS
