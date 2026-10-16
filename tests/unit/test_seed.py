import os
import subprocess
from pathlib import Path

import pytest

from runner import seed
from runner.workdir import WorkdirError
from spec.loader import REPO_ROOT, load_spec


def make_src(root: Path, content="print('hi')\n") -> Path:
    src = root / "src"
    (src / "app").mkdir(parents=True)
    (src / "app" / "main.py").write_text(content)
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "x.pyc").write_bytes(b"\0")
    return src


def test_build_is_deterministic_across_locations_and_ignores_caches(tmp_path):
    src = make_src(tmp_path)
    a = seed.build_seed_repo(src, tmp_path / "a")
    os.chmod(src / "app" / "main.py", 0o755)  # modes must not matter
    b = seed.build_seed_repo(src, tmp_path / "b")
    assert a == b and len(a) == 40
    assert not (tmp_path / "a" / "__pycache__").exists()


def test_build_changes_with_content(tmp_path):
    a = seed.build_seed_repo(make_src(tmp_path / "1"), tmp_path / "a")
    b = seed.build_seed_repo(make_src(tmp_path / "2", "print('other')\n"), tmp_path / "b")
    assert a != b


def test_ensure_builds_caches_and_verifies_pin(tmp_path):
    src = make_src(tmp_path)
    sha = seed.build_seed_repo(src, tmp_path / "ref")
    cache = tmp_path / "cache"
    repo = seed.ensure_seed_repo(src, sha, cache)
    assert repo == cache / sha and (repo / "app" / "main.py").exists()
    mtime = (repo / ".git" / "HEAD").stat().st_mtime_ns
    assert seed.ensure_seed_repo(src, sha, cache) == repo
    assert (repo / ".git" / "HEAD").stat().st_mtime_ns == mtime  # reused, not rebuilt


def test_ensure_rejects_drifted_fixture(tmp_path):
    src = make_src(tmp_path)
    sha = seed.build_seed_repo(src, tmp_path / "ref")
    (src / "app" / "main.py").write_text("print('drifted')\n")
    with pytest.raises(WorkdirError, match="pins"):
        seed.ensure_seed_repo(src, sha, tmp_path / "cache")
    assert not (tmp_path / "cache" / sha).exists()


def test_ensure_rebuilds_corrupt_cache_entry(tmp_path):
    src = make_src(tmp_path)
    sha = seed.build_seed_repo(src, tmp_path / "ref")
    cache = tmp_path / "cache"
    (cache / sha).mkdir(parents=True)
    (cache / sha / "junk").write_text("x")
    repo = seed.ensure_seed_repo(src, sha, cache)
    assert (repo / "app" / "main.py").exists() and not (repo / "junk").exists()


def test_existing_git_repo_is_used_as_is(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    env = dict(os.environ, GIT_AUTHOR_NAME="a", GIT_AUTHOR_EMAIL="a@a", GIT_COMMITTER_NAME="a", GIT_COMMITTER_EMAIL="a@a")
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    assert seed.ensure_seed_repo(repo, sha, tmp_path / "cache") == repo
    with pytest.raises(WorkdirError):
        seed.ensure_seed_repo(repo, "c" * 40, tmp_path / "cache")


def test_real_fixture_still_builds_to_the_pinned_sha(tmp_path):
    loaded = load_spec(REPO_ROOT / "spec" / "examples" / "pilot.yaml")
    repo = seed.ensure_seed_repo(Path(loaded.spec.task.seed_repo), loaded.spec.task.seed_commit, tmp_path)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    assert head == loaded.spec.task.seed_commit
