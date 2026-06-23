from __future__ import annotations

import pandas as pd
import pytest

from clearlane.phase3 import polling
from clearlane.phase3.mappls_client import RawResponse
from clearlane.phase3.response_parsers import MatrixResult


def _directed_segments() -> pd.DataFrame:
    rows = []
    for i, h3 in enumerate(["h3_a", "h3_b"]):
        pid = f"phys_{i}"
        a_lat = 12.97 + i * 0.001
        a_lng = 77.59 + i * 0.001
        b_lat = a_lat + 0.0005
        b_lng = a_lng + 0.0005
        for direction, a, b in (
            ("A_TO_B", (a_lat, a_lng), (b_lat, b_lng)),
            ("B_TO_A", (b_lat, b_lng), (a_lat, a_lng)),
        ):
            rows.append(
                {
                    "physical_segment_id": pid,
                    "directed_segment_id": f"{pid}_{direction}",
                    "h3_res10": h3,
                    "direction": direction,
                    "endpoint_a_latitude": a[0],
                    "endpoint_a_longitude": a[1],
                    "endpoint_b_latitude": b[0],
                    "endpoint_b_longitude": b[1],
                    "route_distance_m": 100.0 + i * 10.0,
                    "route_duration_reference_s": 20.0 + i * 2.0,
                }
            )
    return pd.DataFrame(rows)


def _candidate_meta() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"h3_res10": "h3_a", "normalized_propensity": 0.5, "corrected_rank": 1},
            {"h3_res10": "h3_b", "normalized_propensity": 0.4, "corrected_rank": 2},
        ]
    )


def _config() -> dict:
    return {
        "polling": {"observation_bucket_minutes": 15},
        "mappls": {"request": {"matrix_physical_segments_per_batch": 10}},
        "quality": {
            "minimum_distance_m": 50,
            "maximum_distance_m": 2000,
            "minimum_duration_seconds": 3,
            "maximum_duration_seconds": 3600,
            "maximum_distance_change_ratio": 0.35,
        },
        "baseline": {
            "preferred_method": "rolling_p10",
            "trailing_days": 28,
            "percentile": 0.10,
            "minimum_valid_samples": 20,
            "minimum_distinct_dates": 2,
            "minimum_distinct_hours": 3,
            "allow_provisional_mappls_non_traffic": True,
            "update_only_from_valid_live_eta": True,
        },
        "congestion": {
            "formula": "one_minus_inverse_tti",
            "traffic_label_bands": {
                "normal": {"label": "NORMAL", "minimum": 0.0, "maximum": 10.0},
                "light": {"label": "LIGHT_CONGESTION", "minimum": 10.0, "maximum": 25.0},
                "moderate": {"label": "MODERATE_CONGESTION", "minimum": 25.0, "maximum": 45.0},
                "high": {"label": "HIGH_CONGESTION", "minimum": 45.0, "maximum": 65.0},
                "severe": {"label": "SEVERE_CONGESTION", "minimum": 65.0, "maximum": 100.0},
            },
            "severity_labels": {
                "normal": {"minimum": 0.00, "maximum": 0.15},
                "moderate": {"minimum": 0.15, "maximum": 0.35},
                "high": {"minimum": 0.35, "maximum": 0.55},
                "severe": {"minimum": 0.55, "maximum": 1.00},
            },
            "directional_aggregation": "maximum",
            "retain_mean_severity": True,
        },
        "pic": {
            "historical_propensity_column": "normalized_propensity",
            "live_congestion_column": "congestion_severity",
            "formula": "multiplication",
            "require_valid_live_observation": True,
            "require_usable_baseline": True,
            "rank_only_same_completed_cycle": True,
        },
    }


def _raw(operation: str) -> RawResponse:
    return RawResponse(
        operation=operation,
        http_status=200,
        body={},
        provider_status=None,
        latency_ms=1.0,
        attempt_count=1,
        data_mode="LIVE",
    )


