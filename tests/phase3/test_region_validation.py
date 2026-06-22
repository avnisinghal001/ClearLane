from clearlane.phase3 import region_validation as rv


def _cfg():
    return {
        "region": {
            "approximate_demo_bbox": {
                "minimum_latitude": 12.93, "maximum_latitude": 13.00,
                "minimum_longitude": 77.70, "maximum_longitude": 77.77,
            },
            "explicitly_excluded_h3": [{"h3_res10": "8a6189276627fff", "reason": "OUTSIDE_WHITEFIELD_DEMO_REGION"}],
        }
    }


def test_inside_bbox_passes():
    res = rv.validate_row("h1", 12.98, 77.73, _cfg(), {})
    assert res["inside_demo_bbox"] is True
    assert res["region_validation_status"] == rv.STATUS_PASSED


def test_outside_bbox_excluded():
    res = rv.validate_row("h2", 12.50, 77.50, _cfg(), {})
    assert res["region_validation_status"] == rv.STATUS_EXCLUDED_BBOX


def test_explicit_exclusion_wins():
    excluded = {"8a6189276627fff": "OUTSIDE_WHITEFIELD_DEMO_REGION"}
    res = rv.validate_row("8a6189276627fff", 12.98, 77.73, _cfg(), excluded)
    assert res["region_validation_status"] == rv.STATUS_EXCLUDED_EXPLICIT


def test_reverse_geocode_failure_is_not_deletion():
    # reverse_geocode None means unavailable; candidate still PASSED, not deleted
    res = rv.validate_row("h1", 12.98, 77.73, _cfg(), {}, reverse_geocode=None)
    assert res["region_validation_status"] == rv.STATUS_PASSED


def test_reverse_geocode_enriches():
    rg = {"locality": "Whitefield", "subLocality": "ITPL", "formatted_address": "ITPL, Whitefield"}
    res = rv.validate_row("h1", 12.98, 77.73, _cfg(), {}, reverse_geocode=rg)
    assert res["reverse_geocoded_locality"] == "Whitefield"
