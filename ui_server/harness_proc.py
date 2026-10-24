"""Recognise and verify ``lrae run|resume`` harness processes (UH-3, UH-4).

macOS facts that shaped this: the venv ``python`` re-execs as ``.../Python.app/Contents/MacOS/Python``
(capital P) and a console-script run has ``argv = [that python, <path or ./relative>/lrae, run, ...]``.

``parse_argv`` understands the launch styles: ``python [opts] -m runner.cli ...``, ``python <..>/lrae ...``,
``python <..>/runner/cli.py ...`` and a bare ``lrae ...``. A ``-c`` program never matches.

``verify`` ties a process to ONE run, because the manifest is only a file on disk: its pid/start_epoch
cannot be trusted by themselves. The process must (1) have the harness argv shape, (2) name this run in
its argv (``resume <run_id>`` or the ``run <spec>`` file the manifest records, within its --config and
--repeat selection), (3) belong to this repo (its ``--repo-root``, else its cwd, else an open file inside
the run directory) and (4) not be younger than the run's recorded ``start_epoch`` (+ tolerance).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psutil

GLOBAL_VALUE_OPTS = ("--repo-root", "--claude-home", "--home")
PY_VALUE_OPTS = ("-W", "-X", "-Q")           # python options that take a separate value
START_TOLERANCE_S = 5.0


def _is_python(prog: str) -> bool:
    return os.path.basename(prog).lower().startswith("python")


def _entry_rest(argv: list[str]) -> list[str] | None:
    """The arguments after the lrae entry point, or None when this is not an lrae process."""
    if not argv:
        return None
    if _is_python(argv[0]):
        i = 1
        while i < len(argv):
            a = argv[i]
            if a == "-c" or a.startswith("-c") and len(a) > 2 and a[1] == "c":
                return None
            if a == "-m":
                return argv[i + 2:] if argv[i + 1:i + 2] == ["runner.cli"] else None
            if a in PY_VALUE_OPTS:
                i += 2
                continue
            if a.startswith("-") and a != "-":
                i += 1
                continue
            base = os.path.basename(a)
            if base == "lrae" or os.path.normpath(a).endswith(os.path.join("runner", "cli.py")):
                return argv[i + 1:]
            return None
        return None
    if os.path.basename(argv[0]) == "lrae":
        return argv[1:]
    return None


def parse_argv(argv: list[str]) -> dict[str, Any] | None:
    """``{verb, repo_root, spec, run_id, configs, repeats}`` for an ``lrae run|resume`` command line."""
    rest = _entry_rest(argv)
    if rest is None:
        return None
    out: dict[str, Any] = {"repo_root": None, "spec": None, "run_id": None, "configs": [], "repeats": []}
    i = 0
    verb = None
    while i < len(rest):
        a = rest[i]
        opt, eq, val = a.partition("=")
        if opt in GLOBAL_VALUE_OPTS:
            if not eq:
                i += 1
                val = rest[i] if i < len(rest) else ""
            if opt == "--repo-root":
                out["repo_root"] = val
        elif a.startswith("-"):
            pass
        else:
            verb = a
            i += 1
            break
        i += 1
    if verb not in ("run", "resume"):
        return None
    out["verb"] = verb
    positional = None
    while i < len(rest):
        a = rest[i]
        opt, eq, val = a.partition("=")
        if opt in ("--config", "--repeat", "--from"):
            if not eq:
                i += 1
                val = rest[i] if i < len(rest) else ""
            if opt == "--config":
                out["configs"].append(val)
            elif opt == "--repeat":
                out["repeats"].append(val)
        elif not a.startswith("-") and positional is None:
            positional = a
        i += 1
    if positional is None:
        return None
    out["spec" if verb == "run" else "run_id"] = positional
    return out


def looks_like_harness(argv: list[str]) -> bool:
    return parse_argv(argv) is not None


def _real(p: str | os.PathLike, base: str | None = None) -> str | None:
    try:
        q = Path(p)
        if not q.is_absolute() and base:
            q = Path(base) / q
        return str(q.resolve())
    except (OSError, RuntimeError, ValueError):
        return None


def _within(child: str | None, root: Path) -> bool:
    if not child:
        return False
    try:
        return Path(child).resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False


def belongs_to_repo(p: psutil.Process, info: dict, repo_root: Path, run_dir: Path | None) -> bool:
    if info["repo_root"]:
        cwd = None
        try:
            cwd = p.cwd()
        except (psutil.Error, OSError):
            pass
        return _real(info["repo_root"], cwd) == str(repo_root.resolve())
    try:
        if _within(p.cwd(), repo_root):
            return True
    except (psutil.Error, OSError):
        pass
    if run_dir is not None:
        try:
            return any(_within(f.path, run_dir) for f in p.open_files())
        except (psutil.Error, OSError):
            return False
    return False


def names_this_run(p: psutil.Process, info: dict, manifest: dict) -> bool:
    if info["verb"] == "resume":
        return info["run_id"] == manifest.get("run_id")
    try:
        cwd = p.cwd()
    except (psutil.Error, OSError):
        return False
    want = manifest.get("spec_path")
    if not isinstance(want, str) or _real(info["spec"], cwd) != _real(want):
        return False
    cfg, rep = manifest.get("config"), manifest.get("repeat")
    if info["configs"] and cfg not in info["configs"]:
        return False
    return not (info["repeats"] and str(rep) not in info["repeats"])


def verify(pid: Any, manifest: dict, repo_root: Path, run_dir: Path | None = None) -> psutil.Process | None:
    """The live harness process of this run, or None (nothing may be signalled then)."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1 or pid == os.getpid():
        return None
    if manifest.get("harness_pid") != pid or "end" in manifest:
        return None
    start = manifest.get("start_epoch")
    if not isinstance(start, (int, float)) or isinstance(start, bool):
        return None
    try:
        p = psutil.Process(pid)
        if p.status() == psutil.STATUS_ZOMBIE:
            return None
        info = parse_argv(p.cmdline())
        if info is None or p.create_time() > start + START_TOLERANCE_S:
            return None
        if not names_this_run(p, info, manifest) or not belongs_to_repo(p, info, repo_root, run_dir):
            return None
        return p
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return None


def scan(repo_root: Path) -> list[psutil.Process]:
    """Live harness-shaped processes of this repo, found by command line (a terminal-launched run is
    visible before its manifest exists)."""
    out = []
    for p in psutil.process_iter():
        try:
            if p.pid == os.getpid() or p.status() == psutil.STATUS_ZOMBIE:
                continue
            info = parse_argv(p.cmdline())
            if info is not None and belongs_to_repo(p, info, repo_root, None):
                out.append(p)
        except (psutil.Error, OSError):
            continue
    return out
