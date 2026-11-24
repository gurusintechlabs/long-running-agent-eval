"""Names of the behaviour and security metrics, in OpenTelemetry style (lowercase, dot-namespaced,
snake_case leaves): ``lrae.sec.<name>`` and ``lrae.beh.<mode>.<name>``.

The core metrics (``P R D C W X S`` and their auxiliaries) keep their names. Runs scored before the
rename (2026-10-20) used ``SEC_<name>``, ``BEH_<MODE>_<name>``, ``agent_suite`` and
``behavior_judge_cost_usd``; readers that look at earlier passes accept those through :func:`legacy`.
"""
from __future__ import annotations

SEC_NEW = "lrae.sec.new"
SEC_OPEN = "lrae.sec.open"
SEC_EXPLOITS = "lrae.sec.exploits"
SEC_EXPLOITS_INHERITED = "lrae.sec.exploits_inherited"   # of SEC_EXPLOITS: marked inherited from the seed
SEC_AI = "lrae.sec.ai"
SECURITY = (SEC_NEW, SEC_OPEN, SEC_EXPLOITS, SEC_EXPLOITS_INHERITED, SEC_AI)
AGENT_SUITE = "lrae.beh.agent_suite.failing"     # D-24: failing tests of the agent's own suite
JUDGE_COST = "lrae.beh.judge.cost_usd"           # behaviour judges' spend, never part of S
BEH_PREFIX = "lrae.beh."
SEC_PREFIX = "lrae.sec."
# J1: copy similarity of a clean-room rewrite against the scorer's decompilation (scorer/clean_room.py)
CR_PREFIX = "lrae.cr."
CR_STRUCTURAL = "lrae.cr.structural"   # identifiers and literals normalised: survives renaming
CR_LEXICAL = "lrae.cr.lexical"         # identifiers kept
CLEAN_ROOM = (CR_STRUCTURAL, CR_LEXICAL)


def beh(mode: str, name: str) -> str:
    """``lrae.beh.<mode>.<name>`` for a behaviour mode id (``RH`` -> ``rh``)."""
    return f"{BEH_PREFIX}{mode.lower()}.{name}"


def mode_of(name: str) -> str | None:
    """The mode id (upper case) of a per-mode behaviour metric, else None."""
    parts = name.split(".")
    if len(parts) == 4 and name.startswith(BEH_PREFIX) and len(parts[2]) == 2:
        return parts[2].upper()
    return None


def legacy(name: str) -> str | None:
    """The pre-rename name of a metric, or None if it had none."""
    if name == AGENT_SUITE:
        return "agent_suite"
    if name == JUDGE_COST:
        return "behavior_judge_cost_usd"
    if name.startswith(SEC_PREFIX):
        return "SEC_" + name[len(SEC_PREFIX):]
    mode = mode_of(name)
    if mode:
        return f"BEH_{mode}_{name.split('.', 3)[3]}"
    return None


def lookup(metrics: dict, name: str):
    """``metrics[name]``, falling back to the legacy name (passes written before the rename)."""
    if name in metrics:
        return metrics[name]
    old = legacy(name)
    return metrics.get(old) if old else None
