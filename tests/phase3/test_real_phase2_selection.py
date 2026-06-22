from clearlane.phase3 import candidate_selection as cs

EXPECTED_PRIMARY = [
    "8a6189219cc7fff", "8a61892086a7fff", "8a6189219ceffff", "8a618920ac1ffff",
    "8a6189218a07fff", "8a6189208687fff", "8a61892191b7fff", "8a618920a987fff",
    "8a6189218867fff", "8a618921d497fff", "8a61892191a7fff", "8a618920e98ffff",
    "8a618921d8d7fff", "8a618921d1a7fff", "8a618920ac07fff", "8a618921d127fff",
    "8a618920a98ffff", "8a618920868ffff", "8a618921d427fff", "8a618921dc4ffff",
]


def test_current_real_selection_matches_expected(hotspots, config):
    sel = cs.select_candidates(hotspots, config)
    primary = sel[sel["candidate_tier"] == "PRIMARY"].sort_values("selection_rank")
    assert list(primary["h3_res10"]) == EXPECTED_PRIMARY
