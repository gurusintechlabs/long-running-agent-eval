"""Process-group control for local mode: spawn, pause/resume, terminate, orphan sweep.

The agent runs in its own session/process group so the harness can freeze it for snapshots
(SIGSTOP), stop it (SIGTERM then SIGKILL) and clean up anything that escaped the group
(docs/spec.md §5.1, §7.3).
"""
from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import IO, Any

import psutil


def _under(path: str | None, root: Path) -> bool:
    if not path:
        return False
    try:
        Path(path).resolve().relative_to(root)
        return True
    except (ValueError, OSError):
        return False


def find_in_dir(root: Path, exclude: set[int] | None = None, since: float | None = None,
                check_files: bool = True) -> list[psutil.Process]:
    """Processes whose cwd or open files lie under ``root`` (catches setsid/nohup escapes).

    ``since`` (epoch seconds) restricts the result to processes started at or after that time, so
    a shell the user left sitting in the work dir is never touched.
    """
    root = Path(root).resolve()
    exclude = (exclude or set()) | {os.getpid()}
    found = []
    for proc in psutil.process_iter(["pid"]):
        if proc.pid in exclude:
            continue
        try:
            if since is not None and proc.create_time() < since:
                continue
            if _under(proc.cwd(), root) or (
                    check_files and any(_under(f.path, root) for f in proc.open_files())):
                found.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            continue
    return found


def sweep(root: Path, since: float | None = None) -> list[int]:
    """SIGKILL every process (outside this one) working under ``root``; return their pids."""
    killed = []
    for proc in find_in_dir(root, since=since):
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            proc.kill()
            killed.append(proc.pid)
    return killed


class ManagedProcess:
    def __init__(self, popen: subprocess.Popen, sweep_root: Path | None = None,
                 since: float | None = None):
        self.popen = popen
        self.pid = popen.pid  # also the pgid: the child is its own session leader
        self.sweep_root = Path(sweep_root).resolve() if sweep_root else None
        self.since = since if since is not None else time.time() - 1
        self._paused: list[int] = []

    def alive(self) -> bool:
        return self.popen.poll() is None

    def _tree(self) -> list[psutil.Process]:
        """Group members, descendants, and (if configured) escaped processes under the root."""
        procs: dict[int, psutil.Process] = {}
        with contextlib.suppress(psutil.NoSuchProcess):
            root = psutil.Process(self.pid)
            for p in [root, *root.children(recursive=True)]:
                procs[p.pid] = p
        for p in psutil.process_iter(["pid"]):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError, PermissionError):
                if os.getpgid(p.pid) == self.pid:
                    procs[p.pid] = p
        if self.sweep_root:
            for p in find_in_dir(self.sweep_root, since=self.since, check_files=False):
                procs[p.pid] = p
        procs.pop(os.getpid(), None)
        return list(procs.values())

    def _signal_all(self, sig: int) -> list[int]:
        # EPERM is not a real permission problem here: macOS returns it when signalling a process
        # (or group) that has exited but not yet been reaped, e.g. a checkpoint landing between two
        # turns. Treat it like "already gone" (seen intermittently under load before this fix).
        gone = (ProcessLookupError, PermissionError)
        pids = []
        with contextlib.suppress(*gone):
            os.killpg(self.pid, sig)
        for p in self._tree():
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, *gone):
                os.kill(p.pid, sig)
                pids.append(p.pid)
        return pids

    def pause(self) -> None:
        # Two passes: the first may fork new children between listing and signalling.
        self._paused = self._signal_all(signal.SIGSTOP)
        self._paused += [p for p in self._signal_all(signal.SIGSTOP) if p not in self._paused]

    def resume(self) -> None:
        for pid in self._paused:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGCONT)
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self.pid, signal.SIGCONT)
        self._paused = []

    def terminate(self, grace_s: float = 15.0) -> None:
        """SIGTERM the tree, wait up to ``grace_s``, then SIGKILL whatever is left."""
        self._signal_all(signal.SIGCONT)  # a stopped process cannot handle SIGTERM
        self._signal_all(signal.SIGTERM)
        deadline = time.monotonic() + grace_s
        while time.monotonic() < deadline and self._any_alive():
            time.sleep(0.05)
        self.kill()

    def _any_alive(self) -> bool:
        return self.popen.poll() is None or any(
            p.is_running() and p.status() != psutil.STATUS_ZOMBIE for p in self._tree())

    def kill(self) -> None:
        self._signal_all(signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.popen.wait(timeout=5)


def spawn(cmd: list[str], *, cwd: Path, env: dict[str, str], stdout: int | IO | None = None,
          stderr: int | IO | None = None, stdin: int | IO | None = subprocess.DEVNULL,
          sweep_root: Path | None = None, since: float | None = None, **kw: Any) -> ManagedProcess:
    popen = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=stdout, stderr=stderr, stdin=stdin,
                             start_new_session=True, **kw)
    return ManagedProcess(popen, sweep_root=sweep_root, since=since)
