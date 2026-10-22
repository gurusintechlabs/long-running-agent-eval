"""minidb v3 (L4, staged): run the hidden and exploit suites for real against the per-stage references.

Plan B6 exit check, for the stages authored so far (``AUTHORED_THROUGH``):

* the reference ``minidb_v3_s{s}`` passes every hidden and exploit test active at LRAE_STAGE=s, its own
  unit tests, and the pristine seed tests (R(t) stays clean);
* the bare seed fails cleanly: only the inherited-engine sentinels and /healthz pass;
* each reference fails most of the next stage's new tests (stages add real work); stage 12's new work is
  scale (its concurrency tests are hardening the stage-11 reference already meets), so there the stage-11
  reference must miss the full-scale bulk-load target instead;
* at each change request (stages 3 and 11) the new reference, evaluated with the old stage's tests,
  fails the retired tests and otherwise only tests whose expectation is stage-aware (old error body,
  old score rule), and the old reference fails the replacements;
* X10 catches the inherited LIKE of the stage-0 reference (the exploit suite has teeth).

Every suite run is a subprocess like the scorer's; they run in parallel with the wall-clock tests
(``*timing*``) deselected, which then run once, alone, against the final reference. Local processes
only, no API spend.
"""
from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from runner.seed import ensure_seed_repo
from scorer.metrics import p_hidden
from spec.loader import REPO_ROOT, load_spec
from tests.unit.test_minidb_v3_fixtures import (
    AUTHORED_THROUGH,
    REFS,
    active,
    exploit_tests,
    hidden_tests,
)

pytestmark = pytest.mark.local

SPEC = REPO_ROOT / "spec" / "examples" / "minidb-v3.yaml"
SEED = REPO_ROOT / "fixtures" / "seed_minidb_v3"
TASK = REPO_ROOT / "fixtures" / "tasks" / "minidb_v3"
HIDDEN, EXPLOIT = TASK / "hidden", TASK / "exploit"
CRS = (3, 11)
SCALE_STAGE = 12            # its new work is the full-scale (timing) tier
BULK_LOAD = "test_t22_scale_and_concurrency.py::test_bulk_load_of_100000_points_timing"
SEED_PASSES = {"test_t01_service_basics.py::test_healthz_without_a_key",
               "test_t01_service_basics.py::test_a_port_in_use_is_an_error_not_a_hang",
               "test_t05_inherited_engine.py::test_the_stdin_protocol_is_unchanged",
               "test_t05_inherited_engine.py::test_the_db_flag_still_keeps_data",
               "test_t05_inherited_engine.py::test_bad_cli_arguments_still_exit_2"}
WORKERS = 3


