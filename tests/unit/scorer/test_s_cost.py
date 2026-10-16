import pytest

from scorer.metrics.s_cost import cost_metrics


def test_normal():
    r = cost_metrics(cum_cost=6.0, cum_accepted=3, int_cost=2.0, int_accepted=1, cum_tokens=3000)
    assert r["S"] == pytest.approx(2.0)
    assert r["S_int"] == pytest.approx(2.0)
    assert r["tokens_per_commit"] == pytest.approx(1000)
    assert r["reasons"] == {}


def test_interval_without_commits_keeps_cumulative():
    r = cost_metrics(cum_cost=6.0, cum_accepted=3, int_cost=1.5, int_accepted=0, cum_tokens=90)
    assert r["S"] == pytest.approx(2.0)
    assert r["S_int"] is None and r["reasons"] == {"S_int": "no_accepted_commits"}


def test_zero_commit_rule():
    r = cost_metrics(cum_cost=4.0, cum_accepted=0, int_cost=4.0, int_accepted=0, cum_tokens=500)
    assert r["S"] is None and r["S_int"] is None and r["tokens_per_commit"] is None
    assert set(r["reasons"]) == {"S", "S_int", "tokens_per_commit"}
    assert set(r["reasons"].values()) == {"no_accepted_commits"}


def test_zero_cost_with_commits_is_zero_not_none():
    r = cost_metrics(cum_cost=0.0, cum_accepted=2, int_cost=0.0, int_accepted=2, cum_tokens=0)
    assert r["S"] == 0.0 and r["S_int"] == 0.0
