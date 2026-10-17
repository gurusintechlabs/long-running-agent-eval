"""minidb v2 (L3, staged): stages, briefs, hidden-suite stage windows, constraints, snapshots.

Fast checks only; the hidden suite is run for real in tests/integration/test_minidb_v2_hidden.py.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from runner.stages import load_stages
from spec.loader import REPO_ROOT, load_spec

SPEC = REPO_ROOT / "spec" / "examples" / "minidb-v2.yaml"
V1_SPEC = REPO_ROOT / "spec" / "examples" / "minidb.yaml"
SEED = REPO_ROOT / "fixtures" / "seed_minidb"
TASK = REPO_ROOT / "fixtures" / "tasks" / "minidb_v2"
HIDDEN = TASK / "hidden"
STAGES = TASK / "stages.yaml"
REFS = [f"minidb_v2_s{i}" for i in range(7)]
NEW_MODULES = {"lexer", "nodes", "parser", "values", "storage", "executor", "functions", "planner",
               "durable", "windows"}


def _load_build():
    spec = importlib.util.spec_from_file_location("snapshots_build_minidb_v2",
                                                  REPO_ROOT / "fixtures/snapshots/build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def hidden_tests() -> list[dict]:
    """Every hidden test with its tier and stage window, read from the source (never imported)."""
    out = []
    for f in sorted(HIDDEN.glob("test_*.py")):
        m = re.fullmatch(r"test_t(\d\d)_[a-z0-9_]+\.py", f.name)
        assert m, f"{f.name} does not follow test_tNN_<topic>.py"
        for node in ast.parse(f.read_text()).body:
            if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test")):
                continue
            marks = [d for d in node.decorator_list
                     if isinstance(d, ast.Call) and getattr(d.func, "id", "") == "stage"]
            assert len(marks) == 1, f"{f.name}::{node.name} needs exactly one @stage(...)"
            args = [ast.literal_eval(a) for a in marks[0].args]
            kw = {k.arg: ast.literal_eval(k.value) for k in marks[0].keywords}
            introduced = args[0]
            retired = args[1] if len(args) > 1 else kw.get("retired")
            out.append({"id": f"{f.name}::{node.name}", "file": f.name, "tier": int(m.group(1)),
                        "introduced": introduced, "retired": retired})
    return out


def active(tests: list[dict], stage: int) -> list[dict]:
    return [t for t in tests if t["introduced"] <= stage
            and (t["retired"] is None or stage < t["retired"])]


# ------------------------------------------------------------------ spec and stages

def test_spec_validates_with_its_stages_and_the_v1_seed():
    loaded = load_spec(SPEC)
    task = loaded.spec.task
    assert task.id == "minidb-v2" and task.task_class == "L3"
    assert Path(task.stages_file) == STAGES.resolve()
    assert Path(task.prompt_file) == (TASK / "stage0.md").resolve()
    assert Path(task.seed_repo) == SEED.resolve()
    assert task.seed_commit == load_spec(V1_SPEC).spec.task.seed_commit
    assert Path(task.hidden_tests) == HIDDEN.resolve()
    assert Path(task.constraints_file) == (TASK / "constraints.yaml").resolve()
    run = loaded.spec.run
    assert (run.duration_min, run.checkpoint_interval_min, run.repeats) == (240, 20, 5)
    assert loaded.spec.scoring.judge_runtime == "claude_code"


def test_stages_file_is_valid():
    plan = load_stages(STAGES)
    assert [s.id for s in plan.stages] == list(range(7))
    kinds = [s.kind for s in plan.stages]
    assert kinds.count("change_request") == 2 and kinds[0] == "feature"
    for s in plan.stages:
        assert s.prompt.is_file() and s.prompt.parent == TASK.resolve()


def test_briefs_are_product_owner_messages_that_never_mention_tests():
    plan = load_stages(STAGES)
    cons = yaml.safe_load((TASK / "constraints.yaml").read_text())["constraints"]
    for s in plan.stages:
        text = s.text
        assert "hidden" not in text.lower() and "LRAE" not in text
        for c in cons:  # planted constraints are stated once, by the runtime, not in a brief
            assert c["text"] not in text
        if s.id == 0:
            for err in ("SyntaxError", "NameError", "TypeError", "ConstraintError", "RuntimeError"):
                assert f"`{err}`" in text
            for k in range(1, 8):
                assert re.search(rf"^## {k}\. ", text, re.M), f"section {k} missing from stage 0"
        else:
            assert text.startswith("**Message from the product owner"), s.prompt.name
        if s.kind == "change_request":
            assert "*Old rule" in text and "*New rule" in text, s.prompt.name


def test_constraints_match_the_v1_task():
    v1 = yaml.safe_load((REPO_ROOT / "fixtures/tasks/minidb/constraints.yaml").read_text())
    v2 = yaml.safe_load((TASK / "constraints.yaml").read_text())
    strip = lambda cs: [{k: c[k] for k in ("id", "text", "probe", "params")} for c in cs]  # noqa: E731
    assert strip(v2["constraints"]) == strip(v1["constraints"])


def test_scorer_config():
    cfg = yaml.safe_load((HIDDEN / "scorer.yaml").read_text())
    assert "app_cmd" not in cfg
    assert cfg["test_env"] == {"LRAE_WORKSPACE": "{ws}", "LRAE_PYTHON": "{python}"}
    assert cfg["per_test_timeout_s"] == 30
    ini = (HIDDEN / "pytest.ini").read_text()
    assert "testpaths = ." in ini and "pythonpath = ." in ini


# ------------------------------------------------------------------ hidden suite

def test_every_hidden_test_has_a_stage_window_within_range():
    tests = hidden_tests()
    n_stages = len(load_stages(STAGES).stages)
    support = ast.parse((HIDDEN / "_support.py").read_text())
    final = next(n.value.value for n in support.body if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "FINAL_STAGE")
    assert final == n_stages - 1
    for t in tests:
        assert isinstance(t["introduced"], int) and 0 <= t["introduced"] < n_stages, t
        assert t["retired"] is None or t["introduced"] < t["retired"] < n_stages, t
    assert 200 <= len(tests) <= 260
    assert len(active(tests, n_stages - 1)) >= 190
    for s in range(n_stages):
        assert any(t["introduced"] == s for t in tests), f"stage {s} introduces no test"
    assert {t["tier"] for t in tests} == set(range(1, 23))


def test_only_change_requests_retire_tests_and_each_one_replaces_some():
    tests = hidden_tests()
    plan = load_stages(STAGES)
    for s in plan.stages:
        retired = [t for t in tests if t["retired"] == s.id]
        introduced = [t for t in tests if t["introduced"] == s.id]
        if s.kind == "change_request":
            assert retired, f"change request {s.id} retires no test"
            assert len(introduced) >= len(retired), s.id
        else:
            assert not retired, f"feature stage {s.id} retires {retired}"
    # later stages keep re-exercising earlier tiers: most stage-0 tests stay active to the end
    stage0 = [t for t in tests if t["introduced"] == 0]
    assert sum(1 for t in stage0 if t["retired"] is None) >= 0.85 * len(stage0)


def test_hidden_tests_never_import_the_code_under_test():
    for f in [*HIDDEN.glob("test_*.py"), HIDDEN / "_support.py"]:
        for node in ast.walk(ast.parse(f.read_text())):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            assert not any(m.split(".")[0] == "minidb" for m in mods), f"{f.name} imports minidb"


@pytest.mark.parametrize("stage", ["0", "3", "6", ""])
def test_stage_marker_skips_outside_the_window(monkeypatch, stage):
    monkeypatch.setenv("LRAE_STAGE", stage)
    spec = importlib.util.spec_from_file_location("minidb_v2_support_probe", HIDDEN / "_support.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec.loader.exec_module(mod)
    for window in [(0, 3), (3, 6), (0, None), (6, None)]:
        def probe():
            pass
        fn = mod.stage(*window)(probe)
        skip = fn.pytestmark[0].args[0]
        cur = int(stage) if stage else mod.FINAL_STAGE
        assert skip == (not (window[0] <= cur and (window[1] is None or cur < window[1])))
        assert fn.lrae_stage == window
    with pytest.raises(ValueError):
        mod.stage(3, 3)
    with pytest.raises(ValueError):
        mod.stage(2, 9)


# ------------------------------------------------------------------ reference snapshots

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    build = _load_build()
    out = {}
    for name in ("minidb_v2_s6", "minidb_v2_known_bad"):
        for i in (1, 2):
            out[name, i] = build.materialize(name, tmp_path_factory.mktemp(f"{name}{i}") / "ws",
                                             REPO_ROOT)
    out["minidb_v2_s0", 1] = build.materialize(
        "minidb_v2_s0", tmp_path_factory.mktemp("minidb_v2_s0") / "ws", REPO_ROOT)
    return out


def test_overlay_chain_is_complete_and_points_at_the_v2_spec():
    build = _load_build()
    chain = build._chain("minidb_v2_known_bad")
    assert [d.name for d, _ in chain] == REFS + ["minidb_v2_known_bad"]
    assert chain[0][1]["base"] == "seed" and chain[0][1]["spec"] == "spec/examples/minidb-v2.yaml"
    for (d, meta), prev in zip(chain[1:], REFS, strict=True):
        assert meta["base"] == prev and "spec" not in meta and meta.get("deletes") in ([], None)
        assert (d / "overlay").is_dir()


def test_snapshots_have_stable_shas_on_the_seed(built):
    seed_commit = load_spec(SPEC).spec.task.seed_commit
    for name in ("minidb_v2_s6", "minidb_v2_known_bad"):
        a, b = built[name, 1], built[name, 2]
        assert _git(a, "rev-parse", "HEAD") == _git(b, "rev-parse", "HEAD")
        assert _git(a, "rev-parse", "HEAD~1") == seed_commit
        assert _git(a, "rev-list", "--count", "HEAD") == "2"
        assert _git(a, "status", "--porcelain") == ""
    assert (_git(built["minidb_v2_s6", 1], "rev-parse", "HEAD")
            != _git(built["minidb_v2_known_bad", 1], "rev-parse", "HEAD"))


def test_references_respect_the_constraints_and_known_bad_does_not(built):
    good, bad, first = built["minidb_v2_s6", 1], built["minidb_v2_known_bad", 1], built["minidb_v2_s0", 1]
    seed_protocol = (SEED / "minidb" / "protocol.py").read_bytes()
    assert (good / "minidb" / "protocol.py").read_bytes() == seed_protocol
    assert (first / "minidb" / "protocol.py").read_bytes() == seed_protocol
    assert (bad / "minidb" / "protocol.py").read_bytes() != seed_protocol
    assert "sqlite3" not in "".join(p.read_text() for p in (good / "minidb").glob("*.py"))
    assert "import sqlite3" in (bad / "minidb" / "storage.py").read_text()
    for tree in (good, first):
        tests_text = "".join(p.read_text() for p in (tree / "tests").glob("test_*.py"))
        for mod in (tree / "minidb").glob("*.py"):
            if not (SEED / "minidb" / mod.name).exists():
                assert mod.stem in NEW_MODULES, mod.name
                assert re.search(rf"minidb(\.| import ){mod.stem}\b", tests_text), mod.name
        assert "requirements" not in _git(tree, "diff", "--name-only", "HEAD~1")
