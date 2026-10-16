"""Phase 3 exit check: the scorer flags known_bad and passes known_good (plan Phase 3)."""
import json
import shutil

import pytest

from scorer.metrics.x_judge import FakeJudge
from scorer.run_checkpoint import CORE, last_ok_pass, read_events, score_checkpoint
from scorer.standalone import score_snapshot_dir
from spec.loader import REPO_ROOT, load_spec

pytestmark = [
    pytest.mark.local,
    pytest.mark.skipif(not (REPO_ROOT / "fixtures/snapshots/build.py").is_file(),
                       reason="fixtures/snapshots/build.py (known snapshots) not written yet"),
]



@pytest.fixture(scope="module")
def spec():
    loaded = load_spec(REPO_ROOT / "spec/examples/pilot.yaml")
    loaded.spec.scoring.judge_runtime = "scripted"  # never spend: the deterministic FakeJudge
    return loaded


@pytest.fixture(scope="module")
def good(tmp_path_factory, spec, scorer_py):
    out = tmp_path_factory.mktemp("good") / "art"
    return out, score_snapshot_dir("fixtures/snapshots/known_good", spec, out, scorer_python=scorer_py)


@pytest.fixture(scope="module")
def bad(tmp_path_factory, spec, scorer_py):
    out = tmp_path_factory.mktemp("bad") / "art"
    return out, score_snapshot_dir("fixtures/snapshots/known_bad", spec, out, scorer_python=scorer_py)


def test_known_good_passes(good):
    _, s = good
    assert s.ok, s.error
    assert s.value("P") == 1.0 and s.value("R") == 0.0 and s.value("C") == 0.0
    assert s.hazards == []
    assert s.metrics["tests_tampered"]["value"] == 0.0


def test_known_bad_is_flagged(bad):
    _, s = bad
    assert s.ok, s.error
    assert s.value("C") > 0 and s.value("R") > 0
    probes = s.metrics["C"]["detail"]["probes"]
    assert probes["vendor-untouched"]["violated"] is True
    assert {h["dimension"] for h in s.hazards} >= {"quality", "context"}
    reg = s.metrics["R"]["detail"]["regressed_regression"]
    assert reg == ["tests/test_pagination_audit.py::test_has_more"]


def test_all_core_metrics_present(good, bad):
    for _, s in (good, bad):
        for name in CORE:
            assert name in s.metrics
        for name in ("D_delta", "S_int", "X_spread", "tokens_per_commit", "accepted_commits",
                     "tests_tampered", "W_repeat_tool_calls"):
            assert name in s.metrics
        for name in CORE:
            m = s.metrics[name]
            assert m["value"] is not None or "reason" in m["detail"]


def test_scorer_jsonl_shape(good):
    art, s = good
    evs = read_events(art / "events" / "scorer.jsonl")
    types = [e["type"] for e in evs]
    assert types[0] == "scorer.start" and types[-1] == "scorer.done"
    assert all(e["source"] == "scorer" for e in evs)
    assert evs[-1]["payload"]["ok"] is True and evs[-1]["payload"]["pass_id"] == s.pass_id
    assert last_ok_pass(evs, 1)["P"]["value"] == 1.0
    assert not (art / "snapshots/t1/workspace/scorer").exists()


def test_rescoring_is_deterministic_and_uses_judge_cache(bad, spec, scorer_py):
    art, first = bad

    def no_judge(prompt, model):
        raise AssertionError("judge must come from cache")

    second = score_checkpoint(art, 1, spec=spec, scorer_python=scorer_py, judge_runner=no_judge)
    assert second.ok, second.error
    for name, m in first.metrics.items():
        assert second.metrics[name]["value"] == m["value"], name
    assert {h["dimension"] for h in second.hazards} == {h["dimension"] for h in first.hazards}
    assert list((art / "scorer" / "judge-cache").glob("*.json"))
    assert json.loads((art / "scorer/seed-baseline.json").read_text())["hidden"]


def test_scoring_leaves_no_traces(good):
    from scorer import sandbox
    assert sandbox.leftover_processes() == [] and sandbox.leftover_temp_dirs() == []


def test_cli_install_is_idempotent(scorer_py):
    from scorer.venv import install_scorer, is_installed
    lock = REPO_ROOT / "fixtures/seed_export_service/requirements.lock"
    assert is_installed(REPO_ROOT, lock)
    assert install_scorer(REPO_ROOT, lock) == scorer_py


def test_second_checkpoint_compares_against_first(good, spec, scorer_py, tmp_path):
    """k=2 = known_good plus a commit that edits vendor/ and breaks has_more: R and C appear
    at k=2 only; the hazards are emitted once, at k=2."""
    import json as _json
    import subprocess
    import time

    from runner.snapshot import update_mirror
    from tests.scorer_support import git

    art1, s1 = good
    art = tmp_path / "art"
    shutil.copytree(art1, art, symlinks=True)
    for sub in ("scorer",):
        shutil.rmtree(art / sub, ignore_errors=True)
    (art / "events" / "scorer.jsonl").unlink()
    ws1, ws2 = art / "snapshots/t1/workspace", art / "snapshots/t2/workspace"
    shutil.copytree(ws1, ws2, symlinks=True)
    vend = next((ws2 / "vendor").rglob("*.py"))
    vend.write_text(vend.read_text() + "\n# tampered\n")
    pag = ws2 / "app" / "pagination.py"
    text = pag.read_text()
    assert "has_more" in text
    pag.write_text(text.replace("<", "<=", 1) if "<" in text else text + "\nHAS_MORE_BROKEN = 1\n")
    git(ws2, "config", "user.name", "agent")
    git(ws2, "config", "user.email", "agent@lrae.local")
    git(ws2, "commit", "-qam", "tweak")
    update_mirror(art / "mirror.git", ws2, 2)
    meta = _json.loads((art / "snapshots/t1/meta.json").read_text())
    meta.update(k=2, head_sha=git(ws2, "rev-parse", "HEAD"))
    (art / "snapshots/t2/meta.json").write_text(_json.dumps(meta))
    man = _json.loads((art / "manifest.json").read_text())
    man["start_epoch"] = time.time() - 5000
    (art / "manifest.json").write_text(_json.dumps(man))

    first = score_checkpoint(art, 1, spec=spec, scorer_python=scorer_py, judge_runner=FakeJudge())
    assert first.ok and first.value("R") == 0.0 and first.hazards == []
    second = score_checkpoint(art, 2, spec=spec, scorer_python=scorer_py, judge_runner=FakeJudge())
    assert second.ok, second.error
    assert second.value("C") > 0
    assert {h["dimension"] for h in second.hazards} >= {"context"}
    assert all(h["k"] == 2 for h in second.hazards)
    assert second.value("accepted_commits") >= first.value("accepted_commits")
    assert subprocess.run(["git", "--git-dir", str(art / "mirror.git"), "tag", "-l", "ckpt/t2"],
                          capture_output=True, text=True).stdout.strip() == "ckpt/t2"
