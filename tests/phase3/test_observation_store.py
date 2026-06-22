from clearlane.phase3.observation_store import ObservationStore, observation_id


def _obs(directed, bucket, dur, valid=True, mode="LIVE"):
    return {
        "directed_segment_id": directed,
        "observation_bucket_ist": bucket,
        "provider": "mappls",
        "data_mode": mode,
        "observed_at_ist": f"{bucket}",
        "live_eta_duration_s": dur,
        "is_valid_observation": valid,
    }


def test_same_segment_same_bucket_not_duplicated(tmp_path):
    store = ObservationStore(tmp_path)
    store.write([_obs("d1", "2026-06-22T10:00:00+0530", 100.0)])
    store.write([_obs("d1", "2026-06-22T10:00:00+0530", 120.0)])
    df = store.read_all()
    rows = df[df["directed_segment_id"] == "d1"]
    assert len(rows) == 1
    assert rows.iloc[0]["live_eta_duration_s"] == 120.0  # replaced, not duplicated


def test_different_bucket_creates_new(tmp_path):
    store = ObservationStore(tmp_path)
    store.write([_obs("d1", "2026-06-22T10:00:00+0530", 100.0)])
    store.write([_obs("d1", "2026-06-22T10:15:00+0530", 110.0)])
    assert len(store.read_all()) == 2


def test_invalid_retained_but_flagged(tmp_path):
    store = ObservationStore(tmp_path)
    store.write([_obs("d1", "2026-06-22T10:00:00+0530", None, valid=False)])
    df = store.read_all()
    assert len(df) == 1
    assert bool(df.iloc[0]["is_valid_observation"]) is False


def test_replay_excluded_from_live_samples(tmp_path):
    store = ObservationStore(tmp_path)
    store.write([_obs("d1", "2026-06-22T10:00:00+0530", 100.0, mode="REPLAY")])
    store.write([_obs("d1", "2026-06-22T10:15:00+0530", 110.0, mode="LIVE")])
    samples = store.valid_live_eta_samples("d1")
    assert len(samples) == 1  # only the LIVE one
    assert samples[0][1] == 110.0


def test_observation_id_stable():
    o = _obs("d1", "2026-06-22T10:00:00+0530", 100.0)
    assert observation_id(o) == observation_id(dict(o))
