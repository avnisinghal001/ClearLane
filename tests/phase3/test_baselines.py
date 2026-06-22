from datetime import datetime, timedelta

import pytest

from clearlane.phase3 import baselines as bl


def test_provider_non_traffic_is_provisional():
    res = bl.compute_baseline(live_eta_samples=[], provider_non_traffic_s=188.9)
    assert res["baseline_status"] == bl.PROVISIONAL_MAPPLS
    assert res["free_flow_reference_duration_s"] == pytest.approx(188.9)


def test_percentile_p10():
    vals = list(range(1, 101))  # 1..100
    p10 = bl.percentile([float(v) for v in vals], 0.10)
    assert p10 == pytest.approx(10.9, abs=0.5)


def test_ready_when_enough_history():
    base = datetime(2026, 6, 1, 8, 0, 0)
    samples = []
    for day in range(3):
        for hour in range(0, 12, 3):  # distinct hours
            for k in range(2):
                samples.append((base + timedelta(days=day, hours=hour, minutes=k), 100.0 + k))
    cfg = bl.BaselineConfig(minimum_valid_samples=20, minimum_distinct_dates=2, minimum_distinct_hours=3)
    res = bl.compute_baseline(live_eta_samples=samples, provider_non_traffic_s=188.9, cfg=cfg)
    assert res["baseline_status"] == bl.READY_ROLLING_P10
    assert res["sample_count"] >= 20


def test_unavailable_when_nothing():
    res = bl.compute_baseline(live_eta_samples=[], provider_non_traffic_s=None)
    assert res["baseline_status"] == bl.UNAVAILABLE
    assert res["free_flow_reference_duration_s"] is None


def test_invalid_samples_excluded():
    samples = [(datetime(2026, 6, 1, 8), 100.0), (datetime(2026, 6, 1, 9), -5.0), (datetime(2026, 6, 1, 10), float("nan"))]
    res = bl.compute_baseline(live_eta_samples=samples, provider_non_traffic_s=188.9)
    assert res["sample_count"] == 1
