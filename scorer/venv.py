"""The scorer's own virtualenv: seed lock + scorer tools (docs/spec.md §8.1).

Built once per seed lock under ``tools/scorer-venv-<lock hash>`` (gitignored), so tasks with
different seed locks (the pilot, minidb, ...) each get their own. The hidden-test app, the regression suite,
ruff and bandit all run with this interpreter, never with the agent's venv.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parent / "requirements.txt"
STAMP = ".lrae-scorer-stamp"


class ScorerVenvError(RuntimeError):
    pass


def venv_dir(repo_root: Path, seed_lock: Path) -> Path:
    tag = hashlib.sha256(Path(seed_lock).read_bytes()).hexdigest()[:10]
    return Path(repo_root) / "tools" / f"scorer-venv-{tag}"


def scorer_python(repo_root: Path, seed_lock: Path) -> Path:
    return venv_dir(repo_root, seed_lock) / "bin" / "python"


def inputs_hash(seed_lock: Path, requirements: Path = REQUIREMENTS) -> str:
    h = hashlib.sha256()
    for p in (Path(seed_lock), Path(requirements)):
        h.update(p.read_bytes())
        h.update(b"\0")
    h.update(f"py{sys.version_info.major}.{sys.version_info.minor}".encode())
    return h.hexdigest()


def is_installed(repo_root: Path, seed_lock: Path) -> bool:
    stamp = venv_dir(repo_root, seed_lock) / STAMP
    try:
        return (scorer_python(repo_root, seed_lock).exists()
                and stamp.read_text().strip() == inputs_hash(seed_lock))
    except OSError:
        return False


def install_scorer(repo_root: Path, seed_lock: Path, *, force: bool = False,
                   requirements: Path = REQUIREMENTS) -> Path:
    """Build tools/scorer-venv if its inputs changed; return the venv's python. Idempotent."""
    repo_root, seed_lock = Path(repo_root), Path(seed_lock)
    venv = venv_dir(repo_root, seed_lock)
    want = inputs_hash(seed_lock, requirements)
    py = scorer_python(repo_root, seed_lock)
    stamp = venv / STAMP
    if not force and py.exists() and stamp.exists() and stamp.read_text().strip() == want:
        return py
    cache = repo_root / "tools" / "wheel-cache"
    cache.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([sys.executable, "-m", "venv", "--clear", str(venv)], check=True,
                       capture_output=True, text=True)
        pip = [str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check",
               "--cache-dir", str(cache)]
        for req in (seed_lock, requirements):
            subprocess.run([*pip, "-r", str(req)], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise ScorerVenvError(f"building {venv} failed: {(exc.stderr or exc.stdout or '')[-1500:]}") from exc
    stamp.write_text(want)
    return py
