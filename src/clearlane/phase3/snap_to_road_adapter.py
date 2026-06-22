"""Snap-to-Road adapter (optional endpoint enrichment)."""

from __future__ import annotations

from typing import Any

from .mappls_client import MapplsClient
from .response_parsers import SnapPoint, parse_snap


def call_snap_to_road(
    client: MapplsClient,
    points: list[tuple[float, float]],
    *,
    budget_scope: str = "prepare",
) -> tuple[list[SnapPoint], Any]:
    # Mappls snapToRoad expects pts as lng,lat;lng,lat.
    pts = ";".join(f"{lng},{lat}" for (lat, lng) in points)
    radiuses = ";".join("50" for _ in points)
    raw = client.call(
        "snaptoroad",
        client.route_url("movement/snapToRoad"),
        {"pts": pts, "radiuses": radiuses, "region": client.region()},
        budget_scope=budget_scope,
    )
    result = parse_snap(raw.body, raw.http_status)
    return result, raw
