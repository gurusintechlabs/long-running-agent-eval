"""Known good/bad snapshot fixtures materialize deterministically (no app process needed)."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "fixtures" / "seed_export_service"


def _load_build():
    spec = importlib.util.spec_from_file_location("snapshots_build", ROOT / "fixtures/snapshots/build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build = _load_build()


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = {}
    for name in ("known_good", "known_bad"):
        for i in (1, 2):
            out[name, i] = build.materialize(name, tmp_path_factory.mktemp(f"{name}{i}") / "ws", ROOT)
    return out


def test_shas_are_stable_across_builds(built):
    for name in ("known_good", "known_bad"):
        assert _git(built[name, 1], "rev-parse", "HEAD") == _git(built[name, 2], "rev-parse", "HEAD")
    assert _git(built["known_good", 1], "rev-parse", "HEAD") != _git(built["known_bad", 1], "rev-parse", "HEAD")


def test_one_agent_commit_on_top_of_seed(built):
    for name in ("known_good", "known_bad"):
        ws = built[name, 1]
        assert _git(ws, "log", "--format=%an <%ae>|%cn <%ce>|%ct").splitlines()[0] == (
            "agent <agent@lrae.local>|agent <agent@lrae.local>|1767225600")  # 2026-01-01T00:00:00Z
        assert _git(ws, "rev-list", "--count", "HEAD") == "2"
        assert _git(ws, "status", "--porcelain") == ""


def test_known_good_keeps_vendor_and_has_export_test(built):
    ws = built["known_good", 1]
    assert _git(ws, "rev-parse", "HEAD:vendor") == _git(ws, "rev-parse", "HEAD~1:vendor")
    assert (ws / "vendor/slugify_lite/__init__.py").read_bytes() == (
        SEED / "vendor/slugify_lite/__init__.py").read_bytes()
    tests = [p for p in (ws / "tests").rglob("test_*.py") if '"/export' in p.read_text()]
    assert tests, "no test references /export"
    assert "csv" in (ws / "app/main.py").read_text()


def test_known_bad_differs_in_vendor(built):
    ws = built["known_bad", 1]
    assert _git(ws, "rev-parse", "HEAD:vendor") != _git(ws, "rev-parse", "HEAD~1:vendor")
    assert (ws / "app/main.py").read_text() == (built["known_good", 1] / "app/main.py").read_text()


def test_unknown_snapshot_and_nonempty_dest_rejected(tmp_path):
    with pytest.raises(ValueError):
        build.materialize("nope", tmp_path / "x", ROOT)
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "f").write_text("x")
    with pytest.raises(FileExistsError):
        build.materialize("known_good", tmp_path / "full", ROOT)
