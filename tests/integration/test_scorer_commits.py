"""Per-commit hidden scoring and stage-aware runs (docs/interfaces.md §8, §9)."""
import json
import os
import sys

import pytest
import yaml

from runner.orchestrator import Run, RunState
from scorer import commit_scoring
from scorer.determinism import compare_last_two
from scorer.metrics import r_regression
from scorer.run_checkpoint import read_events, score_checkpoint
from spec.loader import load_spec
from tests.scorer_support import APP_OK, HIDDEN_FILES, SEED_FILES, git, make_seed, write_tree

from .pilot_support import REPO, make_pilot_spec, scorer_passes, scorer_venv  # noqa: F401

pytestmark = pytest.mark.local

DT_S, K = 20.0, 3
BROKEN_MAIN = "raise RuntimeError('broken mid-interval')\n"


def _script_with_intra_interval_regression(spec_path, dt_s):
    """The pilot script plus, inside interval 2: good main.py, a broken one, then the fix."""
    sys.path.insert(0, str(REPO / "fixtures" / "scripted"))
    try:
        from build_pilot_script import OVERLAY
    finally:
        sys.path.pop(0)
    spec = yaml.safe_load(spec_path.read_text())
    script = yaml.safe_load(open(spec["agent"]["script"]).read())
    good = (OVERLAY / "app" / "main.py").read_text()
    t2 = dt_s  # start of interval 2
    extra = []
    for i, (content, msg) in enumerate([(good, "export route"), (BROKEN_MAIN, "refactor main"),
                                        (good, "fix main")]):
        at = t2 + 1.0 + 2.5 * i
        extra += [{"at": at, "do": "write_file", "path": "app/config.py",
                   "content": (OVERLAY / "app" / "config.py").read_text()},
                  {"at": at + 0.02, "do": "write_file", "path": "app/ratelimit.py",
                   "content": (OVERLAY / "app" / "ratelimit.py").read_text()},
                  {"at": at + 0.05, "do": "write_file", "path": "app/main.py", "content": content},
                  {"at": at + 0.3, "do": "git_commit", "message": msg}]
    script["actions"] = sorted(script["actions"] + extra, key=lambda a: a.get("at", 0))
    new = spec_path.parent / "regression_agent.yaml"
    new.write_text(yaml.safe_dump(script))
    spec["agent"]["script"] = str(new)
    spec_path.write_text(yaml.safe_dump(spec, sort_keys=False))


def _commit_events(art, k):
    """scorer.commit payloads of the last ok pass of checkpoint k."""
    events = read_events(art / "events" / "scorer.jsonl")
    ok = [e["payload"]["pass_id"] for e in events
          if e["type"] == "scorer.done" and e["payload"]["k"] == k and e["payload"]["ok"]]
    return [e["payload"] for e in events if e["type"] == "scorer.commit"
            and e["payload"]["pass_id"] == ok[-1]]


def _strip(p):
    return {n: v for n, v in p.items() if n not in ("pass_id", "cached")}


def test_commit_events_expose_an_intra_interval_regression(tmp_path, scorer_venv):  # noqa: F811
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (tmp_path / "claude").mkdir()
    spec_path = make_pilot_spec(tmp_path, dt_s=DT_S, k=K)
    _script_with_intra_interval_regression(spec_path, DT_S)
    loaded = load_spec(spec_path, repo_root=repo_root)
    run = Run(loaded, "A", 0, repo_root=repo_root, claude_home=tmp_path / "claude",
              host_home=tmp_path / "home", caffeinate=False, score=True)
    res = run.execute()
    assert res.state == RunState.COMPLETED, res.error
    art = res.paths.art
    events = read_events(art / "events" / "scorer.jsonl")

    # every scorer.commit comes before its pass's scorer.done
    done_at = {e["payload"]["pass_id"]: i for i, e in enumerate(events) if e["type"] == "scorer.done"}
    for i, e in enumerate(events):
        if e["type"] == "scorer.commit":
            assert i < done_at[e["payload"]["pass_id"]]

    c2 = _commit_events(art, 2)
    assert len(c2) == 4                       # good, broken, fix, and the script's own step
    assert all(c["stage"] is None and c["sampled"] is False for c in c2)
    p = [c["P"] for c in c2]
    assert p[0] > 0 and p[1] == 0.0 and p[2] == p[0] == p[3], p
    assert all(0.0 <= c["t_s"] and c["t_s"] <= 2 * DT_S for c in c2)
    assert [c["t_s"] for c in c2] == sorted(c["t_s"] for c in c2)

    # the checkpoint-level view cannot see it: P and R at t2 only compare t1 with t2 ...
    passes = scorer_passes(art)
    assert passes[2]["metrics"]["R"] == 0.0 and passes[2]["metrics"]["P"] == pytest.approx(p[-1])
    # ... but consecutive commit outcomes show a hidden-suite regression (and a regression-suite one)
    reg_hidden = r_regression.count_regressions(c2[0]["hidden"], c2[1]["hidden"])
    reg_pristine = r_regression.count_regressions(c2[0]["regression"], c2[1]["regression"])
    assert reg_hidden and reg_pristine
    assert not r_regression.count_regressions(c2[1]["hidden"], c2[2]["hidden"])  # the fix restores

    # checkpoints with one commit still get one event; the pilot has hidden P tiers in detail
    assert len(_commit_events(art, 1)) == 1 and len(_commit_events(art, 3)) == 1
    p_metric = next(e for e in events if e["type"] == "scorer.metric" and e["payload"]["name"] == "P")
    assert set(p_metric["payload"]["detail"]["tiers"]) == set(p_metric["payload"]["detail"]["outcomes"])

    # re-scoring is deterministic: same metrics, and the same commit events thanks to the cache
    before = [_strip(c) for c in c2]
    again = score_checkpoint(art, 2, spec=loaded, scorer_python=scorer_venv)
    assert again.ok, again.error
    assert compare_last_two(art).get(2) is None
    after = [_strip(c) for c in _commit_events(art, 2)]
    assert after == before
    assert all(c["cached"] for c in _commit_events(art, 2)) and not any(c["cached"] for c in c2)
    cache = json.loads((art / "scorer" / "commit-cache.json").read_text())
    assert cache["trees"] and cache["plans"]


