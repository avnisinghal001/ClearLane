import json
from pathlib import Path

import pytest

from clearlane.phase3 import geometry_utils as geo

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "mappls"


def read_fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_text())


def test_real_route_adv_fixture_decodes_precision_5():
    body = read_fixture("route_adv.json")
    encoded = body["routes"][0]["geometry"]
    provider_distance = body["routes"][0]["distance"]
    dec = geo.decode_route_geometry(encoded, provider_distance, max_diff_ratio=0.30, precision=5)
    assert dec["status"] == "DECODED"
    assert len(dec["points_latlng"]) >= 2
    # decoded length should be close to provider distance (1626.2)
    assert dec["length_difference_ratio"] < 0.05


def test_geojson_is_lng_lat_order():
    body = read_fixture("route_adv.json")
    pts = geo.decode_polyline(body["routes"][0]["geometry"], 5)
    gj = geo.to_geojson_linestring(pts)
    assert gj["type"] == "LineString"
    lng, lat = gj["coordinates"][0]
    assert 77.0 < lng < 78.0  # longitude first
    assert 12.0 < lat < 13.5


def test_wrong_precision_fails_distance_check():
    body = read_fixture("route_adv.json")
    encoded = body["routes"][0]["geometry"]
    provider_distance = body["routes"][0]["distance"]
    dec = geo.decode_route_geometry(encoded, provider_distance, max_diff_ratio=0.30, precision=6)
    assert dec["status"] == "GEOMETRY_DISTANCE_MISMATCH"


def test_invalid_geometry_raises():
    with pytest.raises(geo.GeometryError):
        geo.decode_route_geometry("", 100.0, 0.30)


def test_geodesic_destination_distance():
    lat, lng = 12.985, 77.735
    dest = geo.destination_point(lat, lng, 90.0, 225.0)
    d = geo.haversine_m((lat, lng), dest)
    assert d == pytest.approx(225.0, abs=1.0)
