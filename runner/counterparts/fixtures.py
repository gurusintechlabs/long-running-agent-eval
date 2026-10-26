"""Harness-owned process fixtures (plan B3): the "backup daemon" holding a lock and the "legacy
service" holding a port (minidb v3 stage 9, docs/minidb-v3-design.md).

Started and stopped by stage ``env_actions`` (``start_process`` / ``stop_process``). The scripts are
standalone (stdlib) and copied into the run's ``<run_id>-svc`` dir before they start, so nothing in
their command line points into the harness repo. An agent that inspects them with ``ps`` and reads
them gets an outside-workspace warning, not a harness-access kill. They run in their own session
(not the agent's process group) with cwd in that dir, so the orphan sweep of the work dir leaves them
alone. procmon (``guardrails/procmon.py``) reports a fixture that dies while the harness still owns
it: :meth:`FixtureSet.processes` lists only those.

Events: ``fixture.started`` ``{name, kind, pid, params}``, ``fixture.stopped`` ``{name, pid}``.
"""
from __future__ import annotations

import os
import re
import select
import shutil
import subprocess
import threading
from pathlib import Path, PurePosixPath

from runner.counterparts import stdlib_python

SCRIPTS = Path(__file__).with_name("fixture_scripts")
KINDS = {"lock_holder": "lock_holder.py", "port_holder": "port_holder.py"}
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
READY_TIMEOUT_S = 10.0


class FixtureError(RuntimeError):
    pass


class FixtureSet:
    def __init__(self, *, workspace: Path, svc_dir: Path, emit=None):
        self.workspace = Path(workspace)
        self.svc_dir = Path(svc_dir)
        self.emit = emit or (lambda *a: None)
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def processes(self) -> dict[str, subprocess.Popen]:
        with self._lock:
            return dict(self._procs)

    def start(self, name: str, kind: str, params: dict) -> subprocess.Popen:
        if not NAME_RE.match(name or ""):
            raise FixtureError(f"bad fixture name {name!r}")
        if kind not in KINDS:
            raise FixtureError(f"unknown fixture kind {kind!r} (known: {', '.join(KINDS)})")
        with self._lock:
            if name in self._procs:
                raise FixtureError(f"fixture {name!r} is already running")
        args = self._args(kind, params)
        self.svc_dir.mkdir(parents=True, exist_ok=True)
        script = self.svc_dir / f"{name}.py"
        shutil.copyfile(SCRIPTS / KINDS[kind], script)
        proc = subprocess.Popen([stdlib_python(), "-I", str(script), "--name", name, *args], cwd=self.svc_dir,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, start_new_session=True, env={"PATH": os.environ.get("PATH", "")})
        ready, _, _ = select.select([proc.stdout], [], [], READY_TIMEOUT_S)
        first = proc.stdout.readline().strip() if ready else ""
        if first != "ready":
            proc.kill()
            proc.wait()
            raise FixtureError(f"fixture {name!r} ({kind}) did not start: {first or 'no answer'}")
        with self._lock:
            self._procs[name] = proc
        (self.svc_dir / f"{name}.pid").write_text(str(proc.pid))  # lets a new harness reap it after a crash
        self.emit("fixture.started", {"name": name, "kind": kind, "pid": proc.pid, "params": dict(params)})
        return proc

    def _args(self, kind: str, params: dict) -> list[str]:
        if kind == "lock_holder":
            rel = params.get("path")
            p = PurePosixPath(rel) if isinstance(rel, str) else None
            if p is None or not rel or p.is_absolute() or ".." in p.parts:
                raise FixtureError(f"lock_holder needs a workspace-relative path, got {rel!r}")
            return ["--path", str(self.workspace / p)]
        port = params.get("port")
        if not isinstance(port, int) or not 1024 <= port <= 65535:
            raise FixtureError(f"port_holder needs a port in 1024..65535, got {port!r}")
        return ["--port", str(port)]

    def stop(self, name: str) -> None:
        with self._lock:
            proc = self._procs.pop(name, None)  # first: procmon must not report a harness stop as a kill
        if proc is None:
            return
        (self.svc_dir / f"{name}.pid").unlink(missing_ok=True)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        self.emit("fixture.stopped", {"name": name, "pid": proc.pid})

    def stop_all(self) -> None:
        for name in list(self.processes()):
            self.stop(name)

    def reap_stale(self) -> list[str]:
        """Kill fixtures a crashed harness left behind (they run in their own session, so nothing
        else stops them, and they still hold their lock or port). A pid is only killed if its command
        line runs this svc dir's script for that name, so a reused pid is never touched."""
        import psutil
        reaped = []
        if not self.svc_dir.is_dir():
            return reaped
        for pid_file in sorted(self.svc_dir.glob("*.pid")):
            name = pid_file.stem
            try:
                pid = int(pid_file.read_text().strip())
                proc = psutil.Process(pid)
                ours = str(self.svc_dir / f"{name}.py") in proc.cmdline()
            except (ValueError, OSError, psutil.Error):
                ours = False
            if ours:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except psutil.TimeoutExpired:
                    proc.kill()
                self.emit("fixture.reaped", {"name": name, "pid": pid})
                reaped.append(name)
            pid_file.unlink(missing_ok=True)
        return reaped
