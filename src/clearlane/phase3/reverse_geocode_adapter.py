"""Reverse Geocode adapter (optional address enrichment / region validation)."""

from __future__ import annotations

from typing import Any

from .mappls_client import MapplsClient
from .response_parsers import ReverseGeocodeResult, parse_reverse_geocode


def call_reverse_geocode(
    client: MapplsClient,
    lat: float,
    lng: float,
    *,
    budget_scope: str = "prepare",
) -> tuple[ReverseGeocodeResult, Any]:
    raw = client.call(
        "rev_geocode",
        client.search_url("address/rev-geocode"),
        {"lat": lat, "lng": lng, "region": client.region(upper=True)},
        budget_scope=budget_scope,
    )
    result = parse_reverse_geocode(raw.body, raw.http_status)
    return result, raw
