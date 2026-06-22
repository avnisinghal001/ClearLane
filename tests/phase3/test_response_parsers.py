import json
from pathlib import Path

import pytest

from clearlane.phase3 import response_parsers as rp

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "mappls"


def read_fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_text())


def test_parse_route_adv():
    body = read_fixture("route_adv.json")
    res = rp.parse_route(body, 200)
    assert res.distance_m == pytest.approx(1626.2)
    assert res.duration_s == pytest.approx(188.9)
    assert res.geometry
    assert res.road_name == "Sri ML Subbaraju Road"


def test_parse_route_eta():
    res = rp.parse_route(read_fixture("route_eta.json"), 200)
    assert res.duration_s > 0


def test_parse_matrix_normal():
    res = rp.parse_matrix(read_fixture("distance_matrix.json"), 200)
    assert res.rows == 4 and res.cols == 4
    assert res.durations[0][1] == pytest.approx(188.9)


def test_parse_matrix_eta():
    res = rp.parse_matrix(read_fixture("distance_matrix_eta.json"), 200)
    assert res.durations[0][1] == pytest.approx(538.4)


def test_parse_matrix_results_list_shape():
    body = {
        "responseCode": 200,
        "results": [
            {
                "code": "Ok",
                "distances": [[0, 120.0], [120.0, 0]],
                "durations": [[0, 30.0], [31.0, 0]],
            }
        ],
    }
    res = rp.parse_matrix(body, 200)
    assert res.rows == 2
    assert res.durations[1][0] == pytest.approx(31.0)


def test_multi_location_matrix_eta():
    res = rp.parse_matrix(read_fixture("distance_matrix_eta.json"), 200)
    assert res.rows >= 3


def test_http_200_access_denied_is_failure():
    body = read_fixture("error_access_denied.json")
    assert rp.classify_error(body, 200) == rp.ACCESS_DENIED
    with pytest.raises(rp.ProviderError):
        rp.parse_route(body, 200)


def test_invalid_token_body_is_failure():
    body = read_fixture("error_invalid_token.json")
    assert rp.classify_error(body, 200) == rp.INVALID_TOKEN
    with pytest.raises(rp.ProviderError):
        rp.parse_matrix(body, 200)


def test_missing_duration():
    body = {"routes": [{"distance": 100.0}], "code": "Ok"}
    with pytest.raises(rp.ProviderError):
        rp.parse_route(body, 200)


def test_missing_distance():
    body = {"results": {"durations": [[0, 1]], "code": "Ok"}, "responseCode": 200}
    with pytest.raises(rp.ProviderError):
        rp.parse_matrix(body, 200)


def test_empty_result():
    body = {"results": {"distances": [], "durations": [], "code": "Ok"}}
    with pytest.raises(rp.ProviderError):
        rp.parse_matrix(body, 200)


def test_schema_change_non_object():
    with pytest.raises(rp.ProviderError):
        rp.parse_route("not json", 200)


def test_parse_snap_lng_lat_order():
    pts = rp.parse_snap(read_fixture("snaptoroad.json"), 200)
    assert len(pts) == 3
    # location is [lng, lat]; first point lat ~12.97, lng ~77.59
    assert 12.9 < pts[0].lat < 13.0
    assert 77.5 < pts[0].lng < 77.7


def test_parse_reverse_geocode():
    res = rp.parse_reverse_geocode(read_fixture("rev_geocode.json"), 200)
    assert res.locality == "Gandhi Nagar"
    assert res.formatted_address
