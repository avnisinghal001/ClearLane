from __future__ import annotations

import pandas as pd

from clearlane.phase2.exposure import compute_exposure, exposure_invariant_report


def test_device_days_are_distinct_device_date_not_ticket_count():
    mapping = pd.DataFrame({
        "h3_res10": ["a", "a", "a", "b"],
        "device_id": ["d1", "d1", "d2", "d3"],
        "created_by_id": ["o1", "o1", "o1", "o2"],
        "created_date": ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-01"],
        "record_usable_for_exposure_analysis": [True, True, True, True],
    })
    exposure = compute_exposure(mapping, minimum_device_days=2)
    row_a = exposure.set_index("h3_res10").loc["a"]
    assert row_a["device_days"] == 2
    assert row_a["citation_count_exposure_rows"] == 3
    assert bool(row_a["eligible_for_corrected_ranking"]) is True


def test_exposure_invariants_fail_when_exposure_equals_impossible_count():
    exposure = pd.DataFrame({
        "h3_res10": ["a"],
        "device_days": [3],
        "officer_days": [1],
        "unique_devices_exposure": [2],
        "unique_officers_exposure": [1],
        "eligible_for_corrected_ranking": [True],
    })
    aggregates = pd.DataFrame({"h3_res10": ["a"], "citation_count_production": [2]})
    report = exposure_invariant_report(exposure, aggregates)
    assert report["status"] == "FAIL"
    assert "device_days cannot exceed citation_count_production." in report["failures"]
