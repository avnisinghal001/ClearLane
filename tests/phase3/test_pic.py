import pandas as pd
import pytest

from clearlane.phase3 import pic


def test_basic_product():
    assert pic.pic_score(0.8, 0.5) == pytest.approx(0.4)


def test_bounds():
    assert pic.pic_score(1.0, 1.0) == 1.0
    assert pic.pic_score(0.0, 0.9) == 0.0


def test_missing_severity_returns_none():
    assert pic.pic_score(0.8, None) is None


def test_out_of_range_inputs_none():
    assert pic.pic_score(1.5, 0.5) is None
    assert pic.pic_score(0.5, 1.5) is None


def _frame():
    return pd.DataFrame(
        [
            {"h3_res10": "a", "normalized_propensity": 0.8, "congestion_severity": 0.5,
             "live_observation_valid": True, "baseline_usable": True},
            {"h3_res10": "b", "normalized_propensity": 0.9, "congestion_severity": 0.5,
             "live_observation_valid": True, "baseline_usable": True},
            {"h3_res10": "c", "normalized_propensity": 0.7, "congestion_severity": None,
             "live_observation_valid": False, "baseline_usable": True},
        ]
    )


def test_ranking_and_not_computed():
    ranked = pic.rank_pic(_frame(), "cycle1")
    computed = ranked[ranked["pic_status"] == "COMPUTED"]
    assert len(computed) == 2
    # b (0.45) ranks above a (0.40)
    top = computed.sort_values("pic_rank").iloc[0]
    assert top["h3_res10"] == "b"
    assert ranked.loc[ranked.h3_res10 == "c", "pic_status"].iloc[0] == "NOT_COMPUTED"


def test_single_poll_cycle_only():
    ranked = pic.rank_pic(_frame(), "cycle1")
    assert ranked.loc[ranked.pic_status == "COMPUTED", "poll_cycle_id"].nunique() == 1
    assert pic.validate_bounds(ranked) == []


def test_deterministic_tie_break():
    df = pd.DataFrame(
        [
            {"h3_res10": "z", "normalized_propensity": 0.5, "congestion_severity": 0.5,
             "live_observation_valid": True, "baseline_usable": True},
            {"h3_res10": "a", "normalized_propensity": 0.5, "congestion_severity": 0.5,
             "live_observation_valid": True, "baseline_usable": True},
        ]
    )
    ranked = pic.rank_pic(df, "c").sort_values("pic_rank")
    assert list(ranked["h3_res10"]) == ["a", "z"]  # H3 ascending breaks tie
