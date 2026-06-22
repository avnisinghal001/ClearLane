"""Build one real physical road segment per primary H3 cell.

For each H3 centroid: generate geodesic endpoint-pair candidates around the
centroid (configured bearings + target length), optionally snap to roads, request
Route ADV, decode + validate geometry, score, and keep the best valid segment.
Both directed forms (A_TO_B, B_TO_A) are emitted, and non-traffic reference
durations are cached. If no candidate is valid, the H3 is marked unresolved so a
reserve candidate can be promoted. Straight-line "roads" are never fabricated.
"""

from __future__ import annotations

from typing import Any, Optional

from . import geometry_utils as geo
from . import segment_validation as sv
from .common import now_ist
from .response_parsers import ProviderError


class SegmentBuildError(RuntimeError):
    pass


def _candidate_endpoints(lat: float, lng: float, bearing: float, target_len: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Symmetric endpoints around centroid: half target length each side."""
    half = target_len / 2.0
    a = geo.destination_point(lat, lng, bearing, half)
    b = geo.destination_point(lat, lng, (bearing + 180.0) % 360.0, half)
    return a, b


def build_segment_for_h3(
    h3: str,
    centroid_lat: float,
    centroid_lng: float,
    config: dict[str, Any],
    *,
    route_adv_fn,
    snap_fn=None,
    reverse_geocode_fn=None,
) -> dict[str, Any]:
    """route_adv_fn(a_lat,a_lng,b_lat,b_lng) -> (RouteResult, raw). Returns a build record."""
    seg_cfg = config["segments"]
    algo = seg_cfg.get("segment_algorithm_version", "phase3-seg-v1")
    target = float(seg_cfg["target_length_m"])
    dmin = float(seg_cfg["minimum_length_m"])
    dmax = float(seg_cfg["maximum_length_m"])
    max_mid = float(seg_cfg["maximum_midpoint_distance_from_h3_m"])
    max_detour = float(seg_cfg["maximum_route_detour_ratio"])
    geo_tol = float(seg_cfg["maximum_geometry_length_difference_ratio"])
    bearings = list(seg_cfg["candidate_bearings_deg"])[: int(seg_cfg["maximum_candidates_per_h3"])]

    attempts: list[dict[str, Any]] = []
    best: Optional[dict[str, Any]] = None

    for bearing in bearings:
        a, b = _candidate_endpoints(centroid_lat, centroid_lng, float(bearing), target)
        snap_used = False
        snap_status = "NOT_USED"
        if snap_fn is not None and seg_cfg.get("snap_to_road", {}).get("enabled", False):
            try:
                snapped, _ = snap_fn([a, b])
                if len(snapped) >= 2:
                    a = (snapped[0].lat, snapped[0].lng)
                    b = (snapped[1].lat, snapped[1].lng)
                    snap_used = True
                    snap_status = "SNAPPED"
            except (ProviderError, Exception):
                snap_status = "SNAP_FAILED"

        attempt: dict[str, Any] = {
            "bearing": bearing,
            "endpoint_a": a,
            "endpoint_b": b,
            "snap_used": snap_used,
            "snap_status": snap_status,
            "route_status": "NOT_CALLED",
            "segment_status": "INVALID",
            "reasons": [],
        }
        try:
            route, raw = route_adv_fn(a[0], a[1], b[0], b[1])
            attempt["route_status"] = "OK"
        except ProviderError as exc:
            attempt["route_status"] = exc.provider_status
            attempt["reasons"] = [f"ROUTE_{exc.provider_status}"]
            attempts.append(attempt)
            continue
        except Exception as exc:  # network etc.
            attempt["route_status"] = "ROUTE_ERROR"
            attempt["reasons"] = [type(exc).__name__]
            attempts.append(attempt)
            continue

        geometry_decoded = False
        geometry_status = "NOT_DECODED"
        points: list[tuple[float, float]] = []
        decoded_len = None
        if route.geometry:
            try:
                dec = geo.decode_route_geometry(route.geometry, route.distance_m, geo_tol)
                points = dec["points_latlng"]
                geometry_decoded = True
                geometry_status = dec["status"]
                decoded_len = dec["decoded_length_m"]
            except geo.GeometryError as exc:
                geometry_status = "DECODE_FAILED"
                attempt["reasons"].append(f"GEOMETRY:{exc}")

        if points:
            mid = geo.midpoint(points)
        else:
            mid = (
                (a[0] + b[0]) / 2.0,
                (a[1] + b[1]) / 2.0,
            )
        mid_dist = geo.haversine_m((centroid_lat, centroid_lng), mid)
        straight = geo.haversine_m(a, b)
        detour_ratio = (route.distance_m / straight) if straight > 0 else None
        coords_inside = all(
            sv.inside_bengaluru(p[0], p[1]) for p in (points or [a, b])
        )
        geometry_valid = geometry_decoded and geometry_status == "DECODED" and len(points) >= 2

        valid, reasons = sv.is_valid_segment(
            route_ok=True,
            distance_m=route.distance_m,
            duration_s=route.duration_s,
            geometry_decoded=geometry_decoded,
            geometry_status=geometry_status,
            n_points=len(points),
            distance_min_m=dmin,
            distance_max_m=dmax,
            midpoint_distance_from_h3_m=mid_dist,
            max_midpoint_distance_m=max_mid,
            detour_ratio=detour_ratio,
            max_detour_ratio=max_detour,
            coords_inside_blr=coords_inside,
        )
        attempt["reasons"].extend(reasons)
        attempt["segment_status"] = "VALID" if valid else "INVALID"

        score = sv.score_candidate(
            route_ok=True,
            distance_m=route.distance_m,
            target_length_m=target,
            midpoint_distance_from_h3_m=mid_dist,
            max_midpoint_distance_m=max_mid,
            detour_ratio=detour_ratio,
            geometry_valid=geometry_valid,
            endpoints_valid=coords_inside,
        )
        record = {
            **attempt,
            "route_distance_m": route.distance_m,
            "route_duration_reference_s": route.duration_s,
            "reference_duration_source": "route_adv",
            "road_name": route.road_name,
            "geometry_points": points,
            "geometry_geojson": geo.to_geojson_linestring(points) if len(points) >= 2 else None,
            "decoded_length_m": decoded_len,
            "route_midpoint_latitude": mid[0],
            "route_midpoint_longitude": mid[1],
            "midpoint_distance_from_h3_m": mid_dist,
            "route_detour_ratio": detour_ratio,
            "route_intersects_or_near_h3": mid_dist <= max_mid,
            "segment_quality_score": score,
            "valid": valid,
        }
        attempts.append({k: record[k] for k in attempt})
        if valid and (best is None or score > best["segment_quality_score"]):
            best = record

    if best is None:
        return {
            "h3_res10": h3,
            "resolved": False,
            "segment_status": "UNRESOLVED",
            "attempts": attempts,
        }

    a = best["endpoint_a"]
    b = best["endpoint_b"]
    phys_id = sv.physical_segment_id(h3, a, b, algo)

    # optional reverse geocode of the chosen midpoint
    locality = sub_locality = formatted = None
    if reverse_geocode_fn is not None and seg_cfg.get("reverse_geocode", {}).get("enabled", False):
        try:
            rg, _ = reverse_geocode_fn(best["route_midpoint_latitude"], best["route_midpoint_longitude"])
            locality = rg.locality
            sub_locality = rg.sub_locality
            formatted = rg.formatted_address
        except Exception:
            pass

    directed = []
    created_at = now_ist().isoformat()
    for direction, (sa, sb) in (("A_TO_B", (a, b)), ("B_TO_A", (b, a))):
        directed.append(
            {
                "physical_segment_id": phys_id,
                "directed_segment_id": sv.directed_segment_id(phys_id, direction),
                "h3_res10": h3,
                "direction": direction,
                "endpoint_a_latitude": sa[0],
                "endpoint_a_longitude": sa[1],
                "endpoint_b_latitude": sb[0],
                "endpoint_b_longitude": sb[1],
                "route_distance_m": best["route_distance_m"],
                "route_duration_reference_s": best["route_duration_reference_s"],
                "reference_duration_source": best["reference_duration_source"],
                "route_geometry": best["geometry_geojson"],
                "route_midpoint_latitude": best["route_midpoint_latitude"],
                "route_midpoint_longitude": best["route_midpoint_longitude"],
                "midpoint_distance_from_h3_m": best["midpoint_distance_from_h3_m"],
                "route_intersects_or_near_h3": best["route_intersects_or_near_h3"],
                "route_detour_ratio": best["route_detour_ratio"],
                "snap_used": best["snap_used"],
                "snap_status": best["snap_status"],
                "route_status": best["route_status"],
                "segment_status": "VALID",
                "segment_quality_score": best["segment_quality_score"],
                "segment_algorithm_version": algo,
                "road_name": best["road_name"],
                "locality": locality,
                "sub_locality": sub_locality,
                "formatted_address": formatted,
                "segment_created_at": created_at,
            }
        )

    return {
        "h3_res10": h3,
        "resolved": True,
        "physical_segment_id": phys_id,
        "segment_status": "VALID",
        "directed": directed,
        "attempts": attempts,
        "best": best,
    }
