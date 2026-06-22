import pytest

from clearlane.phase3 import localized_anomaly as la


def test_computed_value():
    res = la.compute_for_cell(0.8, [0.2, 0.4], minimum_valid_neighbors=2)
    assert res["localized_anomaly_status"] == "COMPUTED"
    assert res["neighbor_median_severity"] == pytest.approx(0.3)
    assert res["localized_anomaly"] == pytest.approx(0.5)
    assert res["localized_anomaly_positive"] is True


def test_insufficient_neighbors():
    res = la.compute_for_cell(0.8, [0.2], minimum_valid_neighbors=2)
    assert res["localized_anomaly_status"] == "INSUFFICIENT_VALID_NEIGHBORS"
    assert res["localized_anomaly"] is None


def test_no_neighbors():
    res = la.compute_for_cell(0.8, [], minimum_valid_neighbors=2)
    assert res["localized_anomaly_status"] == "NO_MONITORED_NEIGHBORS"


def test_current_invalid():
    res = la.compute_for_cell(None, [0.2, 0.4], minimum_valid_neighbors=2)
    assert res["localized_anomaly_status"] == "CURRENT_CELL_INVALID"


def test_invalid_neighbors_excluded():
    res = la.compute_for_cell(0.8, [0.2, None, 0.4, None], minimum_valid_neighbors=2)
    assert res["neighbor_count_valid"] == 2
    assert res["localized_anomaly_status"] == "COMPUTED"
