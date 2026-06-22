import pytest

from clearlane.phase3 import congestion as cong


@pytest.mark.parametrize(
    "ref,eta,expected",
    [
        (100, 100, 0.0),
        (100, 150, 0.333333),
        (100, 200, 0.5),
        (100, 400, 0.75),
    ],
)
def test_known_severities(ref, eta, expected):
    assert cong.congestion_severity(eta, ref) == pytest.approx(expected, abs=1e-5)


def test_missing_eta_is_none_not_zero():
    assert cong.congestion_severity(None, 100) is None
    assert cong.congestion_severity(100, None) is None


def test_zero_or_negative_reference_is_none():
    assert cong.congestion_severity(100, 0) is None
    assert cong.congestion_severity(100, -5) is None


def test_tti_and_delay():
    assert cong.travel_time_index(200, 100) == pytest.approx(2.0)
    assert cong.delay_seconds(150, 100) == pytest.approx(50.0)
    assert cong.delay_seconds(80, 100) == 0.0  # never negative
    assert cong.delay_ratio(150, 100) == pytest.approx(0.5)


def test_labels():
    assert cong.severity_label(0.05) == "NORMAL"
    assert cong.severity_label(0.25) == "MODERATE"
    assert cong.severity_label(0.45) == "HIGH"
    assert cong.severity_label(0.8) == "SEVERE"
    assert cong.severity_label(None) is None


def test_directional_aggregation_uses_maximum():
    agg = cong.aggregate_directions(0.3, 0.6)
    assert agg["maximum_severity"] == pytest.approx(0.6)
    assert agg["maximum_severity_direction"] == "B_TO_A"
    assert agg["directional_coverage_status"] == "BOTH_DIRECTIONS_VALID"


def test_directional_one_valid():
    agg = cong.aggregate_directions(0.3, None)
    assert agg["valid_direction_count"] == 1
    assert agg["directional_coverage_status"] == "ONE_DIRECTION_VALID"


def test_directional_none_valid():
    agg = cong.aggregate_directions(None, None)
    assert agg["directional_coverage_status"] == "NO_VALID_DIRECTION"
    assert agg["maximum_severity"] is None
