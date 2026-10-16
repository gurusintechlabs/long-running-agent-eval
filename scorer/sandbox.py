"""Scorer sandboxing: temp copies of snapshots, process-group helpers, leak checks.

Everything the scorer executes (the agent's app, pytest on the agent's tree, ruff, bandit) runs
in a subprocess started in its own process group, with a scrubbed environment, on a *temp copy*
that lives outside the work dir and the snapshot folder and is deleted afterwards (spec §8.1).
"""
from __future__ import annotations

import contextlib
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psutil

from runner.procs import find_in_dir

TMP_PREFIX = "lrae-score-"

_lock = threading.Lock()
_live_dirs: set[Path] = set()
_groups: dict[int, str] = {}  # pgid -> label of every group started and not yet confirmed dead


class SandboxError(RuntimeError):
    pass


def _resolve(p: Path) -> Path:
    return Path(p).resolve()


def assert_outside(path: Path, forbidden: list[Path]) -> None:
    p = _resolve(path)
    for f in forbidden:
        f = _resolve(f)
        if p == f or f in p.parents or p in f.parents:
            raise SandboxError(f"scratch dir {p} overlaps protected dir {f}")


@contextlib.contextmanager
def scratch_dir(forbid: list[Path] | None = None, prefix: str = TMP_PREFIX) -> Iterator[Path]:
    """An empty temp dir under the system temp root; killed processes inside it are swept and the
    dir is always deleted."""
    d = _resolve(Path(tempfile.mkdtemp(prefix=prefix)))
    try:
        assert_outside(d, forbid or [])
        with _lock:
            _live_dirs.add(d)
        yield d
    finally:
        kill_stragglers(d)
        shutil.rmtree(d, ignore_errors=True)
        with _lock:
            _live_dirs.discard(d)


@contextlib.contextmanager
def temp_copy(src: Path, *, forbid: list[Path] | None = None, exclude_git: bool = False,
              name: str = "tree") -> Iterator[Path]:
    """A fresh copy of ``src`` (symlinks preserved, never followed) in a new temp dir."""
    with scratch_dir(forbid) as d:
        dest = d / name
        ignore = shutil.ignore_patterns(".git") if exclude_git else None
        shutil.copytree(src, dest, symlinks=True, ignore=ignore)
        yield dest


_recent_ports: list[int] = []


def free_port() -> int:
    """A free loopback port; ports handed out recently are not handed out again, so concurrent
    callers (per-commit scoring threads) never race for the same one before its app binds."""
    port = 0
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        with _lock:
            if port not in _recent_ports:
                _recent_ports.append(port)
                del _recent_ports[:-256]
                return port
    return port


def scrubbed_env(python: Path, home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for every scorer subprocess: nothing from the host except a minimal PATH."""
    env = {
        "PATH": f"{Path(python).parent}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(home), "TMPDIR": str(home), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
        "NO_COLOR": "1",
    }
    env.update(extra or {})
    return env


@dataclass
class RunResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_s: float = 0.0


def _register(pgid: int, label: str) -> None:
    with _lock:
        _groups[pgid] = label


def kill_group(pgid: int, grace_s: float = 0.0) -> None:
    for sig in ((signal.SIGTERM,) if grace_s else ()) + (signal.SIGKILL,):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, sig)
        if sig is signal.SIGTERM:
            time.sleep(grace_s)


def group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    # a group of zombies only (not yet reaped) is not a leak
    for p in psutil.process_iter(["pid"]):
        with contextlib.suppress(psutil.Error, OSError):
            if os.getpgid(p.pid) == pgid and p.status() != psutil.STATUS_ZOMBIE:
                return True
    return False


def start(cmd: list[str], *, cwd: Path, env: dict[str, str], stdout, stderr=subprocess.STDOUT,
          label: str = "") -> subprocess.Popen:
    """Start a process in its own session/process group and register the group for leak checks."""
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=stdout,
                            stderr=stderr, start_new_session=True)
    _register(proc.pid, label or " ".join(cmd[:3]))
    return proc


def stop(proc: subprocess.Popen) -> None:
    """Kill the whole group of a process started with :func:`start` and reap it."""
    kill_group(proc.pid)
    with contextlib.suppress(Exception):
        proc.wait(timeout=5)
    with _lock:
        if not group_alive(proc.pid):
            _groups.pop(proc.pid, None)


def run(cmd: list[str], *, cwd: Path, env: dict[str, str], timeout_s: float,
        label: str = "") -> RunResult:
    """Run to completion (or timeout) in a fresh group; the group is always killed afterwards."""
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            errors="replace", start_new_session=True)
    _register(proc.pid, label or " ".join(cmd[:3]))
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_group(proc.pid)
        out, err = proc.communicate()
    finally:
        kill_group(proc.pid)  # background children of the command die with it
        with _lock:
            if not group_alive(proc.pid):
                _groups.pop(proc.pid, None)
    return RunResult(None if timed_out else proc.returncode, out or "", err or "", timed_out,
                     time.monotonic() - t0)


def kill_stragglers(root: Path) -> list[int]:
    """Kill processes that escaped their group (setsid, daemons) but work under ``root``."""
    killed: list[int] = []
    for p in find_in_dir(root):
        with contextlib.suppress(psutil.Error):
            p.kill()
            killed.append(p.pid)
    return killed


def live_dirs() -> list[Path]:
    with _lock:
        return sorted(_live_dirs)


def leftover_processes() -> list[str]:
    """Labels of scorer-started process groups that still have live members."""
    with _lock:
        return [f"{label} (pgid {pg})" for pg, label in _groups.items() if group_alive(pg)]


def reap_leftovers() -> list[str]:
    """Kill and report every scorer-started group that outlived its owner; empty = clean."""
    left = leftover_processes()
    with _lock:
        for pg in list(_groups):
            if group_alive(pg):
                kill_group(pg)
            _groups.pop(pg, None)
    return left


def leftover_temp_dirs() -> list[Path]:
    """Scratch dirs created by this process that still exist (should be empty between passes)."""
    return [d for d in live_dirs() if d.exists()]
