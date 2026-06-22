"""Geodesic helpers and Mappls route-geometry decoding.

Verified against a real Mappls Route ADV response: geometry is an encoded
polyline at **precision 5** (decoded length 1626.5 m vs provider 1626.2 m). The
decoder returns (lat, lng); GeoJSON output uses (lng, lat) order.
"""

from __future__ import annotations

import math
from typing import Any

EARTH_RADIUS_M = 6371000.0


class GeometryError(RuntimeError):
    pass


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres between (lat, lng) points."""
    lat1, lon1 = a
    lat2, lon2 = b
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def destination_point(lat: float, lng: float, bearing_deg: float, distance_m: float) -> tuple[float, float]:
    """Geodesic destination from (lat, lng) along bearing for distance_m. Returns (lat, lng)."""
    ang = distance_m / EARTH_RADIUS_M
    brg = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lng)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(ang) + math.cos(lat1) * math.sin(ang) * math.cos(brg)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(ang) * math.cos(lat1),
        math.cos(ang) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def decode_polyline(encoded: str, precision: int = 5) -> list[tuple[float, float]]:
    """Decode an encoded polyline to a list of (lat, lng) points.

    Pure-python implementation (no hard dependency on `polyline`). Raises
    GeometryError on malformed input.
    """
    if not encoded:
        raise GeometryError("empty geometry")
    coords: list[tuple[float, float]] = []
    index = 0
    lat = 0
    lng = 0
    factor = float(10 ** precision)
    length = len(encoded)
    try:
        while index < length:
            for is_lat in (True, False):
                result = 1
                shift = 0
                while True:
                    b = ord(encoded[index]) - 63 - 1
                    index += 1
                    result += b << shift
                    shift += 5
                    if b < 0x1F:
                        break
                delta = (~(result >> 1)) if (result & 1) else (result >> 1)
                if is_lat:
                    lat += delta
                else:
                    lng += delta
            coords.append((lat / factor, lng / factor))
    except IndexError as exc:
        raise GeometryError(f"malformed polyline near index {index}") from exc
    return coords


def encode_polyline(points: list[tuple[float, float]], precision: int = 5) -> str:
    """Encode (lat, lng) points to an encoded polyline (inverse of decode_polyline)."""
    factor = 10 ** precision
    result = []
    prev_lat = 0
    prev_lng = 0

    def _encode(value: int) -> str:
        value = ~(value << 1) if value < 0 else (value << 1)
        chunks = []
        while value >= 0x20:
            chunks.append((0x20 | (value & 0x1F)) + 63)
            value >>= 5
        chunks.append(value + 63)
        return "".join(chr(c) for c in chunks)

    out = []
    for lat, lng in points:
        ilat = round(lat * factor)
        ilng = round(lng * factor)
        out.append(_encode(ilat - prev_lat))
        out.append(_encode(ilng - prev_lng))
        prev_lat, prev_lng = ilat, ilng
    return "".join(out)


def line_length_m(points: list[tuple[float, float]]) -> float:
    return sum(haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1))


def to_geojson_linestring(points: list[tuple[float, float]]) -> dict[str, Any]:
    """Convert (lat, lng) points to a GeoJSON LineString (lng, lat order)."""
    if len(points) < 2:
        raise GeometryError("LineString needs at least two points")
    return {
        "type": "LineString",
        "coordinates": [[lng, lat] for (lat, lng) in points],
    }


def decode_route_geometry(
    encoded: str,
    provider_distance_m: float,
    max_diff_ratio: float,
    precision: int = 5,
) -> dict[str, Any]:
    """Decode + validate route geometry.

    Returns a dict with decoded points, geojson, length, and a `status` of
    "DECODED" or "GEOMETRY_DISTANCE_MISMATCH".
    """
    points = decode_polyline(encoded, precision)
    if len(points) < 2:
        raise GeometryError("decoded geometry has fewer than two points")
    length = line_length_m(points)
    status = "DECODED"
    diff_ratio = None
    if provider_distance_m and provider_distance_m > 0:
        diff_ratio = abs(length - provider_distance_m) / provider_distance_m
        if diff_ratio > max_diff_ratio:
            status = "GEOMETRY_DISTANCE_MISMATCH"
    return {
        "points_latlng": points,
        "geojson": to_geojson_linestring(points),
        "decoded_length_m": length,
        "provider_distance_m": provider_distance_m,
        "length_difference_ratio": diff_ratio,
        "status": status,
        "precision": precision,
    }


def midpoint(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Return the point on the line nearest the cumulative half-length."""
    if not points:
        raise GeometryError("no points")
    if len(points) == 1:
        return points[0]
    total = line_length_m(points)
    half = total / 2.0
    acc = 0.0
    for i in range(len(points) - 1):
        seg = haversine_m(points[i], points[i + 1])
        if acc + seg >= half:
            frac = 0.0 if seg == 0 else (half - acc) / seg
            lat = points[i][0] + frac * (points[i + 1][0] - points[i][0])
            lng = points[i][1] + frac * (points[i + 1][1] - points[i][1])
            return (lat, lng)
        acc += seg
    return points[-1]
