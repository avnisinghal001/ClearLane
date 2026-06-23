"""Verify required outputs and columns exist after a replay run."""

import pandas as pd

from clearlane.phase3.runner import run_phase3

CANDIDATE_COLS = [
    "h3_res10", "centroid_latitude", "centroid_longitude", "historical_station",
    "mode_police_station", "candidate_tier", "selection_rank", "selection_reason",
    "inside_demo_bbox", "region_validation_status", "region_exclusion_reason",
    "normalized_propensity", "corrected_rank", "spatial_test_status",
    "phase2_run_id", "phase3_run_id", "generated_at",
]

PIC_COLS = [
    "h3_res10", "normalized_propensity", "congestion_severity", "congestion_label",
    "pic_score", "pic_rank", "pic_status", "poll_cycle_id",
]


def test_required_outputs_and_columns(root):
    run_phase3("replay", "configs/phase3.yaml", root=root)
    proc = root / "data/processed"
    interim = root / "data/interim"

    cand = pd.read_parquet(interim / "phase3_whitefield_candidates.parquet")
    for c in CANDIDATE_COLS:
        assert c in cand.columns, f"missing candidate column {c}"

    assert (proc / "phase3_whitefield_candidates.csv").exists()
    assert (proc / "phase3_citywide_historical_layer_manifest.json").exists()

    pic = pd.read_parquet(proc / "phase3_whitefield_live_pic.parquet")
    for c in PIC_COLS:
        assert c in pic.columns, f"missing pic column {c}"

    for ext in ("parquet", "csv", "json", "geojson"):
        assert (proc / f"phase3_whitefield_live_pic.{ext}").exists(), ext

    cong = proc / "phase3_whitefield_live_congestion.parquet"
    assert cong.exists()


def test_citywide_manifest_is_whitefield_only(root):
    import json

    run_phase3("replay", "configs/phase3.yaml", root=root)
    manifest = json.loads((root / "data/processed/phase3_citywide_historical_layer_manifest.json").read_text())
    assert manifest["live_traffic_coverage"] == "WHITEFIELD_DEMO_ONLY"
    assert manifest["citywide_historical_coverage"] == "BENGALURU"
