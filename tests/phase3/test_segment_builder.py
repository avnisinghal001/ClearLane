import pytest

from clearlane.phase3 import geometry_utils as geo
from clearlane.phase3 import segment_builder as sb
from clearlane.phase3 import segment_validation as sv
from clearlane.phase3.response_parsers import ProviderError, RouteResult


def _cfg():
    return {
        "segments": {
            "physical_segments_per_h3": 1,
            "directions": ["A_TO_B", "B_TO_A"],
            "target_length_m": 450,
            "minimum_length_m": 200,
            "maximum_length_m": 900,
            "candidate_bearings_deg": [0, 45, 90],
            "maximum_candidates_per_h3": 3,
            "maximum_midpoint_distance_from_h3_m": 250,
            "maximum_route_detour_ratio": 3.0,
            "maximum_geometry_length_difference_ratio": 0.30,
            "snap_to_road": {"enabled": False},
            "reverse_geocode": {"enabled": False},
            "segment_algorithm_version": "phase3-seg-v1",
        }
    }


def _good_route(a_lat, a_lng, b_lat, b_lng):
    pts = [(a_lat, a_lng), (b_lat, b_lng)]
    dist = geo.haversine_m(pts[0], pts[1])
    geom = geo.encode_polyline(pts, 5)
    return RouteResult(distance_m=dist, duration_s=dist / 5.0, geometry=geom, road_name="Test Rd"), None


def test_builds_directed_segments():
    rec = sb.build_segment_for_h3("8a618921d427fff", 12.985, 77.735, _cfg(), route_adv_fn=_good_route)
    assert rec["resolved"] is True
    assert len(rec["directed"]) == 2
    dirs = {d["direction"] for d in rec["directed"]}
    assert dirs == {"A_TO_B", "B_TO_A"}


def test_stable_ids_reproduce():
    a = (12.985, 77.735)
    b = (12.986, 77.736)
    id1 = sv.physical_segment_id("h", a, b, "v1")
    id2 = sv.physical_segment_id("h", b, a, "v1")  # order independent
    assert id1 == id2
    assert id1 != sv.physical_segment_id("h", a, b, "v2")


def test_directed_equals_two_times_physical():
    rec = sb.build_segment_for_h3("8a618921d427fff", 12.985, 77.735, _cfg(), route_adv_fn=_good_route)
    physical = {d["physical_segment_id"] for d in rec["directed"]}
    assert len(physical) == 1
    assert len(rec["directed"]) == 2 * len(physical)


def test_route_failure_marks_unresolved():
    def fail(*a):
        raise ProviderError("ACCESS_DENIED", "denied")

    rec = sb.build_segment_for_h3("h", 12.985, 77.735, _cfg(), route_adv_fn=fail)
    assert rec["resolved"] is False
    assert rec["segment_status"] == "UNRESOLVED"


def test_too_long_route_rejected():
    def long_route(a_lat, a_lng, b_lat, b_lng):
        # return absurd distance, far beyond max
        pts = [(a_lat, a_lng), (b_lat + 0.2, b_lng + 0.2)]
        return RouteResult(distance_m=50000.0, duration_s=3000.0, geometry=geo.encode_polyline(pts, 5), road_name="X"), None

    rec = sb.build_segment_for_h3("h", 12.985, 77.735, _cfg(), route_adv_fn=long_route)
    assert rec["resolved"] is False


def test_far_from_h3_rejected():
    def far_route(a_lat, a_lng, b_lat, b_lng):
        pts = [(12.5, 77.4), (12.51, 77.41)]  # far from centroid
        d = geo.haversine_m(pts[0], pts[1])
        return RouteResult(distance_m=d, duration_s=d / 5, geometry=geo.encode_polyline(pts, 5), road_name="X"), None

    rec = sb.build_segment_for_h3("h", 12.985, 77.735, _cfg(), route_adv_fn=far_route)
    assert rec["resolved"] is False
