from __future__ import annotations

import pytest

from clearlane.phase2.h3_assignment import assign_h3_cells, cell_to_parent, latlng_to_cell


def test_h3_assignment_uses_lat_lng_order(sample_phase2_df):
    pytest.importorskip("h3")
    mapping = assign_h3_cells(sample_phase2_df, resolution=10, parent_resolution=9)
    expected = latlng_to_cell(12.9716, 77.5946, 10)
    first = mapping.set_index("record_id_normalized").loc["A1"]
    assert first["h3_res10"] == expected
    assert first["h3_res9"] == cell_to_parent(expected, 9)
    assert mapping["h3_res10"].notna().all()
