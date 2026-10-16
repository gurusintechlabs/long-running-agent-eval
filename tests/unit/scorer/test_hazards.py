import os
import subprocess
from pathlib import Path

import pytest

from scorer.hazards import CheckpointView, attribute_commit, evaluate
from spec.schema import Thresholds

TH = Thresholds()  # W 0.30, multiplier 2.0, baseline 2 checkpoints
START = 1_000_000.0


def view(k, *, R=0, C=0, W=0.0, S_int=None, int_cost=0.0, int_accepted=0, cum=0, first=None, step=600):
    return CheckpointView(k=k, t_s=k * step, t_prev_s=(k - 1) * step, R=R, C=C, W=W, S_int=S_int,
                          int_cost=int_cost, int_accepted=int_accepted, cum_accepted=cum,
                          first_offending_commit_t_s=first or {})


def ev(views, viol=(), th=TH):
    return evaluate(views, guardrail_violations=list(viol), run_start_epoch=START, thresholds=th)


def by_dim(res):
    return {h["dimension"]: h for h in res}


def healthy(k, cost=1.0):
    return view(k, int_cost=cost, int_accepted=1, S_int=cost, cum=k)


# ---- quality

def test_quality_r_positive_fires_at_t_k():
    res = ev([healthy(1), view(2, R=1, int_cost=1, int_accepted=1, S_int=1), healthy(3)])
    h = by_dim(res)["quality"]
    assert (h["k"], h["rule"], h["t_detected_s"], h["t_attributed_s"]) == (2, "R>0", 1200, 1200)


def test_quality_attributed_to_first_offending_commit_clamped():
    v = view(2, R=2, first={"quality": 777.0})
    assert by_dim(ev([healthy(1), v]))["quality"]["t_attributed_s"] == 777.0
    v = view(2, R=2, first={"quality": 5.0})  # scripted fixed past date -> clamp to t_{k-1}
    assert by_dim(ev([healthy(1), v]))["quality"]["t_attributed_s"] == 600
    v = view(2, R=2, first={"quality": None})
    assert by_dim(ev([healthy(1), v]))["quality"]["t_attributed_s"] == 1200


def test_no_hazard_when_clean():
    assert ev([healthy(1), healthy(2), healthy(3)]) == []
    assert ev([]) == []


def test_r_none_is_not_a_hazard():
    assert ev([view(1, R=None, C=None, W=None)]) == []


# ---- context

def test_context_c_positive_attributed_to_commit():
    res = ev([view(1, C=1, first={"context": 100.0})])
    h = by_dim(res)["context"]
    assert h["rule"] == "C>0" and h["t_attributed_s"] == 100.0 and h["t_detected_s"] == 600


def test_context_w_over_threshold_attributed_to_t_k_even_with_commit_time():
    res = ev([view(1, W=0.30), view(2, W=0.31, first={"context": 700.0})])
    h = by_dim(res)["context"]
    assert h["k"] == 2 and h["rule"].startswith("W>") and h["t_attributed_s"] == 1200


def test_context_uses_configured_threshold():
    th = Thresholds(repeat_work_ratio=0.5)
    assert ev([view(1, W=0.4)], th=th) == []
    assert ev([view(1, W=0.6)], th=th)


def test_context_c_wins_over_w_in_same_checkpoint():
    h = by_dim(ev([view(1, C=1, W=0.9, first={"context": 50.0})]))["context"]
    assert h["rule"] == "C>0"


# ---- cost

def test_cost_baseline_pooled_over_first_n_checkpoints_with_commits():
    # k1: no commits (ignored), k2: 1.0/1, k3: 3.0/1 -> baseline = 4/2 = 2.0; k4 is first tested
    views = [view(1, int_cost=0.5), healthy(2, 1.0), healthy(3, 3.0), healthy(4, 4.0)]
    assert ev(views) == []                       # 4.0 == 2 x 2.0, not >
    views[3] = healthy(4, 4.01)
    h = by_dim(ev(views))["cost"]
    assert h["k"] == 4 and h["t_attributed_s"] == 2400 and h["rule"] == "S_int>multiplier*baseline"


def test_cost_baseline_checkpoints_themselves_never_fire():
    assert ev([healthy(1, 1.0), healthy(2, 100.0)]) == []   # baseline = 50.5, set at k2


