"""Mappls capability probe.

Probes the verified endpoints with a single small Bengaluru segment and records
known-unavailable products. Concludes which numeric live source and reference
source Phase 3 will use. Native-tile / predictive unavailability must not block.
"""

from __future__ import annotations

from typing import Any, Optional

from .mappls_client import MapplsClient
from .response_parsers import (
    ACCESS_DENIED,
    INVALID_TOKEN,
    RATE_LIMITED,
    UNAUTHORIZED,
    ProviderError,
)

# A small, known Bengaluru segment near MG Road for probing (lat, lng).
PROBE_A = (12.971612, 77.594542)
PROBE_B = (12.975072, 77.599768)

AVAILABLE = "AVAILABLE"
NOT_TESTED = "NOT_TESTED"
NOT_CONFIGURED = "NOT_CONFIGURED"
INVALID_RESPONSE = "INVALID_RESPONSE"
NETWORK_ERROR = "NETWORK_ERROR"

KNOWN_UNAVAILABLE = {
    "ROUTE_TRAFFIC": "ACCESS_DENIED",
    "DISTANCE_MATRIX_TRAFFIC": "ACCESS_DENIED",
    "PREDICTIVE_TRAFFIC": "ACCESS_DENIED",
    "NATIVE_TRAFFIC_TILES": "UNAVAILABLE",
}


def _probe(fn) -> str:
    try:
        fn()
        return AVAILABLE
    except ProviderError as exc:
        return {
            ACCESS_DENIED: "ACCESS_DENIED",
            INVALID_TOKEN: "INVALID_TOKEN",
            UNAUTHORIZED: "UNAUTHORIZED",
            RATE_LIMITED: "RATE_LIMITED",
        }.get(exc.provider_status, INVALID_RESPONSE)
    except FileNotFoundError:
        return NOT_TESTED
    except Exception:
        return NETWORK_ERROR


def run_probe(client: MapplsClient, *, probe_oauth: bool = False) -> dict[str, Any]:
    from .route_adv_adapter import call_route_adv
    from .route_eta_adapter import call_route_eta
    from .matrix_normal_adapter import call_matrix
    from .matrix_eta_adapter import call_matrix_eta
    from .snap_to_road_adapter import call_snap_to_road
    from .reverse_geocode_adapter import call_reverse_geocode

    a, b = PROBE_A, PROBE_B
    results: dict[str, str] = {}

    if not client.credentials.has_rest_key and client.data_mode != "REPLAY":
        results["STATIC_REST_AUTHENTICATION"] = NOT_CONFIGURED
    else:
        results["STATIC_REST_AUTHENTICATION"] = _probe(
            lambda: call_route_adv(client, a[0], a[1], b[0], b[1], budget_scope="prepare")
        )

    results["OAUTH_AUTHENTICATION_OPTIONAL"] = (
        NOT_TESTED if not probe_oauth else (AVAILABLE if client.credentials.has_oauth else NOT_CONFIGURED)
    )
    results["ROUTE_ADV"] = _probe(lambda: call_route_adv(client, a[0], a[1], b[0], b[1], budget_scope="prepare"))
    results["ROUTE_ETA"] = _probe(lambda: call_route_eta(client, a[0], a[1], b[0], b[1], budget_scope="prepare"))
    results["DISTANCE_MATRIX"] = _probe(lambda: call_matrix(client, [a, b], budget_scope="prepare"))
    results["DISTANCE_MATRIX_ETA"] = _probe(lambda: call_matrix_eta(client, [a, b], budget_scope="prepare"))
    results["MULTI_LOCATION_MATRIX_ETA"] = _probe(
        lambda: call_matrix_eta(client, [a, b, PROBE_B], budget_scope="prepare")
    )
    results["REVERSE_GEOCODE"] = _probe(lambda: call_reverse_geocode(client, a[0], a[1], budget_scope="prepare"))
    results["SNAP_TO_ROAD"] = _probe(lambda: call_snap_to_road(client, [a, b], budget_scope="prepare"))

    for name, status in KNOWN_UNAVAILABLE.items():
        results[name] = status

    return build_report(results)


def build_report(results: dict[str, str]) -> dict[str, Any]:
    matrix_eta_ok = results.get("DISTANCE_MATRIX_ETA") == AVAILABLE
    route_eta_ok = results.get("ROUTE_ETA") == AVAILABLE
    matrix_ok = results.get("DISTANCE_MATRIX") == AVAILABLE
    route_adv_ok = results.get("ROUTE_ADV") == AVAILABLE

    numeric_traffic_available = any([matrix_eta_ok, route_eta_ok])

    selected_live: Optional[str] = (
        "distance_matrix_eta" if matrix_eta_ok else ("route_eta" if route_eta_ok else None)
    )
    fallback_live: Optional[str] = "route_eta" if (matrix_eta_ok and route_eta_ok) else None
    selected_reference: Optional[str] = (
        "distance_matrix" if matrix_ok else ("route_adv" if route_adv_ok else None)
    )
    fallback_reference: Optional[str] = "route_adv" if (matrix_ok and route_adv_ok) else None

    return {
        "endpoint_status": results,
        "numeric_live_traffic_available": bool(numeric_traffic_available),
        "selected_live_source": selected_live,
        "fallback_live_source": fallback_live,
        "selected_reference_source": selected_reference,
        "fallback_reference_source": fallback_reference,
        "native_traffic_tiles_available": False,
        "predictive_traffic_available": False,
        "phase3_live_backend_ready": bool(numeric_traffic_available and selected_reference is not None),
    }
