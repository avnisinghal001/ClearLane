import json
from pathlib import Path

from clearlane.phase3.runner import run_phase3


def test_replay_runs_and_is_labelled_replay(root):
    result = run_phase3("replay", "configs/phase3.yaml", root=root)
    assert result["data_mode"] == "REPLAY"
    assert result["status"] == "REPLAY_PASS"
    assert result["poll_cycle"]["valid_observations"] >= 1


def test_replay_outputs_not_labelled_live(root):
    run_phase3("replay", "configs/phase3.yaml", root=root)
    pic_json = root / "data/processed/phase3_whitefield_live_pic.json"
    payload = json.loads(pic_json.read_text())
    assert payload["data_mode"] == "REPLAY"


def test_replay_pic_within_bounds(root):
    import pandas as pd

    run_phase3("replay", "configs/phase3.yaml", root=root)
    pic = pd.read_parquet(root / "data/processed/phase3_whitefield_live_pic.parquet")
    computed = pic[pic["pic_status"] == "COMPUTED"]
    assert (computed["pic_score"] >= 0).all()
    assert (computed["pic_score"] <= 1).all()
    assert computed["poll_cycle_id"].nunique() == 1
