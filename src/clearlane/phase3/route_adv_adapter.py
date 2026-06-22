"""Route ADV adapter (non-traffic reference route + geometry)."""

from __future__ import annotations

from typing import Any

from .mappls_client import MapplsClient
from .response_parsers import RouteResult, parse_route


def _coords(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> str:
    # Mappls path coordinates are lng,lat;lng,lat
    return f"{a_lng},{a_lat};{b_lng},{b_lat}"


def call_route_adv(
    client: MapplsClient,
    a_lat: float,
    a_lng: float,
    b_lat: float,
    b_lng: float,
    *,
    budget_scope: str = "prepare",
) -> tuple[RouteResult, Any]:
    path = client.route_url(f"direction/route_adv/driving/{_coords(a_lat, a_lng, b_lat, b_lng)}")
    params = {"region": client.region(), "overview": "full", "steps": "false"}
    raw = client.call("route_adv", path, params, budget_scope=budget_scope)
    result = parse_route(raw.body, raw.http_status)
    return result, raw
