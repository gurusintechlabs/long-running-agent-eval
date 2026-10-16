"""S(t): cost per accepted commit (docs/spec.md §8.3 row 7).

Costs are the CLI's API-equivalent estimates (D-16). Judge spend is not included (§8.3.6).
"""
from __future__ import annotations

NO_ACCEPTED = "no_accepted_commits"


def cost_metrics(*, cum_cost: float, cum_accepted: int, int_cost: float, int_accepted: int,
                 cum_tokens: int) -> dict:
    """``{"S", "S_int", "tokens_per_commit", "reasons"}``.

    Each value is ``None`` when its denominator is 0 (zero-commit rule), with the reason under
    ``reasons[name]`` (``"no_accepted_commits"``). S is cumulative cost / cumulative accepted
    commits, S_int the same over the interval, tokens_per_commit is cumulative tokens / cumulative
    accepted commits.
    """
    out: dict = {"S": None, "S_int": None, "tokens_per_commit": None, "reasons": {}}
    if cum_accepted > 0:
        out["S"] = cum_cost / cum_accepted
        out["tokens_per_commit"] = cum_tokens / cum_accepted
    else:
        out["reasons"]["S"] = out["reasons"]["tokens_per_commit"] = NO_ACCEPTED
    if int_accepted > 0:
        out["S_int"] = int_cost / int_accepted
    else:
        out["reasons"]["S_int"] = NO_ACCEPTED
    return out
