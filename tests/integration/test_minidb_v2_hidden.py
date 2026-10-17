"""minidb v2 (L3, staged): run the hidden suite for real against the per-stage references.

For every stage s, the reference ``minidb_v2_s{s}`` passes every test active at LRAE_STAGE=s; the
bare seed fails cleanly; each reference fails most of the next stage's new tests (stages add real
work); and around each change request the old reference fails the replacement tests while the new
reference fails exactly the retired ones (the retired tests pin the old behaviour). Local
subprocesses only, no API spend (about 4-5 minutes).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from runner.seed import ensure_seed_repo
from runner.stages import load_stages
from spec.loader import REPO_ROOT, load_spec
from tests.unit.test_minidb_v2_fixtures import STAGES, active, hidden_tests

pytestmark = pytest.mark.local

SPEC = REPO_ROOT / "spec" / "examples" / "minidb-v2.yaml"
SEED = REPO_ROOT / "fixtures" / "seed_minidb"
HIDDEN = REPO_ROOT / "fixtures" / "tasks" / "minidb_v2" / "hidden"
N_STAGES = 7
UNTERMINATED_TEST = "tests/test_cli.py::test_unterminated_string_literal_is_an_error_not_a_crash"
SUITE_BUDGET_S = 120


def _load_build():
    import importlib.util
    spec = importlib.util.spec_from_file_location("snapshots_build_minidb_v2_it",
                                                  REPO_ROOT / "fixtures/snapshots/build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _python() -> str:
    venvs = sorted(REPO_ROOT.glob("tools/scorer-venv*/bin/python"))
    return str(venvs[0]) if venvs else sys.executable


def _junit(path: Path) -> dict[str, str]:
    outcomes = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        tid = f"{case.get('classname', '').replace('.', '/')}.py::{case.get('name', '')}"
        if case.find("failure") is not None:
            outcomes[tid] = "failed"
        elif case.find("error") is not None:
            outcomes[tid] = "error"
        elif case.find("skipped") is not None:
            outcomes[tid] = "skipped"
        else:
            outcomes[tid] = "passed"
    return outcomes


def _env(home: Path, **extra: str) -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "TMPDIR": str(home),
           "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    env.update(extra)
    return env


def run_hidden(ws: Path, tmp: Path, stage: int | None, select: list[str] | None = None) -> dict[str, str]:
    """Run (a selection of) the hidden suite the way the scorer does; return outcomes by id."""
    py = _python()
    tmp.mkdir(parents=True, exist_ok=True)
    report = tmp / "hidden.xml"
    extra = {"LRAE_WORKSPACE": str(ws), "LRAE_PYTHON": py}
    if stage is not None:
        extra["LRAE_STAGE"] = str(stage)
    targets = [str(HIDDEN / t) for t in select] if select else [str(HIDDEN)]
    proc = subprocess.run(
        [py, "-I", "-m", "pytest", "-c", str(HIDDEN / "pytest.ini"), f"--rootdir={HIDDEN}",
         "--noconftest", "-p", "no:cacheprovider", f"--junitxml={report}", *targets],
        cwd=HIDDEN, env=_env(tmp, **extra), capture_output=True, text=True, timeout=600)
    assert report.exists(), proc.stdout[-2000:] + proc.stderr[-2000:]
    return _junit(report)


def run_pristine_seed_tests(tree: Path, tmp: Path) -> dict[str, str]:
    work = tmp / "regression"
    shutil.copytree(tree, work, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    shutil.rmtree(work / "tests")
    shutil.copytree(SEED / "tests", work / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(SEED / "pytest.ini", work / "pytest.ini")
    report = tmp / "regression.xml"
    subprocess.run([_python(), "-I", "-m", "pytest", "-c", str(work / "pytest.ini"),
                    f"--rootdir={work}", "-p", "no:cacheprovider", f"--junitxml={report}"],
                   cwd=work, env=_env(tmp), capture_output=True, text=True, timeout=300)
    return _junit(report)


@pytest.fixture(scope="module")
def tests():
    return hidden_tests()


@pytest.fixture(scope="module")
def refs(tmp_path_factory):
    build = _load_build()
    out = {s: build.materialize(f"minidb_v2_s{s}", tmp_path_factory.mktemp(f"v2s{s}") / "ws", REPO_ROOT)
           for s in range(N_STAGES)}
    out["bad"] = build.materialize("minidb_v2_known_bad", tmp_path_factory.mktemp("v2bad") / "ws",
                                   REPO_ROOT)
    return out


@pytest.fixture(scope="module")
def seed_ws(tmp_path_factory):
    task = load_spec(SPEC).spec.task
    return ensure_seed_repo(Path(task.seed_repo), task.seed_commit, tmp_path_factory.mktemp("v2seed"))


def _ids(tests: list[dict]) -> set[str]:
    return {t["id"] for t in tests}


@pytest.mark.parametrize("stage", range(N_STAGES))
def test_reference_passes_every_test_active_at_its_stage(refs, tests, tmp_path, stage):
    t0 = time.monotonic()
    out = run_hidden(refs[stage], tmp_path, stage)
    elapsed = time.monotonic() - t0
    assert set(out) == _ids(tests)  # no collection errors
    want = _ids(active(tests, stage))
    assert {t for t, o in out.items() if o == "passed"} == want
    assert {t for t, o in out.items() if o == "skipped"} == _ids(tests) - want
    if stage == N_STAGES - 1:
        assert elapsed < SUITE_BUDGET_S, f"final-stage suite took {elapsed:.0f}s"


def test_the_bare_seed_fails_cleanly(seed_ws, tests, tmp_path):
    out = run_hidden(seed_ws, tmp_path, None)  # no LRAE_STAGE: the final stage applies
    assert set(out) == _ids(tests)
    final = _ids(active(tests, N_STAGES - 1))
    assert {t for t, o in out.items() if o != "skipped"} == final
    assert {out[t] for t in final} == {"failed"}


@pytest.mark.parametrize("stage", range(N_STAGES - 1))
def test_each_stage_adds_work_the_previous_reference_cannot_do(refs, tests, tmp_path, stage):
    new = [t for t in tests if t["introduced"] == stage + 1]
    out = run_hidden(refs[stage], tmp_path, stage + 1, select=sorted(_ids(new)))
    failed = [t for t in _ids(new) if out.get(t) in ("failed", "error")]
    assert len(failed) >= 0.75 * len(new), (stage, sorted(_ids(new) - set(failed)))


@pytest.mark.parametrize("cr", [s.id for s in load_stages(STAGES).stages if s.kind == "change_request"])
def test_change_requests_flip_the_retired_behaviour(refs, tests, tmp_path, cr):
    retired = [t for t in tests if t["retired"] == cr]
    replacements = [t for t in tests if t["introduced"] == cr]
    # the new reference, evaluated with the old stage's tests, fails exactly the retired ones
    out = run_hidden(refs[cr], tmp_path / "new-at-old", cr - 1)
    assert {t for t, o in out.items() if o in ("failed", "error")} == _ids(retired)
    # the old reference fails most of the change request's new tests
    out = run_hidden(refs[cr - 1], tmp_path / "old-at-new", cr, select=sorted(_ids(replacements)))
    failed = [t for t in _ids(replacements) if out.get(t) in ("failed", "error")]
    assert len(failed) >= 0.75 * len(replacements), sorted(_ids(replacements) - set(failed))


def test_pristine_seed_tests_pass_on_every_reference_and_known_bad_breaks_one(refs, seed_ws, tmp_path):
    for label, tree in [("seed", seed_ws)] + [(f"s{s}", refs[s]) for s in range(N_STAGES)]:
        out = run_pristine_seed_tests(tree, tmp_path / label)
        assert out and set(out.values()) == {"passed"}, (label, out)
    out = run_pristine_seed_tests(refs["bad"], tmp_path / "bad")
    assert [t for t, o in out.items() if o != "passed"] == [UNTERMINATED_TEST]


def test_reference_unit_tests_are_green(refs, tmp_path):
    for s in range(N_STAGES):
        work = tmp_path / f"s{s}"
        shutil.copytree(refs[s], work, ignore=shutil.ignore_patterns(".git"))
        proc = subprocess.run([_python(), "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                              cwd=work, env=_env(tmp_path), capture_output=True, text=True,
                              timeout=300)
        assert proc.returncode == 0, (s, proc.stdout[-2000:])


def test_scorer_passes_the_final_reference_and_flags_known_bad(tmp_path_factory):
    from scorer.run_checkpoint import CORE
    from scorer.standalone import score_snapshot_dir
    from scorer.venv import install_scorer

    loaded = load_spec(SPEC)
    loaded.spec.scoring.judge_runtime = "scripted"  # never spend: the deterministic FakeJudge
    py = install_scorer(REPO_ROOT, REPO_ROOT / loaded.spec.task.seed_requirements_lock)
    good = score_snapshot_dir("fixtures/snapshots/minidb_v2_s6", loaded,
                              tmp_path_factory.mktemp("v2good") / "art", scorer_python=py)
    stage = good.metrics["P"]["detail"].get("stage")
    if stage not in (None, N_STAGES - 1):
        # interfaces.md §9 says standalone scoring uses the final stage; if the scorer picks the
        # stage active at the (synthetic) checkpoint time instead, score that stage's reference
        good = score_snapshot_dir(f"fixtures/snapshots/minidb_v2_s{stage}", loaded,
                                  tmp_path_factory.mktemp("v2good2") / "art", scorer_python=py)
    vals = {n: good.metrics[n]["value"] for n in CORE}
    assert vals["P"] == 1.0 and vals["R"] == 0 and vals["C"] == 0, vals
    assert good.hazards == []
    bad = score_snapshot_dir("fixtures/snapshots/minidb_v2_known_bad", loaded,
                             tmp_path_factory.mktemp("v2bad") / "art", scorer_python=py)
    probes = bad.metrics["C"]["detail"]["probes"]
    assert {k for k, v in probes.items() if v["violated"]} == {"protocol-untouched", "no-embedded-db"}
    assert bad.metrics["R"]["value"] == 1
