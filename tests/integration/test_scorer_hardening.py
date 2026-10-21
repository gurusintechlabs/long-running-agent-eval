"""Scorer gaming resistance (plan Phase 3; spec §8.2). Each test would fail without the hardening."""
import subprocess
import tempfile
from pathlib import Path

import psutil
import pytest

from scorer import sandbox
from scorer.metrics import p_hidden
from scorer.metrics import r_regression as rr
from tests.scorer_support import (
    APP_OK,
    HIDDEN_FILES,
    SEED_FILES,
    make_seed,
    write_tree,
)

pytestmark = pytest.mark.local

FORCE_PASS_CONFTEST = '''import pytest



@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call":
        rep.outcome = "passed"
        rep.longrepr = None


def pytest_collection_modifyitems(items):
    for it in items:
        it.add_marker(pytest.mark.xfail(strict=False))
'''
BROKEN_CALC = "def add(a, b):\n    return 0\n\n\ndef sub(a, b):\n    return a - b\n"
NO_ASSERT_TESTS = "from calc import add, sub\n\n\ndef test_add():\n    add(1, 2)\n\n\ndef test_sub():\n    sub(3, 1)\n"


def _outcomes(tree, seed, py):
    return rr.run_regression_on(tree, seed, py).outcomes


def test_malicious_conftest_and_weakened_tests_do_not_change_r(tmp_path, scorer_py):
    seed = make_seed(tmp_path / "seed")
    honest = write_tree(tmp_path / "honest", {**SEED_FILES, "calc.py": BROKEN_CALC})
    gamed = write_tree(tmp_path / "gamed", {
        **SEED_FILES, "calc.py": BROKEN_CALC, "conftest.py": FORCE_PASS_CONFTEST,
        "tests/conftest.py": FORCE_PASS_CONFTEST, "tests/test_calc.py": NO_ASSERT_TESTS,
        "pytest.ini": "[pytest]\naddopts = --deselect tests/test_calc.py::test_add\ntestpaths = tests\n"})
    expected = _outcomes(honest, seed, scorer_py)
    assert expected["tests/test_calc.py::test_add"] == "failed"
    assert _outcomes(gamed, seed, scorer_py) == expected
    prev = {"tests/test_calc.py::test_add": "passed", "tests/test_calc.py::test_sub": "passed"}
    assert rr.score_regressions({}, {}, prev, _outcomes(gamed, seed, scorer_py))["value"] == 1.0
    assert rr.tests_tampered(gamed, seed)["value"] == 1.0
    assert rr.tests_tampered(honest, seed)["value"] == 0.0


def test_agent_conftest_does_not_change_p(tmp_path, scorer_py):
    hidden = write_tree(tmp_path / "hidden", HIDDEN_FILES)
    broken_app = APP_OK.replace('"/b": "b"', '"/b": "WRONG"')
    plain = write_tree(tmp_path / "plain", {"app.py": broken_app})
    gamed = write_tree(tmp_path / "gamed", {"app.py": broken_app, "conftest.py": FORCE_PASS_CONFTEST,
                                            "pytest.ini": "[pytest]\naddopts = --co\n"})
    a = p_hidden.score_hidden(plain, hidden, scorer_py)
    b = p_hidden.score_hidden(gamed, hidden, scorer_py)
    assert a["value"] == b["value"] == 0.5
    assert a["detail"]["outcomes"] == b["detail"]["outcomes"]


def test_app_start_failure_is_p_zero_with_reason(tmp_path, scorer_py):
    hidden = write_tree(tmp_path / "hidden", HIDDEN_FILES)
    app = write_tree(tmp_path / "app", {"app.py": "raise SystemExit('boom: cannot start')\n"})
    res = p_hidden.score_hidden(app, hidden, scorer_py)
    assert res["value"] == 0.0 and "app_start_failed" in res["detail"]["reason"]
    assert set(res["detail"]["outcomes"].values()) == {"failed"} and res["detail"]["total"] == 2


def test_no_process_outlives_scoring_and_temp_copy_is_deleted(tmp_path, scorer_py, monkeypatch):
    scratch_root = tmp_path / "tmproot"
    scratch_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch_root))
    hidden = write_tree(tmp_path / "hidden", HIDDEN_FILES)
    # the app spawns a daemon that leaves its process group (setsid) and keeps running
    daemon = ("import subprocess\nsubprocess.Popen(['sleep', '4242'], start_new_session=True)\n"
              + APP_OK)
    app = write_tree(tmp_path / "app", {"app.py": daemon})
    res = p_hidden.score_hidden(app, hidden, scorer_py)
    assert res["value"] == 1.0
    assert list(scratch_root.iterdir()) == []  # temp copy gone
    assert sandbox.leftover_temp_dirs() == []
    assert sandbox.reap_leftovers() == []  # nothing the scorer started is still alive
    left = [p.pid for p in psutil.process_iter(["cmdline"])
            if p.info["cmdline"] and p.info["cmdline"][:2] == ["sleep", "4242"]]
    assert left == []


def test_temp_copy_is_outside_protected_dirs_and_removed(tmp_path):
    snap = write_tree(tmp_path / "snap", {"a.txt": "x"})
    with sandbox.temp_copy(snap, forbid=[tmp_path]) as copy:
        assert (copy / "a.txt").read_text() == "x"
        kept = copy
    assert not kept.exists()
    with pytest.raises(sandbox.SandboxError):
        with sandbox.scratch_dir(forbid=[Path(tempfile.gettempdir())]):
            pass


def test_hung_command_is_killed_by_timeout(tmp_path):
    res = sandbox.run(["sh", "-c", "sleep 60 & sleep 60"], cwd=tmp_path, env={"PATH": "/bin:/usr/bin"},
                      timeout_s=1)
    assert res.timed_out
    assert sandbox.reap_leftovers() == []
    # -x: the whole command line, so an unrelated "sleep 600" elsewhere on the machine does not match
    out = subprocess.run(["pgrep", "-fx", "sleep 60"], capture_output=True, text=True)
    assert out.stdout.strip() == ""