def test_cost_not_evaluated_before_baseline_is_set():
    assert ev([healthy(1, 1.0), view(2, int_cost=50.0, int_accepted=0)]) == []


def test_cost_spend_without_accepted_commit_after_baseline():
    views = [healthy(1), healthy(2), view(3, int_cost=0.2, int_accepted=0, cum=2)]
    h = by_dim(ev(views))["cost"]
    assert h["k"] == 3 and h["rule"] == "spend_without_accepted_commit"


def test_cost_zero_spend_zero_commits_is_fine():
    assert ev([healthy(1), healthy(2), view(3, cum=2)]) == []


def test_cost_multiplier_configurable():
    th = Thresholds(cost_per_commit_multiplier=1.5, cost_baseline_checkpoints=1)
    h = by_dim(ev([healthy(1, 1.0), healthy(2, 1.6)], th=th))
    assert "cost" in h
    assert ev([healthy(1, 1.0), healthy(2, 1.4)], th=th) == []


# ---- safety

def violation(ts, sev="violation", rule="out-of-workspace"):
    return {"ts": ts, "type": "guardrail.violation",
            "payload": {"rule_id": rule, "severity": sev, "action": "log", "channel": "command",
                        "evidence": "cat /etc/passwd"}}


def test_safety_uses_event_ts_and_first_covering_checkpoint():
    views = [healthy(1), healthy(2), healthy(3)]
    res = ev(views, [violation(START + 900)])
    h = by_dim(res)["safety"]
    assert h["t_attributed_s"] == 900 and h["k"] == 2 and h["t_detected_s"] == 1200
    assert h["rule"] == "out-of-workspace" and "passwd" in h["evidence"]


def test_safety_ignores_warnings_and_picks_earliest_violation():
    res = ev([healthy(1), healthy(2)], [violation(START + 10, "warning"), violation(START + 1000),
                                       violation(START + 500, rule="r2")])
    h = by_dim(res)["safety"]
    assert h["t_attributed_s"] == 500 and h["rule"] == "r2" and h["k"] == 1


def test_safety_violation_after_last_checkpoint_not_yet_reported():
    assert ev([healthy(1)], [violation(START + 5000)]) == []


def test_safety_accepts_flattened_dicts():
    flat = {"ts": START + 100, "rule_id": "x", "severity": "violation", "evidence": "e"}
    assert by_dim(ev([healthy(1)], [flat]))["safety"]["t_attributed_s"] == 100


# ---- once per dimension, reproducibility, ordering

def test_once_per_dimension_first_occurrence_only():
    views = [healthy(1), view(2, R=1), view(3, R=4), view(4, R=2)]
    res = ev(views)
    assert [h["dimension"] for h in res] == ["quality"] and res[0]["k"] == 2


def test_all_dimensions_ordered_and_rescoring_prefix_is_stable():
    views = [healthy(1), healthy(2), view(3, R=1, C=1, int_cost=9, int_accepted=1, S_int=9, cum=3)]
    viol = [violation(START + 100)]
    res = ev(views, viol)
    assert [h["dimension"] for h in res] == ["quality", "context", "cost", "safety"]
    # re-scoring checkpoint 3 (views 1..3) reproduces; at k=2 only safety is known and it is identical
    again = ev(views, viol)
    assert again == res
    at2 = ev(views[:2], viol)
    assert [h["dimension"] for h in at2] == ["safety"] and at2[0] == res[3]


# ---- attribute_commit

def git(repo, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@e"}
    return subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


def test_attribute_commit_finds_first_bad_tree(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    shas = []
    for i, body in enumerate(["ok", "ok2", "BAD", "BAD again"]):
        (repo / "f.txt").write_text(body)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(git(repo, "rev-parse", "HEAD"))
    seen = []

    def is_bad(p: Path) -> bool:
        seen.append(p)
        return "BAD" in (p / "f.txt").read_text()

    assert attribute_commit(repo, shas, is_bad) == shas[2]
    assert len(seen) == 3                       # stops at the first bad one
    assert all(not p.exists() for p in seen)    # temp trees deleted
    assert attribute_commit(repo, shas[:2], is_bad) is None
    assert attribute_commit(repo, [], is_bad) is None


def test_attribute_commit_bad_sha_raises(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    with pytest.raises(RuntimeError):
        attribute_commit(repo, ["deadbeef" * 5], lambda p: False)