def _load_build():
    import importlib.util
    spec = importlib.util.spec_from_file_location("snapshots_build_minidb_v3_it", REPO_ROOT / "fixtures/snapshots/build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _env(home: Path, **extra: str) -> dict[str, str]:
    env = {"PATH": f"{Path(extra.pop('PY', '/usr/bin/python3')).parent}:/usr/bin:/bin", "HOME": str(home),
           "TMPDIR": str(home), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    env.update(extra)
    return env


def _junit(path: Path) -> dict[str, str]:
    """Outcome per test function (parametrised cases folded: any failure fails the function)."""
    rank = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}
    out: dict[str, str] = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        tid = f"{case.get('classname', '').replace('.', '/')}.py::{case.get('name', '').split('[')[0]}"
        if case.find("failure") is not None:
            o = "failed"
        elif case.find("error") is not None:
            o = "error"
        elif case.find("skipped") is not None:
            o = "skipped"
        else:
            o = "passed"
        if tid not in out or rank[o] > rank[out[tid]]:
            out[tid] = o
    return out


def run_suite(py: str, ws: Path, tmp: Path, stage: int, suite: Path, *, select: list[str] | None = None,
              k: str | None = None) -> dict[str, str]:
    """Run (a selection of) a suite the way the scorer does; outcomes by test id."""
    tmp.mkdir(parents=True, exist_ok=True)
    report = tmp / "report.xml"
    targets = sorted({str(suite / t.split("::")[0]) if "::" not in t else f"{suite}/{t}" for t in select}) \
        if select else [str(suite)]
    per_test = p_hidden.per_test_timeout(p_hidden.load_config(suite))     # the scorer's own (scorer.yaml)
    proc = subprocess.run(
        [py, "-I", "-m", "pytest", "-c", str(suite / "pytest.ini"), f"--rootdir={suite}", "--noconftest",
         "-p", "no:cacheprovider", f"--timeout={per_test:g}", f"--junitxml={report}", *(["-k", k] if k else []),
         *targets],
        cwd=suite, env=_env(tmp, PY=py, LRAE_WORKSPACE=str(ws), LRAE_PYTHON=py, LRAE_STAGE=str(stage)),
        capture_output=True, text=True, timeout=2400)
    assert report.exists(), proc.stdout[-3000:] + proc.stderr[-3000:]
    return _junit(report)


def run_own_tests(py: str, tree: Path, tmp: Path, *, pristine: bool) -> tuple[int, str]:
    """The tree's own pytest suite, or (pristine) the seed's tests overlaid on it, as R(t) does."""
    work = tmp / "work"
    shutil.copytree(tree, work, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    if pristine:
        shutil.rmtree(work / "tests")
        shutil.copytree(SEED / "tests", work / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(SEED / "pytest.ini", work / "pytest.ini")
    proc = subprocess.run([py, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=work,
                          env=_env(tmp, PY=py), capture_output=True, text=True, timeout=900)
    return proc.returncode, proc.stdout[-3000:] + proc.stderr[-2000:]


@pytest.fixture(scope="module")
def tests_():
    return hidden_tests(), exploit_tests()


@pytest.fixture(scope="module")
def runs(tmp_path_factory, tests_):
    from scorer.venv import install_scorer
    task = load_spec(SPEC).spec.task
    py = str(install_scorer(REPO_ROOT, Path(task.seed_requirements_lock)))
    build = _load_build()
    trees = {s: build.materialize(REFS[s], tmp_path_factory.mktemp(f"v3s{s}") / "ws", REPO_ROOT)
             for s in range(AUTHORED_THROUGH + 1)}
    seed = ensure_seed_repo(SEED, task.seed_commit, tmp_path_factory.mktemp("v3seed"))
    hidden, _ = tests_
    tmp = tmp_path_factory.mktemp("runs")
    jobs = {}
    for s in range(AUTHORED_THROUGH + 1):
        jobs["ref", s] = lambda s=s: run_suite(py, trees[s], tmp / f"ref{s}", s, HIDDEN, k="not timing")
        jobs["exploit", s] = lambda s=s: run_suite(py, trees[s], tmp / f"exp{s}", s, EXPLOIT)
        jobs["unit", s] = lambda s=s: run_own_tests(py, trees[s], tmp / f"unit{s}", pristine=False)
        jobs["pristine", s] = lambda s=s: run_own_tests(py, trees[s], tmp / f"pristine{s}", pristine=True)
    if SCALE_STAGE <= AUTHORED_THROUGH:
        jobs["scale"] = lambda: run_suite(py, trees[SCALE_STAGE - 1], tmp / "scale", SCALE_STAGE, HIDDEN,
                                          select=[BULK_LOAD])
    for s in range(AUTHORED_THROUGH):
        new = sorted(t["id"] for t in hidden if t["introduced"] == s + 1)
        jobs["next", s] = lambda s=s, new=new: run_suite(py, trees[s], tmp / f"next{s}", s + 1, HIDDEN, select=new,
                                                         k="not timing")
    jobs["seed"] = lambda: run_suite(py, seed, tmp / "seed", AUTHORED_THROUGH, HIDDEN)
    for cr in CRS:
        if cr <= AUTHORED_THROUGH:
            jobs["flip", cr] = lambda cr=cr: run_suite(py, trees[cr], tmp / f"flip{cr}", cr - 1, HIDDEN, k="not timing")
    jobs["x10"] = lambda: run_suite(py, trees[0], tmp / "x10", 1, EXPLOIT, select=["test_x10_redos.py"])
    with ThreadPoolExecutor(WORKERS) as ex:
        futures = {key: ex.submit(fn) for key, fn in jobs.items()}
        out = {key: f.result() for key, f in futures.items()}
    out["timing"] = run_suite(py, trees[AUTHORED_THROUGH], tmp / "timing", AUTHORED_THROUGH, HIDDEN, k="timing")
    return out


def _ids(tests: list[dict]) -> set[str]:
    return {t["id"] for t in tests}


def _timing(tests: list[dict]) -> set[str]:
    return {t["id"] for t in tests if "timing" in t["id"].split("::")[1]}


@pytest.mark.parametrize("stage", range(AUTHORED_THROUGH + 1))
def test_reference_passes_every_test_active_at_its_stage(runs, tests_, stage):
    hidden, _ = tests_
    out = runs["ref", stage]
    assert set(out) == _ids(hidden) - _timing(hidden)                  # no collection errors
    want = _ids(active(hidden, stage)) - _timing(hidden)
    assert {t for t, o in out.items() if o == "passed"} == want, sorted(t for t in want if out.get(t) != "passed")
    assert {t for t, o in out.items() if o == "skipped"} == set(out) - want


def test_the_timing_tests_pass_on_the_final_reference(runs, tests_):
    hidden, _ = tests_
    timing = _timing(active(hidden, AUTHORED_THROUGH))
    assert timing and {t: o for t, o in runs["timing"].items() if t in timing} == dict.fromkeys(timing, "passed")


@pytest.mark.parametrize("stage", range(AUTHORED_THROUGH + 1))
def test_exploits_fail_on_every_reference(runs, tests_, stage):
    """Each exploit test asserts that its attack fails: all active ones pass."""
    _, exploits = tests_
    out = runs["exploit", stage]
    want = _ids(active(exploits, stage))
    assert {t for t, o in out.items() if o == "passed"} == want, {t: out.get(t) for t in want if out.get(t) != "passed"}


@pytest.mark.parametrize("stage", range(AUTHORED_THROUGH + 1))
def test_reference_unit_tests_and_pristine_seed_tests_are_green(runs, stage):
    rc, tail = runs["unit", stage]
    assert rc == 0, tail
    rc, tail = runs["pristine", stage]
    assert rc == 0, tail


def test_the_bare_seed_fails_cleanly(runs, tests_):
    hidden, _ = tests_
    out = runs["seed"]
    final = _ids(active(hidden, AUTHORED_THROUGH))
    assert set(out) == _ids(hidden) and {t for t, o in out.items() if o != "skipped"} == final
    passed = {t for t, o in out.items() if o == "passed"}
    assert passed <= SEED_PASSES and "test_t01_service_basics.py::test_healthz_without_a_key" in passed, passed
    assert {out[t] for t in final - passed} <= {"failed", "error"}


@pytest.mark.parametrize("stage", [s for s in range(AUTHORED_THROUGH) if s + 1 != SCALE_STAGE])
def test_each_stage_adds_work_the_previous_reference_cannot_do(runs, tests_, stage):
    hidden, _ = tests_
    new = {t["id"] for t in hidden if t["introduced"] == stage + 1} - _timing(hidden)
    out = runs["next", stage]
    failed = {t for t in new if out.get(t) in ("failed", "error")}
    assert len(failed) >= 0.75 * len(new), (stage, sorted(new - failed))


@pytest.mark.parametrize("cr", [c for c in CRS if c <= AUTHORED_THROUGH])
def test_the_change_request_flips_the_retired_behaviour(runs, tests_, cr):
    hidden, _ = tests_
    retired = {t["id"] for t in hidden if t["retired"] == cr}
    aware = {t["id"] for t in hidden if t["stage_aware"]}
    failed = {t for t, o in runs["flip", cr].items() if o in ("failed", "error")}
    assert retired and retired <= failed, retired - failed
    assert failed <= retired | aware, sorted(failed - retired - aware)
    # the old reference fails the replacements (the stage before the CR at the CR: test_each_stage_adds_work...)
    replacements = {t["id"] for t in hidden if t["introduced"] == cr} - _timing(hidden)
    failing = {t for t in replacements if runs["next", cr - 1].get(t) in ("failed", "error")}
    assert len(failing) >= 0.75 * len(replacements), sorted(replacements - failing)


@pytest.mark.skipif(SCALE_STAGE > AUTHORED_THROUGH, reason="stage 12 not authored")
def test_the_stage_11_reference_misses_the_full_scale_load_target(runs):
    assert runs["scale"].get(BULK_LOAD) in ("failed", "error"), runs["scale"]


def test_x10_catches_the_inherited_like_of_the_stage_0_reference(runs):
    out = runs["x10"]
    assert out and set(out.values()) == {"failed"}, out
