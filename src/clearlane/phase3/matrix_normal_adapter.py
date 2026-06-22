"""Distance Matrix (non-traffic) adapter — reference durations."""

from __future__ import annotations

from typing import Any

from .mappls_client import MapplsClient
from .response_parsers import MatrixResult, parse_matrix


def format_points(points: list[tuple[float, float]]) -> str:
    """points are (lat, lng); Mappls path uses lng,lat;lng,lat."""
    return ";".join(f"{lng},{lat}" for (lat, lng) in points)


def call_matrix(
    client: MapplsClient,
    points: list[tuple[float, float]],
    *,
    sources: list[int] | None = None,
    destinations: list[int] | None = None,
    budget_scope: str = "prepare",
    operation: str = "distance_matrix",
    is_fallback: bool = False,
) -> tuple[MatrixResult, Any]:
    path = client.route_url(f"dm/distance_matrix/driving/{format_points(points)}")
    params: dict[str, Any] = {"region": client.region()}
    if sources is not None:
        params["sources"] = ";".join(str(i) for i in sources)
    if destinations is not None:
        params["destinations"] = ";".join(str(i) for i in destinations)
    raw = client.call(operation, path, params, budget_scope=budget_scope, is_fallback=is_fallback)
    result = parse_matrix(raw.body, raw.http_status)
    return result, raw
