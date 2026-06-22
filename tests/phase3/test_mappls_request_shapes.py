from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clearlane.phase3.mappls_auth import Credentials
from clearlane.phase3.mappls_client import MapplsClient
from clearlane.phase3.matrix_eta_adapter import call_matrix_eta
from clearlane.phase3.matrix_normal_adapter import call_matrix
from clearlane.phase3.reverse_geocode_adapter import call_reverse_geocode
from clearlane.phase3.route_adv_adapter import call_route_adv
from clearlane.phase3.route_eta_adapter import call_route_eta
from clearlane.phase3.snap_to_road_adapter import call_snap_to_road


class CaptureTransport:
    def __init__(self, body: Any):
        self.body = body
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, params: dict[str, Any]) -> tuple[int, Any]:
        self.calls.append((url, dict(params)))
        return 200, self.body


def _body(fixture_dir: Path, name: str) -> Any:
    return json.loads((fixture_dir / name).read_text(encoding="utf-8"))


def _client(config: dict[str, Any], transport: CaptureTransport) -> MapplsClient:
    creds = Credentials(
        rest_key="TEST_MAPPLS_TOKEN",
        client_id=None,
        client_secret=None,
        access_token=None,
    )
    return MapplsClient(config, creds, transport=transport)


def _assert_token_query_not_path(url: str, params: dict[str, Any]) -> None:
    assert "TEST_MAPPLS_TOKEN" not in url
    assert params["access_token"] == "TEST_MAPPLS_TOKEN"


def test_route_eta_request_matches_mappls_route_direction_shape(config, fixture_dir):
    transport = CaptureTransport(_body(fixture_dir, "route_eta.json"))
    client = _client(config, transport)

    call_route_eta(client, 12.9716, 77.5946, 12.9750, 77.6000, budget_scope="prepare")

    url, params = transport.calls[-1]
    assert url == (
        "https://route.mappls.com/route/direction/route_eta/driving/"
        "77.5946,12.9716;77.6,12.975"
    )
    assert params["region"] == "ind"
    assert params["steps"] == "false"
    assert params["overview"] == "full"
    _assert_token_query_not_path(url, params)


def test_route_adv_request_uses_route_direction_shape(config, fixture_dir):
    transport = CaptureTransport(_body(fixture_dir, "route_adv.json"))
    client = _client(config, transport)

    call_route_adv(client, 12.9716, 77.5946, 12.9750, 77.6000)

    url, params = transport.calls[-1]
    assert url.startswith("https://route.mappls.com/route/direction/route_adv/driving/")
    assert url.endswith("77.5946,12.9716;77.6,12.975")
    assert params["region"] == "ind"
    _assert_token_query_not_path(url, params)


def test_matrix_requests_match_mappls_dm_shape(config, fixture_dir):
    points = [(12.9716, 77.5946), (12.9750, 77.6000)]

    normal_transport = CaptureTransport(_body(fixture_dir, "distance_matrix.json"))
    call_matrix(_client(config, normal_transport), points)
    normal_url, normal_params = normal_transport.calls[-1]
    assert normal_url == (
        "https://route.mappls.com/route/dm/distance_matrix/driving/"
        "77.5946,12.9716;77.6,12.975"
    )
    assert normal_params["region"] == "ind"
    _assert_token_query_not_path(normal_url, normal_params)

    eta_transport = CaptureTransport(_body(fixture_dir, "distance_matrix_eta.json"))
    call_matrix_eta(_client(config, eta_transport), points, sources=[0], destinations=[1])
    eta_url, eta_params = eta_transport.calls[-1]
    assert eta_url == (
        "https://route.mappls.com/route/dm/distance_matrix_eta/driving/"
        "77.5946,12.9716;77.6,12.975"
    )
    assert eta_params["region"] == "ind"
    assert eta_params["sources"] == "0"
    assert eta_params["destinations"] == "1"
    _assert_token_query_not_path(eta_url, eta_params)


def test_client_records_redacted_live_request_audit(config, fixture_dir):
    transport = CaptureTransport(_body(fixture_dir, "route_eta.json"))
    client = _client(config, transport)

    call_route_eta(client, 12.9716, 77.5946, 12.9750, 77.6000, budget_scope="prepare")

    assert client.request_summary()["live_mappls_api_calls_attempted"] == 1
    audit = client.call_history[-1]
    assert audit["hit_mappls_api"] is True
    assert audit["operation"] == "route_eta"
    assert audit["params"]["access_token"] == "***REDACTED***"
    assert "TEST_MAPPLS_TOKEN" not in str(audit)


def test_search_and_snap_requests_match_mappls_shapes(config, fixture_dir):
    rg_transport = CaptureTransport(_body(fixture_dir, "rev_geocode.json"))
    call_reverse_geocode(_client(config, rg_transport), 12.9716, 77.5946)
    rg_url, rg_params = rg_transport.calls[-1]
    assert rg_url == "https://search.mappls.com/search/address/rev-geocode"
    assert rg_params["lat"] == 12.9716
    assert rg_params["lng"] == 77.5946
    assert rg_params["region"] == "IND"
    _assert_token_query_not_path(rg_url, rg_params)

    snap_transport = CaptureTransport(_body(fixture_dir, "snaptoroad.json"))
    call_snap_to_road(
        _client(config, snap_transport),
        [(12.9716, 77.5946), (12.9720, 77.5952), (12.9725, 77.5960)],
    )
    snap_url, snap_params = snap_transport.calls[-1]
    assert snap_url == "https://route.mappls.com/route/movement/snapToRoad"
    assert snap_params["pts"] == "77.5946,12.9716;77.5952,12.972;77.596,12.9725"
    assert snap_params["radiuses"] == "50;50;50"
    assert snap_params["region"] == "ind"
    _assert_token_query_not_path(snap_url, snap_params)