# -- stage-aware, sampled and budget-limited per-commit scoring on a tiny synthetic repo -----------

STAGED_HIDDEN = {
    **HIDDEN_FILES,
    "test_t02_late.py": (
        "import os\nimport urllib.request\n\nimport pytest\n\n"
        "@pytest.mark.skipif(int(os.environ.get('LRAE_STAGE', '9')) < 1, reason='not yet')\n"
        "def test_late():\n"
        "    assert urllib.request.urlopen(os.environ['LRAE_APP_URL'] + '/late').read() == b'late'\n"),
}


def _mirror(tmp_path, apps, dates):
    """A repo with one commit per app.py text (committer date per commit); returns (git dir, shas)."""
    repo = write_tree(tmp_path / "repo", SEED_FILES)
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    shas = [git(repo, "rev-parse", "HEAD")]
    for i, (app, date) in enumerate(zip(apps, dates, strict=True)):
        (repo / "app.py").write_text(app)
        git(repo, "add", "-A")
        os.environ["GIT_COMMITTER_DATE"] = date
        try:
            git(repo, "commit", "-q", "-m", f"c{i}")
        finally:
            os.environ.pop("GIT_COMMITTER_DATE", None)
        shas.append(git(repo, "rev-parse", "HEAD"))
    return repo / ".git", shas


@pytest.fixture
def scorer_py_():
    from scorer.venv import install_scorer
    return install_scorer(REPO, REPO / "fixtures" / "seed_export_service" / "requirements.lock")


def test_commits_use_their_own_stage_and_are_cached_by_tree_and_stage(tmp_path, scorer_py_):
    app_late = APP_OK.replace('"/b": "b"}', '"/b": "b", "/late": "late"}')
    start = 1_700_000_000
    # commits at t = 10, 30, 50 s after the run start; stage 1 is delivered at t = 25
    dates = [f"@{start + t} +0000" for t in (10, 30, 50)]
    mirror, shas = _mirror(tmp_path, [APP_OK, app_late, app_late + "\n# touch\n"], dates)
    hidden = write_tree(tmp_path / "hidden", STAGED_HIDDEN)
    seed_ws = make_seed(tmp_path / "seed")
    accepted = r_regression.AcceptedCache(tmp_path / "scorer" / "accepted.json")
    cache = commit_scoring.CommitCache(tmp_path / "scorer" / "commit-cache.json")
    kw = dict(mirror=mirror, prev_sha=shas[0], cur_sha=shas[3], t_prev=0.0, t_k=60.0,
              start_epoch=float(start), timeline=[(25.0, 1)], staged=True, hidden=hidden,
              seed_ws=seed_ws, python=scorer_py_, accepted=accepted, cache=cache, forbid=[tmp_path / "x"],
              est_commit_s=1.0)
    first = commit_scoring.score_commits(**kw)
    ev = first.events
    assert [e["stage"] for e in ev] == [0, 1, 1] and [e["t_s"] for e in ev] == [10.0, 30.0, 50.0]
    # stage 0: 'late' is skipped and not counted; stage 1: active and passing only from c1 on
    assert (ev[0]["passed"], ev[0]["total"], ev[0]["skipped"], ev[0]["P"]) == (2, 2, 1, 1.0)
    assert (ev[1]["passed"], ev[1]["total"], ev[1]["P"]) == (3, 3, 1.0)
    assert ev[0]["hidden"]["test_t02_late.py::test_late"] == "skipped"
    assert ev[0]["regression"] and set(ev[0]["regression"].values()) == {"passed"}
    assert not any(e["cached"] for e in ev) and first.n_computed == 3
    # the same trees are reused from the cache; the regression run was stored in the accepted cache
    second = commit_scoring.score_commits(**kw)
    assert second.n_computed == 0 and all(e["cached"] for e in second.events)
    assert [_strip(e) for e in second.events] == [_strip(e) for e in ev]
    assert all("outcomes" in rec for rec in accepted.data.values())
    # a stage change on an identical tree is a different cache key
    kw2 = dict(kw, timeline=[(0.0, 1)])
    third = commit_scoring.score_commits(**dict(kw2, cache=commit_scoring.CommitCache(tmp_path / "c2.json")))
    assert [e["stage"] for e in third.events] == [1, 1, 1] and third.events[0]["P"] < 1.0


