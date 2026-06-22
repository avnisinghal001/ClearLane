from __future__ import annotations

import pytest

from clearlane.phase2.h3_assignment import latlng_to_cell
from clearlane.phase2.h3_geometry import h3_boundary_lonlat, h3_feature
from clearlane.phase2.spatial_weights import grid_disk, present_neighbor_map


def test_h3_geometry_exports_geojson_lon_lat_order():
    pytest.importorskip("h3")
    cell = latlng_to_cell(12.9716, 77.5946, 10)
    ring = h3_boundary_lonlat(cell)
    lon, lat = ring[0]
    assert 77.0 < lon < 78.0
    assert 12.0 < lat < 13.5
    feature = h3_feature(cell)
    assert feature["properties"]["polygon_valid"] is True


def test_neighbor_map_contains_present_ring1_neighbors():
    pytest.importorskip("h3")
    cell = latlng_to_cell(12.9716, 77.5946, 10)
    neighbor = sorted(grid_disk(cell, 1) - {cell})[0]
    neighbors = present_neighbor_map([cell, neighbor])
    assert neighbor in neighbors[cell]
    assert cell in neighbors[neighbor]
