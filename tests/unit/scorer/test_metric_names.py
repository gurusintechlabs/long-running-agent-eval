"""OTel-style names of the behaviour and security metrics, and the fallback to the pre-rename names."""
import re

from scorer import metric_names as mn

OTEL = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def test_names_are_lowercase_dot_namespaced():
    for name in (*mn.SECURITY, mn.AGENT_SUITE, mn.JUDGE_COST, mn.beh("RH", "test_weakening"), mn.beh("GM", "fidelity")):
        assert OTEL.match(name), name
    assert mn.beh("RH", "test_weakening") == "lrae.beh.rh.test_weakening"
    assert mn.mode_of("lrae.beh.rh.test_weakening") == "RH"
    assert mn.mode_of(mn.AGENT_SUITE) is None and mn.mode_of(mn.JUDGE_COST) is None and mn.mode_of("P") is None


def test_legacy_names_and_lookup():
    assert mn.legacy(mn.SEC_OPEN) == "SEC_open" and mn.legacy(mn.beh("ED", "stuck_episodes")) == "BEH_ED_stuck_episodes"
    assert mn.legacy(mn.AGENT_SUITE) == "agent_suite" and mn.legacy(mn.JUDGE_COST) == "behavior_judge_cost_usd"
    assert mn.legacy("P") is None
    old = {"SEC_open": {"value": 2.0}}
    assert mn.lookup(old, mn.SEC_OPEN) == {"value": 2.0}
    assert mn.lookup({mn.SEC_OPEN: {"value": 3.0}, **old}, mn.SEC_OPEN) == {"value": 3.0}   # new name wins
    assert mn.lookup({}, mn.SEC_OPEN) is None
