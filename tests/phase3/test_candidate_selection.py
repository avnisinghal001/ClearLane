from clearlane.phase3 import candidate_selection as cs


def test_station_filter_and_counts(hotspots, config):
    counts = cs.selection_counts(hotspots, config)
    assert counts["whitefield_h3_cells"] == 161
    assert counts["eligible_whitefield_h3_cells"] == 47
    assert counts["tested_whitefield_h3_cells"] == 40
    assert counts["explicitly_excluded_h3_cells"] == 1


def test_primary_reserve_counts(hotspots, config):
    sel = cs.select_candidates(hotspots, config)
    primary = sel[sel["candidate_tier"] == "PRIMARY"]
    reserve = sel[sel["candidate_tier"] == "RESERVE"]
    assert len(primary) == 20
    assert len(reserve) == 10
    assert set(primary["h3_res10"]).isdisjoint(set(reserve["h3_res10"]))


def test_carmelaram_excluded(hotspots, config):
    sel = cs.select_candidates(hotspots, config)
    assert "8a6189276627fff" not in set(sel["h3_res10"])


def test_only_tested_and_eligible(hotspots, config):
    sel = cs.select_candidates(hotspots, config)
    assert (sel["spatial_test_status"] == "TESTED").all()
    assert (sel["eligible_for_corrected_ranking"] == True).all()  # noqa: E712


def test_corrected_rank_ordering(hotspots, config):
    sel = cs.select_candidates(hotspots, config).sort_values("selection_rank")
    ranks = list(sel["corrected_rank"])
    assert ranks == sorted(ranks)


def test_deterministic(hotspots, config):
    a = list(cs.select_candidates(hotspots, config)["h3_res10"])
    b = list(cs.select_candidates(hotspots, config)["h3_res10"])
    assert a == b