def test_budget_limits_and_flags_sampling_and_the_plan_is_sticky(tmp_path, scorer_py_):
    start = 1_700_000_000
    apps = [APP_OK + f"\n# {i}\n" for i in range(6)]
    mirror, shas = _mirror(tmp_path, apps, [f"@{start + 5 * i} +0000" for i in range(6)])
    hidden = write_tree(tmp_path / "hidden", HIDDEN_FILES)
    kw = dict(mirror=mirror, prev_sha=shas[0], cur_sha=shas[-1], t_prev=0.0, t_k=60.0,
              start_epoch=float(start), timeline=[], staged=False, hidden=hidden,
              seed_ws=make_seed(tmp_path / "seed"), python=scorer_py_, forbid=[tmp_path / "x"],
              accepted=r_regression.AcceptedCache(tmp_path / "a.json"),
              cache=commit_scoring.CommitCache(tmp_path / "c.json"))
    tight = commit_scoring.score_commits(**kw, est_commit_s=100.0, max_scoring_s=200.0, workers=1)
    assert len(tight.events) == 2 and tight.budget_limited
    assert all(e["sampled"] and e["budget_limited"] and e["stage"] is None for e in tight.events)
    assert [e["sha"] for e in tight.events] == [shas[1], shas[-1]]
    # a re-score with a different time estimate keeps the recorded plan
    again = commit_scoring.score_commits(**kw, est_commit_s=0.1, max_scoring_s=200.0)
    assert [e["sha"] for e in again.events] == [e["sha"] for e in tight.events]
    # a fresh cache with a roomy budget scores them all, unflagged
    roomy = commit_scoring.score_commits(**dict(kw, cache=commit_scoring.CommitCache(tmp_path / "d.json")),
                                         est_commit_s=1.0)
    assert len(roomy.events) == 6 and not roomy.budget_limited
    assert not any(e["sampled"] for e in roomy.events)


def test_intra_interval_regression_reaches_the_degradation_analysis(tmp_path, scorer_venv):  # noqa: F811
    """End to end: run -> per-commit scoring -> ingest -> degradation analysis sees the break and the
    fix inside interval 2, in commit order (the scripted commits share one timestamp)."""
    from analysis import degradation
    from analysis.ingest import ingest
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (tmp_path / "claude").mkdir()
    spec_path = make_pilot_spec(tmp_path, dt_s=DT_S, k=K)
    _script_with_intra_interval_regression(spec_path, DT_S)
    run = Run(load_spec(spec_path, repo_root=repo_root), "A", 0, repo_root=repo_root,
              claude_home=tmp_path / "claude", host_home=tmp_path / "home", caffeinate=False, score=True)
    res = run.execute()
    assert res.state == RunState.COMPLETED, res.error
    db = tmp_path / "m.sqlite"
    ingest(repo_root / "runs", db)
    flips = degradation.flip_events(db, res.run_id)
    regressions = [f for f in flips if f.kind == "regression"]
    recoveries = [f for f in flips if f.kind == "recovery"]
    assert regressions, "the broken commit must show up as regressions"
    assert {f.test_id for f in recoveries} >= {f.test_id for f in regressions}
    m = degradation.load_matrix(db, res.run_id)
    commits_k2 = [p for p in m.points if p.point == "commit" and p.k == 2]
    assert [p.sha for p in commits_k2] == [c["sha"] for c in _commit_events(res.paths.art, 2)]
    summary = degradation.run_summary(db, res.run_id)
    assert summary["regressions"] >= len(regressions) > 0
