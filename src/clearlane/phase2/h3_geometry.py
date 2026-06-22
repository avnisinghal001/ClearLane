from __future__ import annotations

from typing import Any

import pandas as pd

from .h3_assignment import h3_library


def _boundary_latlng(cell: str) -> list[tuple[float, float]]:
    h3 = h3_library()
    if hasattr(h3, "cell_to_boundary"):
        return [(float(lat), float(lng)) for lat, lng in h3.cell_to_boundary(cell)]
    return [(float(lat), float(lng)) for lat, lng in h3.h3_to_geo_boundary(cell)]


def h3_boundary_lonlat(cell: str) -> list[list[float]]:
    ring = [[lng, lat] for lat, lng in _boundary_latlng(cell)]
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def h3_centroid_latlng(cell: str) -> tuple[float, float]:
    h3 = h3_library()
    if hasattr(h3, "cell_to_latlng"):
        lat, lng = h3.cell_to_latlng(cell)
    else:
        lat, lng = h3.h3_to_geo(cell)
    return float(lat), float(lng)


def polygon_valid_lonlat(ring: list[list[float]]) -> bool:
    if len(ring) < 4:
        return False
    try:
        from shapely.geometry import Polygon  # type: ignore
    except ImportError:
        return ring[0] == ring[-1]
    poly = Polygon(ring)
    return bool(poly.is_valid and not poly.is_empty and poly.area > 0)


def h3_feature(cell: str, properties: dict[str, Any] | None = None) -> dict[str, Any]:
    ring = h3_boundary_lonlat(cell)
    lat, lng = h3_centroid_latlng(cell)
    props = dict(properties or {})
    props.update({
        "h3_res10": cell,
        "centroid_latitude": lat,
        "centroid_longitude": lng,
        "crs": "EPSG:4326",
        "polygon_valid": polygon_valid_lonlat(ring),
    })
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {
            "type": "Polygon",
            "coordinates": [ring],
        },
    }


def geometry_table(cells: list[str] | pd.Series) -> pd.DataFrame:
    rows = []
    for cell in sorted(set(map(str, cells))):
        feature = h3_feature(cell)
        props = feature["properties"]
        rows.append({
            "h3_res10": cell,
            "centroid_latitude": props["centroid_latitude"],
            "centroid_longitude": props["centroid_longitude"],
            "polygon_valid": props["polygon_valid"],
            "geometry_geojson": feature["geometry"],
        })
    return pd.DataFrame(rows)


def feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "name": "clearlane_phase2_h3_hotspots",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": features,
    }
