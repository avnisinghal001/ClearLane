from clearlane.phase3 import retry_policy as rp
from clearlane.phase3.response_parsers import ACCESS_DENIED, INVALID_TOKEN, RATE_LIMITED


def test_401_no_retry():
    d = rp.decide(attempt=1, max_attempts=3, http_status=401)
    assert d.should_retry is False


def test_403_no_retry():
    d = rp.decide(attempt=1, max_attempts=3, http_status=403)
    assert d.should_retry is False


def test_invalid_token_no_retry():
    d = rp.decide(attempt=1, max_attempts=3, provider_status=INVALID_TOKEN)
    assert d.should_retry is False


def test_access_denied_no_retry():
    d = rp.decide(attempt=1, max_attempts=3, provider_status=ACCESS_DENIED)
    assert d.should_retry is False


def test_429_honors_retry_after():
    d = rp.decide(attempt=1, max_attempts=3, http_status=429, retry_after=7.0)
    assert d.should_retry is True
    assert d.delay_seconds == 7.0


def test_429_provider_status():
    d = rp.decide(attempt=1, max_attempts=3, provider_status=RATE_LIMITED)
    assert d.should_retry is True


def test_500_retries_bounded():
    assert rp.decide(attempt=1, max_attempts=3, http_status=500).should_retry is True
    assert rp.decide(attempt=3, max_attempts=3, http_status=500).should_retry is False


def test_timeout_retries_bounded():
    assert rp.decide(attempt=1, max_attempts=3, timeout=True).should_retry is True
    assert rp.decide(attempt=5, max_attempts=3, timeout=True).should_retry is False


def test_invalid_schema_no_blind_retry():
    from clearlane.phase3.response_parsers import INVALID_RESPONSE

    d = rp.decide(attempt=1, max_attempts=3, provider_status=INVALID_RESPONSE)
    assert d.should_retry is False


def test_backoff_growth_capped():
    assert rp.backoff_delay(1, 1.0, 15.0) == 1.0
    assert rp.backoff_delay(2, 1.0, 15.0) == 2.0
    assert rp.backoff_delay(10, 1.0, 15.0) == 15.0
