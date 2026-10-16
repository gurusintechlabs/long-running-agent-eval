import math

import numpy as np
import pytest

from analysis.survival import headline, headline_text, kaplan_meier, median_ci, summarize

# Worked example: Freireich et al. (1963) 6-MP remission times in weeks, 21 patients, 9 relapses,
# 12 censored (the "+" values). As tabulated in Kleinbaum & Klein, "Survival Analysis" (ch. 1-2)
# and reproduced by R survfit(Surv(time, status) ~ 1):
#   t:    6      7      10     13     16     22     23
#   S(t): 0.857  0.807  0.753  0.690  0.627  0.538  0.448
#   SE:   0.0764 0.0869 0.0963 0.1068 0.1141 0.1282 0.1346   (Greenwood)
# Median survival = 23 weeks.
SIX_MP_T = [6, 6, 6, 7, 10, 13, 16, 22, 23] + [6, 9, 10, 11, 17, 19, 20, 25, 32, 32, 34, 35]
SIX_MP_E = [1] * 9 + [0] * 12
PUBLISHED = {6: (0.857, 0.0764), 7: (0.807, 0.0869), 10: (0.753, 0.0963), 13: (0.690, 0.1068),
             16: (0.627, 0.1141), 22: (0.538, 0.1282), 23: (0.448, 0.1346)}


def test_km_and_greenwood_match_published_6mp():
    km = kaplan_meier(SIX_MP_T, SIX_MP_E)
    for t, (s, se) in PUBLISHED.items():
        i = int(np.nonzero(km.times == t)[0][0])
        assert km.surv[i] == pytest.approx(s, abs=5e-4)
        assert km.surv[i] * math.sqrt(km.greenwood[i]) == pytest.approx(se, abs=5e-4)
    assert km.n_risk[0] == 21 and km.n_event[0] == 3
    assert km.median() == 23.0
    assert km.survival_at(5.9) == 1.0 and km.survival_at(8) == pytest.approx(0.807, abs=1e-3)


def test_loglog_ci_matches_formula_and_is_ordered():
    km = kaplan_meier(SIX_MP_T, SIX_MP_E)
    i = int(np.nonzero(km.times == 23)[0][0])
    s, g = km.surv[i], km.greenwood[i]
    se = math.sqrt(g) / abs(math.log(s))
    z = 1.959964
    assert km.lower[i] == pytest.approx(s ** math.exp(z * se), rel=1e-4)
    assert km.upper[i] == pytest.approx(s ** math.exp(-z * se), rel=1e-4)
    assert np.all(km.lower <= km.surv + 1e-12) and np.all(km.surv <= km.upper + 1e-12)
    assert np.all((km.lower >= 0) & (km.upper <= 1))


def test_median_not_reached():
    km = kaplan_meier([5, 8, 10, 12], [1, 0, 0, 0])
    assert km.median() is None
    assert summarize([5, 8, 10, 12], [1, 0, 0, 0])["median"] is None


def test_bootstrap_seeded_and_deterministic():
    a = median_ci(SIX_MP_T, SIX_MP_E, n_boot=300, seed=7)
    assert a == median_ci(SIX_MP_T, SIX_MP_E, n_boot=300, seed=7)
    lo, hi = a
    assert lo is not None and 6 <= lo <= 23 and (hi is None or hi >= 23)
    all_censored = median_ci([5, 6, 7], [0, 0, 0], n_boot=50)
    assert all_censored == (None, None)


def test_headline_never_reaches_target():
    assert headline(SIX_MP_T, SIX_MP_E) is None            # first event drops the bound below 0.8
    assert "never reaches" in headline_text(None)
    assert headline([100, 200, 300, 400, 500], [1, 0, 0, 0, 0]) is None


def test_headline_event_free_uses_exact_bound():
    # no events: lower one-sided 90% bound = 0.1 ** (1/n_at_risk): n=11 -> 0.812, n=10 -> 0.794
    t = list(range(1, 12))
    # at risk shrinks as runs are censored, so only t=1 (n=11) meets the target
    assert headline(t, [0] * 11) == 1.0
    assert headline([1, 2, 3, 4, 5], [0] * 5) is None       # 0.1 ** (1/5) = 0.63


def test_headline_is_last_time_before_bound_drops():
    # 40 runs: one hazard at 100 s (bound 0.913), six at 300 s (S = 0.825, bound 0.732 < 0.8)
    t = [100.0] + [300.0] * 6 + [500.0] * 33
    e = [1] * 7 + [0] * 33
    km = kaplan_meier(t, e, level_1s=0.90)
    assert km.lower_1s[0] == pytest.approx(0.9128, abs=1e-3) and km.lower_1s[1] == pytest.approx(0.7316, abs=1e-3)
    assert headline(t, e) == 100.0
    assert headline(t, e, target=0.7) == 500.0
    assert "Operating limit" in headline_text(100.0)


def test_input_validation():
    with pytest.raises(ValueError):
        kaplan_meier([], [])
    with pytest.raises(ValueError):
        kaplan_meier([1, 2], [1])


def test_all_events_gives_zero_survival_with_degenerate_ci():
    km = kaplan_meier([1, 2, 3], [1, 1, 1])
    assert km.surv[-1] == 0.0 and km.lower[-1] == 0.0 and km.upper[-1] == 0.0
    assert km.median() == 2.0
