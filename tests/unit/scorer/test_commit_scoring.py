from scorer import commit_scoring as cs


def _ev(stage, t):
    return {"type": "stage.delivered", "payload": {"stage": stage, "t_s": t}}


def test_stage_is_the_last_delivered_at_or_before_t():
    tl = cs.stage_timeline([{"type": "checkpoint", "payload": {"k": 1}}, _ev(2, 50.0), _ev(1, 20.0),
                            {"type": "stage.delivered", "payload": {"stage": "x"}}])
    assert tl == [(20.0, 1), (50.0, 2)]
    assert [cs.stage_at(tl, t) for t in (0, 19.9, 20.0, 49.0, 50.0, 1e6)] == [0, 0, 1, 1, 2, 2]
    assert cs.stage_at([], 10) == 0


def test_stage_for_is_none_without_a_stages_file():
    evs = [_ev(1, 5.0)]
    assert cs.stage_for(evs, 10.0, staged=False) is None
    assert cs.stage_for(evs, 10.0, staged=True) == 1
    assert cs.stage_for([], 10.0, staged=True) == 0


def test_plan_samples_evenly_and_keeps_the_last_commit_when_tiny():
    commits = [f"c{i}" for i in range(10)]
    assert cs._plan(commits, 40) == commits
    assert cs._plan(commits, 1) == ["c9"]
    p = cs._plan(commits, 4)
    assert len(p) == 4 and p[0] == "c0" and p[-1] == "c9"


def test_cache_roundtrip(tmp_path):
    c = cs.CommitCache(tmp_path / "scorer" / "commit-cache.json")
    c.trees["t:1"] = {"P": 1.0}
    c.plans["a..b"] = ["x"]
    c.save()
    d = cs.CommitCache(tmp_path / "scorer" / "commit-cache.json")
    assert d.trees == c.trees and d.plans == c.plans
