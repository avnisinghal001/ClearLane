from clearlane.phase3 import capability_probe as cap


def test_matrix_and_route_eta_available():
    results = {
        "ROUTE_ADV": "AVAILABLE", "ROUTE_ETA": "AVAILABLE",
        "DISTANCE_MATRIX": "AVAILABLE", "DISTANCE_MATRIX_ETA": "AVAILABLE",
    }
    rpt = cap.build_report(results)
    assert rpt["numeric_live_traffic_available"] is True
    assert rpt["selected_live_source"] == "distance_matrix_eta"
    assert rpt["fallback_live_source"] == "route_eta"
    assert rpt["selected_reference_source"] == "distance_matrix"
    assert rpt["fallback_reference_source"] == "route_adv"
    assert rpt["phase3_live_backend_ready"] is True


def test_strict_traffic_denied_does_not_block():
    rpt = cap.build_report({"DISTANCE_MATRIX_ETA": "AVAILABLE", "DISTANCE_MATRIX": "AVAILABLE"})
    assert rpt["native_traffic_tiles_available"] is False
    assert rpt["predictive_traffic_available"] is False
    assert rpt["phase3_live_backend_ready"] is True


def test_route_eta_fallback_when_no_matrix_eta():
    rpt = cap.build_report({"ROUTE_ETA": "AVAILABLE", "ROUTE_ADV": "AVAILABLE"})
    assert rpt["selected_live_source"] == "route_eta"
    assert rpt["selected_reference_source"] == "route_adv"
    assert rpt["numeric_live_traffic_available"] is True


def test_both_eta_unavailable_not_ready():
    rpt = cap.build_report({"ROUTE_ADV": "AVAILABLE", "DISTANCE_MATRIX": "AVAILABLE"})
    assert rpt["numeric_live_traffic_available"] is False
    assert rpt["phase3_live_backend_ready"] is False


def test_replay_probe_uses_fixtures(config, root, fixture_dir):
    from clearlane.phase3.mappls_auth import load_credentials
    from clearlane.phase3.mappls_client import MapplsClient, REPLAY

    creds = load_credentials(config, env={})
    client = MapplsClient(config, creds, data_mode=REPLAY, replay_dir=fixture_dir)
    rpt = cap.run_probe(client)
    assert rpt["endpoint_status"]["DISTANCE_MATRIX_ETA"] == "AVAILABLE"
    assert rpt["endpoint_status"]["ROUTE_ETA"] == "AVAILABLE"
