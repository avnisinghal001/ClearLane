import pytest

from clearlane.phase3.api_budget import ALLOWED, BLOCKED, ApiBudget, BudgetExceeded


def _budget(**kw):
    base = dict(
        maximum_prepare_requests_per_run=5,
        maximum_requests_per_poll_cycle=3,
        maximum_route_eta_fallbacks_per_cycle=1,
        maximum_requests_per_day=8,
    )
    base.update(kw)
    return ApiBudget(**base)


def test_counted_before_execution():
    b = _budget()
    assert b.attempted == 0
    b.reserve(scope="poll")
    assert b.attempted == 1 and b.cycle_used == 1 and b.day_used == 1


def test_prepare_budget_enforced():
    b = _budget(maximum_prepare_requests_per_run=2)
    b.reserve(scope="prepare")
    b.reserve(scope="prepare")
    with pytest.raises(BudgetExceeded):
        b.reserve(scope="prepare")


def test_poll_cycle_budget_enforced():
    b = _budget(maximum_requests_per_poll_cycle=2)
    b.reserve(scope="poll")
    b.reserve(scope="poll")
    with pytest.raises(BudgetExceeded):
        b.reserve(scope="poll")


def test_daily_budget_enforced():
    b = _budget(maximum_requests_per_day=2, maximum_requests_per_poll_cycle=10)
    b.reserve(scope="poll")
    b.reserve(scope="poll")
    with pytest.raises(BudgetExceeded):
        b.reserve(scope="poll")


def test_fallback_counted_and_capped():
    b = _budget(maximum_route_eta_fallbacks_per_cycle=1, maximum_requests_per_poll_cycle=10)
    b.reserve(scope="poll", is_fallback=True)
    assert b.fallback_requests == 1
    with pytest.raises(BudgetExceeded):
        b.reserve(scope="poll", is_fallback=True)


def test_check_does_not_mutate():
    b = _budget(maximum_requests_per_poll_cycle=1)
    b.reserve(scope="poll")
    assert b.check(scope="poll") == BLOCKED
    assert b.cycle_used == 1  # check did not increment


def test_prevented_request_not_counted():
    b = _budget(maximum_prepare_requests_per_run=1)
    b.reserve(scope="prepare")
    with pytest.raises(BudgetExceeded):
        b.reserve(scope="prepare")
    assert b.prepare_used == 1  # blocked one not counted
