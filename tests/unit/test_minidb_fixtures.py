"""The minidb ladder task (L2): seed, prompt, hidden suite, constraints and known snapshots.

Fast checks run by default. The ``local`` tests run the hidden suite and the pristine seed tests
for real (subprocesses, no API spend) against the seed and the known snapshots.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from runner.seed import ensure_seed_repo
from spec.loader import REPO_ROOT, load_spec

SPEC = REPO_ROOT / "spec" / "examples" / "minidb.yaml"
SEED = REPO_ROOT / "fixtures" / "seed_minidb"
TASK = REPO_ROOT / "fixtures" / "tasks" / "minidb"
HIDDEN = TASK / "hidden"
TIERS = range(1, 13)
UNTERMINATED_TEST = "tests/test_cli.py::test_unterminated_string_literal_is_an_error_not_a_crash"


def _load_build():
    spec = importlib.util.spec_from_file_location("snapshots_build_minidb",
                                                  REPO_ROOT / "fixtures/snapshots/build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def _hidden_files() -> list[Path]:
    return sorted(HIDDEN.glob("test_*.py"))


def _test_functions(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    return [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test")]


# ------------------------------------------------------------------ fast checks

def test_seed_builds_to_the_pinned_sha(tmp_path):
    loaded = load_spec(SPEC)
    task = loaded.spec.task
    assert Path(task.seed_repo) == SEED.resolve()
    repo = ensure_seed_repo(Path(task.seed_repo), task.seed_commit, tmp_path)
    assert _git(repo, "rev-parse", "HEAD") == task.seed_commit
    assert (repo / "minidb" / "protocol.py").is_file()


def test_seed_has_no_agent_memory_or_settings():
    names = {p.name for p in SEED.rglob("*")}
    assert not names & {"CLAUDE.md", "CLAUDE.local.md", ".claude", "AGENTS.md"}


def test_seed_lock_pins_the_same_pytest_as_the_pilot():
    def pins(path: Path) -> dict[str, str]:
        out = {}
        for line in path.read_text().splitlines():
            if "==" in line:
                name, ver = line.split("==", 1)
                out[name.strip().lower()] = ver.strip()
        return out
    minidb = pins(SEED / "requirements.lock")
    pilot = pins(REPO_ROOT / "fixtures/seed_export_service/requirements.lock")
    assert "pytest" in minidb
    assert {k: pilot.get(k) for k in minidb} == minidb


def test_prompt_states_every_tier_and_never_mentions_hidden_tests():
    text = (TASK / "prompt.md").read_text()
    for k in TIERS:
        assert re.search(rf"^## Tier {k}\. ", text, re.M), f"tier {k} missing from prompt"
    assert "hidden" not in text.lower()
    for err in ("SyntaxError", "NameError", "TypeError", "ConstraintError", "TransactionError",
                "RuntimeError", "IOError"):
        assert f"`{err}`" in text


def test_every_hidden_test_file_maps_to_a_tier():
    files = _hidden_files()
    tiers = []
    for f in files:
        m = re.fullmatch(r"test_t(\d\d)_[a-z0-9_]+\.py", f.name)
        assert m, f"{f.name} does not follow test_tNN_<topic>.py"
        tiers.append(int(m.group(1)))
        assert len(_test_functions(f)) >= 5, f"{f.name} has fewer than 5 tests"
    assert sorted(tiers) == list(TIERS)


def test_hidden_tests_never_import_the_code_under_test():
    for f in [*_hidden_files(), HIDDEN / "_support.py"]:
        for node in ast.walk(ast.parse(f.read_text())):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            assert not any(m.split(".")[0] == "minidb" for m in mods), f"{f.name} imports minidb"


def test_scorer_config_and_constraints():
    cfg = yaml.safe_load((HIDDEN / "scorer.yaml").read_text())
    assert "app_cmd" not in cfg
    assert cfg["test_env"] == {"LRAE_WORKSPACE": "{ws}", "LRAE_PYTHON": "{python}"}
    assert cfg["per_test_timeout_s"] == 30
    ini = (HIDDEN / "pytest.ini").read_text()
    assert "testpaths = ." in ini and "pythonpath = ." in ini
    cons = yaml.safe_load((TASK / "constraints.yaml").read_text())["constraints"]
    probes = {c["id"]: (c["probe"], c.get("params") or {}) for c in cons}
    assert probes["protocol-untouched"] == ("vendor_unchanged", {"path": "minidb/protocol.py"})
    assert probes["stdlib-only"][0] == "no_new_dependencies"
    assert probes["no-embedded-db"][0] == "forbidden_python"
    assert "sqlite3" in probes["no-embedded-db"][1]["imports"]
    assert set(probes["no-embedded-db"][1]["calls"]) == {"eval", "exec"}
    assert probes["modules-need-tests"][0] == "module_has_test"
    assert (SEED / "minidb" / "protocol.py").is_file()
    prompt = (TASK / "prompt.md").read_text()
    for c in cons:  # planted constraints are stated once, by the runtime, not in the prompt
        assert c["text"] not in prompt


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    build = _load_build()
    out = {}
    for name in ("minidb_known_good", "minidb_known_bad"):
        for i in (1, 2):
            out[name, i] = build.materialize(name, tmp_path_factory.mktemp(f"{name}{i}") / "ws",
                                             REPO_ROOT)
    return out


def test_known_snapshots_have_stable_shas_on_the_minidb_seed(built):
    seed_commit = load_spec(SPEC).spec.task.seed_commit
    for name in ("minidb_known_good", "minidb_known_bad"):
        a, b = built[name, 1], built[name, 2]
        assert _git(a, "rev-parse", "HEAD") == _git(b, "rev-parse", "HEAD")
        assert _git(a, "rev-parse", "HEAD~1") == seed_commit
        assert _git(a, "rev-list", "--count", "HEAD") == "2"
        assert _git(a, "status", "--porcelain") == ""
    assert (_git(built["minidb_known_good", 1], "rev-parse", "HEAD")
            != _git(built["minidb_known_bad", 1], "rev-parse", "HEAD"))


def test_known_good_respects_the_constraints_and_known_bad_does_not(built):
    good, bad = built["minidb_known_good", 1], built["minidb_known_bad", 1]
    seed_protocol = (SEED / "minidb" / "protocol.py").read_bytes()
    assert (good / "minidb" / "protocol.py").read_bytes() == seed_protocol
    assert (bad / "minidb" / "protocol.py").read_bytes() != seed_protocol
    assert "sqlite3" not in "".join(p.read_text() for p in (good / "minidb").glob("*.py"))
    assert "import sqlite3" in (bad / "minidb" / "storage.py").read_text()
    tests_text = "".join(p.read_text() for p in (good / "tests").glob("test_*.py"))
    for mod in (good / "minidb").glob("*.py"):
        if not (SEED / "minidb" / mod.name).exists():
            assert re.search(rf"minidb(\.| import ){mod.stem}\b", tests_text), mod.name


# ------------------------------------------------------------------ real runs (local)

def _python() -> str:
    venvs = sorted(REPO_ROOT.glob("tools/scorer-venv*/bin/python"))
    return str(venvs[0]) if venvs else sys.executable


def _junit(path: Path) -> dict[str, str]:
    outcomes = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        cls, name = case.get("classname", ""), case.get("name", "")
        tid = f"{cls.replace('.', '/')}.py::{name}"
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
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1"}
    env.update(extra)
    return env


def run_hidden(ws: Path, tmp: Path) -> dict[str, str]:
    py = _python()
    report = tmp / "hidden.xml"
    proc = subprocess.run(
        [py, "-I", "-m", "pytest", "-c", str(HIDDEN / "pytest.ini"), f"--rootdir={HIDDEN}",
         "--noconftest", "-p", "no:cacheprovider", f"--junitxml={report}", str(HIDDEN)],
        cwd=HIDDEN, env=_env(tmp, LRAE_WORKSPACE=str(ws), LRAE_PYTHON=py),
        capture_output=True, text=True, timeout=300)
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
                   cwd=work, env=_env(tmp), capture_output=True, text=True, timeout=120)
    return _junit(report)


@pytest.fixture(scope="module")
def seed_ws(tmp_path_factory):
    task = load_spec(SPEC).spec.task
    return ensure_seed_repo(Path(task.seed_repo), task.seed_commit,
                            tmp_path_factory.mktemp("seedcache"))


def _expected_hidden_count() -> int:
    return sum(len(_test_functions(f)) for f in _hidden_files())


@pytest.mark.local
def test_hidden_suite_passes_completely_on_known_good(built, tmp_path):
    out = run_hidden(built["minidb_known_good", 1], tmp_path)
    assert len(out) == _expected_hidden_count()
    assert [t for t, o in out.items() if o != "passed"] == []


@pytest.mark.local
def test_hidden_suite_fails_cleanly_on_the_seed(seed_ws, tmp_path):
    out = run_hidden(seed_ws, tmp_path)
    assert len(out) == _expected_hidden_count()  # no collection errors
    assert set(out.values()) == {"failed"}


@pytest.mark.local
def test_pristine_seed_tests_pass_on_seed_and_known_good(seed_ws, built, tmp_path):
    for label, tree in (("seed", seed_ws), ("good", built["minidb_known_good", 1])):
        out = run_pristine_seed_tests(tree, tmp_path / label)
        assert out and set(out.values()) == {"passed"}, (label, out)


@pytest.mark.local
def test_known_bad_breaks_exactly_one_seed_test(built, tmp_path):
    out = run_pristine_seed_tests(built["minidb_known_bad", 1], tmp_path)
    assert [t for t, o in out.items() if o != "passed"] == [UNTERMINATED_TEST]
