"""D(t): defect density = (ruff + bandit >= medium findings) per KLOC of non-vendor, non-test
Python (docs/spec.md §8.3). Both tools run from the scorer venv with scorer-owned settings, so the
agent's config cannot silence them: ruff ``--isolated --ignore-noqa``, bandit ``--ignore-nosec``
and no config discovery.
"""
from __future__ import annotations

import json
from pathlib import Path

from scorer import sandbox

SKIP_DIRS = {".git", "venv", ".venv", "env", "node_modules", "site-packages", "__pycache__",
             "build", "dist", ".tox", ".mypy_cache", ".ruff_cache"}
VENDOR_DIRS = {"vendor", "vendored", "third_party", "_vendor"}
TEST_DIRS = {"tests", "test", "testing"}
RUFF_SELECT = "E4,E7,E9,F,B"


def is_scored_file(rel: Path) -> bool:
    parts = rel.parts
    if rel.suffix != ".py":
        return False
    if any(p in SKIP_DIRS or p.endswith(".egg-info") for p in parts[:-1]):
        return False
    if any(p in VENDOR_DIRS for p in parts[:-1]) or any(p in TEST_DIRS for p in parts[:-1]):
        return False
    name = parts[-1]
    return not (name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py"))


def collect_files(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if p.is_symlink() or not p.is_file() or not is_scored_file(rel):
            continue
        out.append(rel)
    return out


def count_loc(root: Path, files: list[Path]) -> int:
    n = 0
    for f in files:
        for ln in (root / f).read_text(errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#"):
                n += 1
    return n


def _chunks(items: list[str], size: int = 200):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def measure(root: Path, python: Path) -> dict:
    """Absolute defect numbers for one tree (a temp copy; tools run with cwd = ``root``)."""
    files = collect_files(root)
    loc = count_loc(root, files)
    names = [f.as_posix() for f in files]
    ruff_n = bandit_n = 0
    errors: list[str] = []
    ruff_rules: dict[str, int] = {}
    with sandbox.scratch_dir() as scratch:
        env = sandbox.scrubbed_env(python, scratch)
        for chunk in _chunks(names):
            if not chunk:
                continue
            r = sandbox.run([str(python), "-m", "ruff", "check", "--isolated", "--ignore-noqa",
                             "--select", RUFF_SELECT, "--exit-zero", "--no-cache",
                             "--output-format", "json", *chunk],
                            cwd=root, env=env, timeout_s=120, label="ruff")
            try:
                found = json.loads(r.stdout or "[]")
                ruff_n += len(found)
                for item in found:
                    ruff_rules[item.get("code") or "?"] = ruff_rules.get(item.get("code") or "?", 0) + 1
            except ValueError:
                errors.append(f"ruff: {(r.stderr or r.stdout)[-300:]}")
            b = sandbox.run([str(python), "-m", "bandit", "-q", "-ll", "--ignore-nosec",
                             "-f", "json", *chunk],
                            cwd=root, env=env, timeout_s=120, label="bandit")
            try:
                doc = json.loads(b.stdout)
                bandit_n += len(doc.get("results", []))
            except ValueError:
                errors.append(f"bandit: {(b.stderr or b.stdout)[-300:]}")
    kloc = loc / 1000
    return {"ruff": ruff_n, "bandit": bandit_n, "loc": loc, "kloc": kloc, "files": len(files),
            "ruff_rules": ruff_rules, "errors": errors,
            "D": ((ruff_n + bandit_n) / kloc) if kloc else None}


def score_defects(snapshot_ws: Path, seed_measure: dict, python: Path) -> dict:
    """Return the D metric and the D_delta auxiliary (vs the seed measurement)."""
    with sandbox.temp_copy(snapshot_ws, exclude_git=True) as tree:
        m = measure(tree, python)
    d = m["D"]
    detail = {k: v for k, v in m.items() if k != "D"}
    detail["seed"] = {k: seed_measure.get(k) for k in ("ruff", "bandit", "loc", "D")}
    if d is None:
        detail["reason"] = "no_python_loc"
    delta = None if d is None or seed_measure.get("D") is None else d - seed_measure["D"]
    return {"D": {"value": d, "detail": detail},
            "D_delta": {"value": delta, "detail": {"seed_D": seed_measure.get("D"),
                                                   **({} if delta is not None else {"reason": "no_python_loc"})}}}