def test_polling_uses_explicit_directional_matrix_diagonals(monkeypatch):
    calls = []

    def fake_call_matrix_eta(client, points, *, sources=None, destinations=None, budget_scope="poll"):
        calls.append({"sources": list(sources), "destinations": list(destinations)})
        if sources == [0, 2] and destinations == [1, 3]:
            matrix = MatrixResult(
                distances=[[100.0, 999.0], [999.0, 110.0]],
                durations=[[30.0, 999.0], [999.0, 33.0]],
                rows=2,
                cols=2,
            )
        elif sources == [1, 3] and destinations == [0, 2]:
            matrix = MatrixResult(
                distances=[[100.0, 999.0], [999.0, 110.0]],
                durations=[[31.0, 999.0], [999.0, 34.0]],
                rows=2,
                cols=2,
            )
        else:
            raise AssertionError(f"unexpected matrix request: {sources=} {destinations=}")
        return matrix, _raw("distance_matrix_eta")

    monkeypatch.setattr(polling, "call_matrix_eta", fake_call_matrix_eta)

    result = polling.run_poll_cycle(
        directed_segments=_directed_segments(),
        candidate_meta=_candidate_meta(),
        baseline_map={},
        client=object(),
        config=_config(),
        poll_cycle_id="cycle",
        data_mode="LIVE",
    )

    assert calls == [
        {"sources": [0, 2], "destinations": [1, 3]},
        {"sources": [1, 3], "destinations": [0, 2]},
    ]
    assert result["counters"]["requests_attempted"] == 2
    assert result["counters"]["monitored_pairs_requested"] == 4
    assert result["counters"]["monitored_pairs_extracted"] == 4
    assert result["counters"]["matrix_cells_returned"] == 8
    assert all(o["is_valid_observation"] for o in result["observations"])
    durations = {
        (o["physical_segment_id"], o["direction"]): o["live_eta_duration_s"]
        for o in result["observations"]
    }
    assert durations == {
        ("phys_0", "A_TO_B"): 30.0,
        ("phys_0", "B_TO_A"): 31.0,
        ("phys_1", "A_TO_B"): 33.0,
        ("phys_1", "B_TO_A"): 34.0,
    }


def test_polling_adds_speed_labels_and_previous_deltas(monkeypatch):
    def fake_call_matrix_eta(client, points, *, sources=None, destinations=None, budget_scope="poll"):
        if sources == [0, 2] and destinations == [1, 3]:
            matrix = MatrixResult(
                distances=[[100.0, 999.0], [999.0, 110.0]],
                durations=[[30.0, 999.0], [999.0, 33.0]],
                rows=2,
                cols=2,
            )
        else:
            matrix = MatrixResult(
                distances=[[100.0, 999.0], [999.0, 110.0]],
                durations=[[31.0, 999.0], [999.0, 34.0]],
                rows=2,
                cols=2,
            )
        return matrix, _raw("distance_matrix_eta")

    monkeypatch.setattr(polling, "call_matrix_eta", fake_call_matrix_eta)

    result = polling.run_poll_cycle(
        directed_segments=_directed_segments(),
        candidate_meta=_candidate_meta(),
        baseline_map={},
        client=object(),
        config=_config(),
        poll_cycle_id="cycle",
        data_mode="LIVE",
        previous_observations_by_directed={
            "phys_0_A_TO_B": {
                "live_eta_duration_s": 24.0,
                "eta_distance_m": 100.0,
            }
        },
    )

    obs = {
        (o["physical_segment_id"], o["direction"]): o
        for o in result["observations"]
    }
    current = obs[("phys_0", "A_TO_B")]
    assert current["current_speed_kmh"] == pytest.approx(12.0)
    assert current["reference_speed_kmh"] == pytest.approx(18.0)
    assert current["speed_reduction_percentage"] == pytest.approx(33.333333)
    assert current["traffic_label"] == "MODERATE_CONGESTION"
    assert current["eta_change_percentage"] == pytest.approx(25.0)
    assert current["speed_change_percentage"] == pytest.approx(-20.0)

    pic = result["pic"].set_index("h3_res10")
    assert pic.loc["h3_a", "current_speed_kmh"] == pytest.approx(100.0 / 31.0 * 3.6)
    assert pic.loc["h3_a", "congestion_label"] == "MODERATE_CONGESTION"
