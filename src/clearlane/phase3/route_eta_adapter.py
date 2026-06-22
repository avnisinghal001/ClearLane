"""Route ETA adapter (traffic-aware live duration — fallback live source)."""

from __future__ import annotations

from typing import Any

from .mappls_client import MapplsClient
from .response_parsers import RouteResult, parse_route


def call_route_eta(
    client: MapplsClient,
    a_lat: float,
    a_lng: float,
    b_lat: float,
    b_lng: float,
    *,
    budget_scope: str = "poll",
) -> tuple[RouteResult, Any]:
    coords = f"{a_lng},{a_lat};{b_lng},{b_lat}"
    path = client.route_url(f"direction/route_eta/driving/{coords}")
    params = {"region": client.region(), "overview": "full", "steps": "false"}
    raw = client.call("route_eta", path, params, budget_scope=budget_scope, is_fallback=True)
    result = parse_route(raw.body, raw.http_status)
    return result, raw
