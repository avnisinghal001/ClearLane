"""Distance Matrix ETA adapter — primary repeated live source.

Builds an explicit source/destination index map back to directed segments so a
returned matrix cell is only ever interpreted as the exact monitored pair it was
requested for (never an unrelated cross-matrix cell)."""

from __future__ import annotations

from typing import Any

from .matrix_normal_adapter import format_points
from .mappls_client import MapplsClient
from .response_parsers import MatrixResult, parse_matrix


def call_matrix_eta(
    client: MapplsClient,
    points: list[tuple[float, float]],
    *,
    sources: list[int] | None = None,
    destinations: list[int] | None = None,
    budget_scope: str = "poll",
) -> tuple[MatrixResult, Any]:
    path = client.route_url(f"dm/distance_matrix_eta/driving/{format_points(points)}")
    params: dict[str, Any] = {"region": client.region()}
    if sources is not None:
        params["sources"] = ";".join(str(i) for i in sources)
    if destinations is not None:
        params["destinations"] = ";".join(str(i) for i in destinations)
    raw = client.call("distance_matrix_eta", path, params, budget_scope=budget_scope)
    result = parse_matrix(raw.body, raw.http_status)
    return result, raw


def extract_pair(matrix: MatrixResult, source_index: int, dest_index: int) -> tuple[float | None, float | None]:
    """Return (distance_m, duration_s) for an explicit (source, dest) cell, or (None, None)."""
    try:
        dist = matrix.distances[source_index][dest_index]
        dur = matrix.durations[source_index][dest_index]
    except (IndexError, TypeError):
        return None, None
    return (
        float(dist) if dist is not None else None,
        float(dur) if dur is not None else None,
    )
