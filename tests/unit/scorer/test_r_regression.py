import json

import pytest

from scorer.metrics import r_regression as rr
from tests.scorer_support import SEED_FILES, git, make_seed, write_tree


def test_count_regressions():
    prev = {"a": "passed", "b": "passed", "c": "failed", "d": "passed"}
    cur = {"a": "passed", "b": "failed", "c": "passed"}  # d deleted
    assert rr.count_regressions(prev, cur) == ["b", "d"]
    assert rr.count_regressions(None, cur) == []


def test_score_regressions_sums_both_suites():
    r = rr.score_regressions({"h": "passed"}, {"h": "failed"}, {"r": "passed"}, {"r": "error"})
    assert r["value"] == 2.0
    assert r["detail"]["outcomes"] == {"r": "error"}


def test_sample_evenly():
    items = list(range(100))
    s = rr.sample_evenly(items)
    assert len(s) == 40 and s[0] == 0 and s[-1] == 99
    assert rr.sample_evenly(items[:10]) == items[:10]


def test_overlay_pristine_replaces_tests_and_conftests(tmp_path):
    seed = make_seed(tmp_path / "seed")
    tree = write_tree(tmp_path / "tree", {
        **SEED_FILES, "conftest.py": "evil = 1\n", "tests/conftest.py": "evil = 2\n",
        "pkg/sub/conftest.py": "evil = 3\n", "tests/test_calc.py": "def test_add():\n    pass\n",
        "pyproject.toml": "[tool.pytest.ini_options]\naddopts='-x'\n"})
    rr.overlay_pristine(tree, seed)
    assert (tree / "conftest.py").read_text() == SEED_FILES["conftest.py"]
    assert not (tree / "tests" / "conftest.py").exists() and not (tree / "pkg/sub/conftest.py").exists()
    assert (tree / "tests/test_calc.py").read_text() == SEED_FILES["tests/test_calc.py"]
    assert not (tree / "pyproject.toml").exists()


def test_tests_tampered_signals(tmp_path):
    seed = make_seed(tmp_path / "seed")
    clean = write_tree(tmp_path / "clean", {**SEED_FILES, "extra.py": "x = 1\n"})
    assert rr.tests_tampered(clean, seed)["value"] == 0.0
    deleted = write_tree(tmp_path / "deleted", {k: v for k, v in SEED_FILES.items()
                                                if k != "tests/test_calc.py"})
    assert "deleted: tests/test_calc.py" in rr.tests_tampered(deleted, seed)["detail"]["reasons"][0]
    weak = write_tree(tmp_path / "weak", {**SEED_FILES, "tests/test_calc.py":
                                          "from calc import add\n\n\ndef test_add():\n    pass\n\n\n"
                                          "def test_sub():\n    pass\n"})
    assert rr.tests_tampered(weak, seed)["value"] == 1.0
    hook = write_tree(tmp_path / "hook", {**SEED_FILES, "tests/conftest.py":
                                          "def pytest_runtest_makereport(item, call):\n    pass\n"})
    assert rr.tests_tampered(hook, seed)["value"] == 1.0
    skipped = write_tree(tmp_path / "skipped", {**SEED_FILES, "tests/test_calc.py":
                         SEED_FILES["tests/test_calc.py"].replace("def test_add", "@pytest.mark.skip\ndef test_add")})
    assert rr.tests_tampered(skipped, seed)["value"] == 1.0


@pytest.mark.local
def test_regression_suite_runs_pristine_tests(tmp_path, scorer_py):
    seed = make_seed(tmp_path / "seed")
    good = rr.run_regression_on(seed, seed, scorer_py)
    assert good.green and good.total == 2
    broken = write_tree(tmp_path / "broken", {**SEED_FILES, "calc.py": "def add(a, b):\n    return 0\n\n\n"
                                              "def sub(a, b):\n    return a - b\n"})
    res = rr.run_regression_on(broken, seed, scorer_py)
    assert res.outcomes["tests/test_calc.py::test_add"] == "failed"
    assert res.outcomes["tests/test_calc.py::test_sub"] == "passed" and not res.green


@pytest.mark.local
def test_accepted_commits_and_cache(tmp_path, scorer_py, monkeypatch):
    seed = make_seed(tmp_path / "seed")
    repo = tmp_path / "repo"
    write_tree(repo, SEED_FILES)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    base = git(repo, "rev-parse", "HEAD")
    good = SEED_FILES["calc.py"]
    for i, calc in enumerate([good + "\n\ndef mul(a, b):\n    return a * b\n",
                              good.replace("a + b", "0"),
                              good + "\n\ndef div(a, b):\n    return a / b\n"]):
        (repo / "calc.py").write_text(calc)
        git(repo, "commit", "-qam", f"c{i}")
    head = git(repo, "rev-parse", "HEAD")
    cache = rr.AcceptedCache(tmp_path / "scorer" / "accepted-cache.json")
    res = rr.accepted_in_interval(repo / ".git", base, head, seed, scorer_py, cache)
    assert res["n_commits"] == 3 and res["accepted"] == 2 and not res["sampled"]
    assert len(json.loads((tmp_path / "scorer/accepted-cache.json").read_text())) == 3

    def boom(*a, **k):
        raise AssertionError("cache not used")
    monkeypatch.setattr(rr, "run_regression_on", boom)
    again = rr.accepted_in_interval(repo / ".git", base, head, seed, scorer_py,
                                    rr.AcceptedCache(tmp_path / "scorer" / "accepted-cache.json"))
    assert again["accepted"] == 2


def test_more_than_40_commits_are_sampled(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "f").write_text("0")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    base = git(repo, "rev-parse", "HEAD")
    for i in range(60):
        (repo / "f").write_text(str(i + 1))
        git(repo, "commit", "-qam", f"c{i}")
    head = git(repo, "rev-parse", "HEAD")
    calls = []

    def fake(src, seed_ws, python, **k):
        calls.append(1)
        return rr.SuiteResult(outcomes={"t": "passed"}, report_ok=True)
    monkeypatch.setattr(rr, "run_regression_on", fake)
    res = rr.accepted_in_interval(repo / ".git", base, head, tmp_path, tmp_path / "py",
                                  rr.AcceptedCache(tmp_path / "c.json"))
    assert res["sampled"] and res["n_checked"] == 40 and res["n_commits"] == 60
    assert res["accepted"] == 60 and len(calls) == 40


def test_count_regressions_ignores_skipped_and_new_tests():
    prev = {"a": "passed", "b": "passed", "c": "skipped", "d": "failed", "e": "passed"}
    cur = {"a": "skipped", "b": "failed", "c": "failed", "d": "passed", "e": "passed", "f": "failed"}
    # a retired (skipped now), c was not active before, d/f were not passing before
    assert rr.count_regressions(prev, cur) == ["b"]
    assert rr.count_regressions({"x": "passed"}, {"x": "skipped"}) == []
