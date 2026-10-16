import math

import pytest

from analysis import trends
from analysis.ingest import ingest
from tests.unit.analysis import synth
from tests.unit.analysis.synth import make_run, score_pass


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("telemetry.counters.interval_counters", synth.fake_counters)
    r = tmp_path / "runs"
    make_run(r, repeat=1, n_cp=3)
    # run 2: its pass at k=3 has a null P and different values
    p3 = score_pass(3, "z", value=0.9)
    p3 = [e for e in p3 if not (e["type"] == "scorer.metric" and e["payload"]["name"] == "P")]
    p3.insert(1, {"type": "scorer.metric", "payload": {"k": 3, "pass_id": "z", "name": "P", "value": None,
                                                       "detail": {"reason": "x"}}})
    make_run(r, repeat=2, n_cp=3, dt=600.0, extra_passes=[p3])
    make_run(r, repeat=3, n_cp=3, dt=600.0, extra_passes=[score_pass(3, "y", value=0.1)])
    ingest(r, tmp_path / "m.sqlite")
    return tmp_path / "m.sqlite"


def test_series_aligned_per_run_and_metric(db):
    series = trends.metric_series(db, "exp-one")
    assert len(series) == 3 * 7
    s = next(x for x in series if x.name == "P" and "r01" in x.run_id)
    assert s.k == [1, 2, 3] and s.t_s == [600.0, 1200.0, 1800.0]
    assert s.value == pytest.approx([0.51, 0.52, 0.53])
    nul = next(x for x in series if x.name == "P" and "r02" in x.run_id)
    assert math.isnan(nul.value[2]) and nul.value[0] == pytest.approx(0.51)


def test_median_by_k_ignores_nulls(db):
    series = trends.metric_series(db, "exp-one")
    ks, ts, med = trends.median_by_k(series, "P")
    assert ks == [1, 2, 3] and ts == [600.0, 1200.0, 1800.0]
    # k=3: values 0.53, null, 0.13 -> median of the two = 0.33
    assert med == pytest.approx([0.51, 0.52, 0.33])
    ks, _, med = trends.median_by_k(series, "R")
    assert med == pytest.approx([0.5, 0.5, 0.5])
    assert trends.median_by_k(series, "nope") == ([], [], [])


def test_fill_pairs_and_counter_series(db):
    pairs = trends.fill_pairs(db, "exp-one", "P")
    assert len(pairs) == 3 * 3 - 1                      # the null P is dropped
    assert pairs[0] == ("exp-one-A-r01-abcd1234", 1, pytest.approx(0.1), pytest.approx(0.51))
    cs = trends.counter_series(db, "exp-one", "context_fill_max")
    assert cs["exp-one-A-r01-abcd1234"][0] == [600.0, 1200.0, 1800.0]
