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
    assert cong.delay_percentage(150, 100) == pytest.approx(50.0)


def test_configured_traffic_labels():
    cfg = {
        "congestion": {
            "traffic_label_bands": {
                "normal": {"label": "NORMAL", "minimum": 0, "maximum": 10},
                "light": {"label": "LIGHT_CONGESTION", "minimum": 10, "maximum": 25},
                "moderate": {"label": "MODERATE_CONGESTION", "minimum": 25, "maximum": 45},
                "high": {"label": "HIGH_CONGESTION", "minimum": 45, "maximum": 65},
                "severe": {"label": "SEVERE_CONGESTION", "minimum": 65, "maximum": 100},
            }
        }
    }
    assert cong.traffic_label(5, cfg) == "NORMAL"
    assert cong.traffic_label(10, cfg) == "LIGHT_CONGESTION"
    assert cong.traffic_label(25, cfg) == "MODERATE_CONGESTION"
    assert cong.traffic_label(45, cfg) == "HIGH_CONGESTION"
    assert cong.traffic_label(80, cfg) == "SEVERE_CONGESTION"
    assert cong.traffic_label(None, cfg) is None


def test_legacy_severity_labels():
    assert cong.severity_label(0.05) == "NORMAL"
    assert cong.severity_label(0.25) == "MODERATE"
    assert cong.severity_label(0.45) == "HIGH"
    assert cong.severity_label(0.8) == "SEVERE"
    assert cong.severity_label(None) is None


def test_speed_delay_and_delta_metrics():
    out = cong.compute(
        150,
        100,
        current_distance_m=1000,
        reference_distance_m=1000,
        previous_live_eta_s=120,
        previous_current_speed_kmh=30,
    )
    assert out["current_speed_kmh"] == pytest.approx(24.0)
    assert out["reference_speed_kmh"] == pytest.approx(36.0)
    assert out["speed_reduction_percentage"] == pytest.approx(33.333333)
    assert out["delay_seconds"] == pytest.approx(50.0)
    assert out["delay_percentage"] == pytest.approx(50.0)
    assert out["travel_time_index"] == pytest.approx(1.5)
    assert out["congestion_severity"] == pytest.approx(0.333333)
    assert out["congestion_severity_percentage"] == pytest.approx(33.333333)
    assert out["eta_change_percentage"] == pytest.approx(25.0)
    assert out["speed_change_percentage"] == pytest.approx(-20.0)
    assert out["traffic_label"] == "MODERATE_CONGESTION"


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
