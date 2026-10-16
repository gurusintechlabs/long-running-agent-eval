"""Run orchestrator: lifecycle for one run (docs/spec.md §5.1).

PENDING -> PREPARING -> RUNNING <-> CHECKPOINTING -> FINALIZING -> terminal state.
Cleanup (final snapshot already taken, agent state dir deleted, user memory restored, processes
swept, work dir removed) runs in *every* terminal state and again, via :func:`recover_unfinalized`,
for runs whose harness crashed.
"""
from __future__ import annotations

import enum
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from runner import manifest as mf
from runner import memory, preflight, procs, snapshot
from runner.loop_driver import LoopDriver, TurnFailure, TurnHandle, ensure_supported
from runner.preflight import PreflightError
from runner.probe import run_probe
from runner.prompt import assemble_prompt
from runner.runtimes.base import TurnContext
from runner.runtimes.claude_code import ClaudeCodeRuntime
from runner.runtimes.scripted import ScriptedRuntime
from runner.workdir import (
    RunPaths,
    WorkdirError,
    build_agent_env,
    build_venv,
    clone_seed,
    harness_settings,
    pip_freeze,
)
from spec.loader import REPO_ROOT, LoadedSpec, load_harness_config
from telemetry.counters import cumulative_cost
from telemetry.events import EventWriter
from telemetry.otlp_receiver import OtlpReceiver


class RunState(str, enum.Enum):
    PENDING = "PENDING"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    CHECKPOINTING = "CHECKPOINTING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    KILLED = "KILLED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


TERMINAL = {RunState.COMPLETED, RunState.KILLED, RunState.BUDGET_EXHAUSTED, RunState.INTERRUPTED,
            RunState.FAILED}


@dataclass
class RunResult:
    run_id: str
    state: RunState
    paths: RunPaths
    snapshots: list = field(default_factory=list)
    error: str | None = None


def user_memory_lock(repo_root: Path) -> Path:
    return Path(repo_root) / "runs" / ".user-memory.lock"


def make_runtime(loaded: LoadedSpec):
    agent = loaded.spec.agent
    if agent.runtime == "scripted":
        return ScriptedRuntime(agent.script)
    return ClaudeCodeRuntime(agent.claude_bin, agent.model, agent.auto_memory)


class Run:
    def __init__(self, loaded: LoadedSpec, config_name: str, repeat: int, *,
                 repo_root: Path = REPO_ROOT, claude_home: Path | None = None,
                 host_home: Path | None = None, host_env: dict | None = None,
                 resume_from: int | None = None, confirm_spend: bool = False,
                 caffeinate: bool = True):
        self.loaded = loaded
        self.spec = loaded.spec
        self.config_name = config_name
        self.repeat = repeat
        self.repo_root = Path(repo_root)
        self.claude_home = Path(claude_home) if claude_home else memory.default_claude_home()
        self.host_home = Path(host_home) if host_home else Path.home()
        self.host_env = dict(os.environ if host_env is None else host_env)
        self.resume_from = resume_from
        self.confirm_spend = confirm_spend
        self.use_caffeinate = caffeinate

        self.run_id = loaded.run_id(config_name, repeat)
        self.paths = RunPaths.for_run(self.run_id, Path(self.spec.isolation.work_dir), self.repo_root)
        self.runtime = make_runtime(loaded)
        self.config = load_harness_config(config_name)
        self.state = RunState.PENDING
        self.final_state: RunState | None = None
        self.error: str | None = None
        self.snapshots: list = []

        self.stop = threading.Event()
        self.snap_lock = threading.Lock()
        self.current: TurnHandle | None = None
        self._created = False
        self._ev: EventWriter | None = None
        self._stream: EventWriter | None = None
        self._otel: EventWriter | None = None
        self._receiver: OtlpReceiver | None = None
        self._guard: memory.UserMemoryGuard | None = None
        self._caff: subprocess.Popen | None = None
        self._stderr = None
        self._env: dict[str, str] = {}
        self._session_id = ""
        self._t0_mono = 0.0
        self._offset_s = 0.0
        self._start_epoch = 0.0
        self._checkpoint_error: BaseException | None = None
        self._start_epoch_run = 0.0
        self.state_dir = memory.state_dir(self.paths.workspace, self.claude_home)

    # -- helpers --------------------------------------------------------------------------
    def _set_state(self, new: RunState, **extra) -> None:
        old, self.state = self.state, new
        if self._ev:
            self._ev.emit("state", {"from": old.value, "to": new.value, **extra})

    def elapsed_s(self) -> float:
        return time.monotonic() - self._t0_mono + self._offset_s

    # -- public ---------------------------------------------------------------------------
    def execute(self) -> RunResult:
        try:
            self._prepare()
            self._run_loop()
            self.final_state = self.final_state or RunState.COMPLETED
        except PreflightError as exc:
            self.error, self.final_state = str(exc), RunState.FAILED
        except TurnFailure as exc:
            self.error, self.final_state = str(exc), RunState.INTERRUPTED
        except FileExistsError as exc:
            self.error, self.final_state = f"FileExistsError: {exc}", RunState.FAILED
        except Exception as exc:  # harness bug or environment problem
            self.error = f"{type(exc).__name__}: {exc}"
            self.final_state = RunState.FAILED
            if self._ev:
                self._ev.emit("run.error", {"error": self.error, "trace": traceback.format_exc()[-4000:]})
        finally:
            self._finalize()
        return RunResult(self.run_id, self.state, self.paths, self.snapshots, self.error)

    # -- prepare --------------------------------------------------------------------------
    def _prepare(self) -> None:
        resuming = self.resume_from is not None
        if resuming:
            self.paths.create_work()
        else:
            self.paths.create()
        self._created = True
        self._ev = EventWriter(self.paths.events / "orchestrator.jsonl", self.run_id, "orchestrator")
        self._stream = EventWriter(self.paths.events / "agent_stream.jsonl", self.run_id, "agent_stream")
        self._otel = EventWriter(self.paths.events / "otel.jsonl", self.run_id, "otel")
        self._stderr = open(self.paths.events / "agent_stderr.log", "a")
        self._set_state(RunState.PREPARING)

        self._start_epoch = time.time()
        if resuming:
            self._restore_for_resume()
            self._write_manifest()
        else:
            self._session_id = str(uuid.uuid4())
            self._write_manifest()  # before cloning, so even an early failure records its end state
            clone_seed(Path(self.spec.task.seed_repo), self.spec.task.seed_commit, self.paths.workspace)

        if self.runtime.needs_venv:
            cache = Path(self.spec.isolation.work_dir) / ".pip-cache"
            build_venv(self.paths.venv, Path(self.spec.task.seed_requirements_lock), cache)

        self._receiver = OtlpReceiver(self.paths.otel_raw / "raw.jsonl", self._otel)
        self._receiver.start()
        attrs = {"lrae.run_id": self.run_id, "lrae.config": self.config_name, "lrae.repeat": str(self.repeat)}
        tel = self.spec.telemetry
        settings = harness_settings(otel_endpoint=self._receiver.endpoint, protocol=tel.protocol,
                                    export_interval_ms=tel.export_interval_ms, resource_attrs=attrs)
        self.paths.harness_settings.write_text(json.dumps(settings, indent=2))
        path_dirs = ([str(self.paths.venv / "bin")] if self.paths.venv.exists() else [])
        path_dirs += self.runtime.path_dirs()
        git_bin = shutil.which("git")
        if git_bin:
            path_dirs.append(str(Path(git_bin).parent))
        self._env = build_agent_env(host_env=self.host_env, tmpdir=self.paths.tmp, path_dirs=path_dirs,
                                    otel_endpoint=self._receiver.endpoint, protocol=tel.protocol,
                                    export_interval_ms=tel.export_interval_ms, resource_attrs=attrs)

        self._preflight()
        if self.runtime.uses_real_agent:
            self._guard = memory.UserMemoryGuard(self.claude_home, user_memory_lock(self.repo_root))
            moved = self._guard.engage()
            self._ev.emit("user_memory", {"mechanism": "move_aside" if moved else "none_present",
                                          "moved": moved})
            mf.update(self.paths.manifest, user_memory={"mechanism": "move_aside" if moved else "none_present",
                                                        "moved": moved})
            self._probe()  # after user memory is hidden, so it tests real run conditions
        ensure_supported(self.config)

    def _forbidden_names(self) -> list[str]:
        hidden = Path(self.spec.task.hidden_tests)
        return [hidden.name] if hidden.name not in ("", ".") else []

    def _preflight(self) -> None:
        checks = preflight.run_static_checks(
            self.paths, repo_root=self.repo_root, claude_home=self.claude_home, home=self.host_home,
            forbidden_names=self._forbidden_names(), check_state_empty=self.resume_from is None)
        if self.runtime.uses_real_agent:
            checks.append(preflight.check_claude_version(self.spec.agent.claude_bin,
                                                         self.spec.agent.claude_code_version))
            checks.append(preflight.Check("spend confirmed", self.confirm_spend,
                                          "real-agent runs consume subscription usage; pass confirm_spend"))
        self._ev.emit("preflight", {"checks": [c.__dict__ for c in checks]})
        preflight.require(checks)

    def _probe(self) -> None:
        """One cheap real turn proving L-3 (no MCP/plugins/skills) and L-5 (telemetry arrives)."""
        result = run_probe(runtime=self.runtime, env=self._env, receiver=self._receiver,
                           probe_dir=self.paths.work / "probe", art=self.paths.art,
                           settings_path=self.paths.harness_settings, claude_home=self.claude_home)
        self._ev.emit("preflight.probe", {"checks": [c.__dict__ for c in result.checks],
                                          "cost_usd": result.cost_usd,
                                          "note": "preflight spend; excluded from run cost"})
        preflight.require(result.checks)

    def _write_manifest(self) -> None:
        a = self.spec.agent
        claude_path = shutil.which(a.claude_bin) if a.runtime == "claude_code" else None
        settings_json = self.claude_home / "settings.json"
        data = {
            "run_id": self.run_id, "experiment_id": self.spec.experiment_id,
            "config": self.config_name, "repeat": self.repeat, "spec_hash": self.loaded.spec_hash,
            "spec_path": str(self.loaded.path),
            "spec": self.spec.model_dump(mode="json", by_alias=True),
            "model": a.model, "runtime": a.runtime, "claude_code_version": a.claude_code_version,
            "claude_path": claude_path,
            "user_settings_sha256": (hashlib.sha256(settings_json.read_bytes()).hexdigest()
                                     if settings_json.exists() else None),
            "seed_commit": self.spec.task.seed_commit, "isolation_mode": self.spec.isolation.mode,
            "framework": mf.framework_version(self.repo_root), "host": mf.host_info(),
            "start_epoch": self._start_epoch, "harness_pid": os.getpid(),
            "session_id": self._session_id, "resumed": self.resume_from is not None,
            "paths": {"work": str(self.paths.work), "workspace": str(self.paths.workspace),
                      "state_dir": str(self.state_dir)},
            "claude_home": str(self.claude_home),
        }
        if self.resume_from is not None:
            old = mf.load(self.paths.manifest)
            data["session_id"] = old.get("session_id", self._session_id)
            self._session_id = data["session_id"]
            data["resumes"] = [*old.get("resumes", []), {"from_k": self.resume_from, "at": time.time()}]
            data["original_start_epoch"] = old.get("original_start_epoch", old.get("start_epoch"))
        mf.write(self.paths.manifest, data)

    def _restore_for_resume(self) -> None:
        k = self.resume_from
        snap = self.paths.snapshots / f"t{k}"
        if not (snap / "meta.json").exists():
            raise WorkdirError(f"no snapshot t{k} for run {self.run_id}")
        old = mf.load(self.paths.manifest)
        self._session_id = old.get("session_id", "")
        for later in sorted(self.paths.snapshots.glob("t*")):
            if int(later.name[1:]) > k:
                shutil.rmtree(later)
        memory.assert_empty(self.state_dir)
        shutil.copytree(snap / "workspace", self.paths.workspace, symlinks=True)
        memory.restore_state(snap / "agent_state", self.state_dir)
        self._offset_s = k * self.spec.run.checkpoint_interval_min * 60
        self._ev.emit("run.resumed", {"from_k": k, "offset_s": self._offset_s})

    # -- run ------------------------------------------------------------------------------
    def _run_loop(self) -> None:
        if self.use_caffeinate and shutil.which("caffeinate"):
            self._caff = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
        self._t0_mono = time.monotonic()
        self._start_epoch_run = time.time() - self._offset_s
        self._set_state(RunState.RUNNING)
        initial = assemble_prompt(self.spec.task.prompt_file, self.spec.task.constraints_file)
        driver = LoopDriver(spawn_turn=lambda p, first: self._spawn_turn(p, first), stop=self.stop,
                            initial_prompt=initial, continuation_prompt=self.config.continuation_prompt,
                            snap_lock=self.snap_lock, first_turn=self.resume_from is None,
                            on_turn=lambda n, rc: self._ev.emit("turn.end", {"turn": n, "returncode": rc}))
        ckpt = threading.Thread(target=self._checkpointer, name="checkpointer", daemon=True)
        ckpt.start()
        try:
            driver.run()
        finally:
            self.stop.set()
            ckpt.join(timeout=60)
        if self._checkpoint_error:
            raise self._checkpoint_error

    def _spawn_turn(self, prompt: str, first: bool) -> TurnHandle:
        ctx = TurnContext(prompt=prompt, session_id=self._session_id, first_turn=first,
                          workspace=self.paths.workspace, art=self.paths.art,
                          settings_path=self.paths.harness_settings, otel_endpoint=self._receiver.endpoint,
                          run_start_epoch=self._start_epoch_run, state_dir=self.state_dir)
        cmd = self.runtime.build_command(ctx)
        self._ev.emit("turn.start", {"first": first, "session_id": self._session_id,
                                     "prompt_chars": len(prompt)})
        proc = procs.spawn(cmd, cwd=self.paths.workspace, env=self._env, stdout=subprocess.PIPE,
                           stderr=self._stderr, text=True, sweep_root=self.paths.work,
                           since=self._start_epoch - 1)
        pump = threading.Thread(target=self._pump, args=(proc,), daemon=True)
        pump.start()
        handle = TurnHandle(proc, pump)
        self.current = handle
        return handle

    def _pump(self, proc) -> None:
        for line in proc.popen.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                msg = json.loads(line)
                etype = f"stream.{msg.get('type', 'unknown')}" if isinstance(msg, dict) else "stream.invalid"
                self._stream.emit(etype, msg if isinstance(msg, dict) else {"raw": line[:2000]})
            except ValueError:
                self._stream.emit("stream.invalid", {"raw": line[:2000]})

    def _checkpointer(self) -> None:
        dt = self.spec.run.checkpoint_interval_min * 60
        total = self.spec.run.checkpoint_count
        start_k = self.resume_from or 0
        try:
            for k in range(start_k + 1, total + 1):
                while self.elapsed_s() < k * dt:
                    if self.stop.wait(min(0.05, max(0.0, k * dt - self.elapsed_s()))):
                        return
                self._checkpoint(k)
            self.stop.set()  # deadline reached
        except BaseException as exc:  # noqa: BLE001 - surfaced by _run_loop
            self._checkpoint_error = exc
            self.stop.set()

    def _checkpoint(self, k: int) -> None:
        with self.snap_lock:
            self._set_state(RunState.CHECKPOINTING, k=k)
            cost = cumulative_cost(self.paths.events / "otel.jsonl")
            freeze = pip_freeze(self.paths.venv) if self.paths.venv.exists() else None
            info = snapshot.take_snapshot(self.paths, k, state_dir=self.state_dir, proc=self.current.proc
                                          if self.current else None, cumulative_cost_usd=cost,
                                          pip_freeze_text=freeze)
            self.snapshots.append(info)
            self._ev.emit("checkpoint", {"k": k, "t_s": round(self.elapsed_s(), 3), **info.meta})
            self._set_state(RunState.RUNNING)

    # -- finalize -------------------------------------------------------------------------
    def _finalize(self) -> None:
        final = self.final_state or RunState.FAILED
        if not self._created:  # e.g. run folder already existed: touch nothing that is not ours
            self.state = final
            return
        if self._ev:
            self._set_state(RunState.FINALIZING)
        self.stop.set()
        steps = [
            ("terminate agent", lambda: self.current and self.current.proc.terminate(grace_s=15)),
            ("sweep orphans", lambda: procs.sweep(self.paths.work, since=self._start_epoch - 1)),
            ("flush telemetry", self._flush_receiver),
            ("delete agent state dir", lambda: memory.delete_state(self.state_dir)),
            ("restore user memory", lambda: self._guard and self._guard.restore()),
            ("stop caffeinate", lambda: self._caff and self._caff.terminate()),
        ]
        for name, fn in steps:
            try:
                fn()
            except Exception as exc:  # cleanup must keep going
                if self._ev:
                    self._ev.emit("cleanup.error", {"step": name, "error": str(exc)})
        manifest_end = {"state": final.value, "end_epoch": time.time(), "error": self.error,
                        "checkpoints": len(self.snapshots)}
        try:
            mf.update(self.paths.manifest, end=manifest_end)
        except OSError:
            pass
        self.state = final
        if self._ev:
            self._ev.emit("state", {"from": "FINALIZING", "to": final.value})
        for w in (self._ev, self._stream, self._otel):
            if w:
                w.close()
        if self._stderr:
            self._stderr.close()
        if not self.spec.isolation.keep_work_dir:
            self.paths.remove_work()

    def _flush_receiver(self) -> None:
        if self._receiver is None:
            return
        if self.runtime.uses_real_agent:
            time.sleep(2 * self.spec.telemetry.export_interval_ms / 1000)
        else:
            time.sleep(0.05)
        self._receiver.stop()


# -- crash recovery ---------------------------------------------------------------------------

def _pid_alive(pid: int | None) -> bool:
    return bool(pid) and psutil.pid_exists(pid)


def recover_unfinalized(repo_root: Path, claude_home: Path | None = None) -> list[str]:
    """Finish the cleanup of runs whose harness died before FINALIZING. Returns recovered run IDs."""
    repo_root = Path(repo_root)
    claude_home = Path(claude_home) if claude_home else memory.default_claude_home()
    recovered = []
    runs_dir = repo_root / "runs"
    if not runs_dir.exists():
        return recovered
    for mpath in sorted(runs_dir.glob("*/manifest.json")):
        try:
            m = mf.load(mpath)
        except (OSError, ValueError):
            continue
        if "end" in m or _pid_alive(m.get("harness_pid")):
            continue
        paths = m.get("paths", {})
        work = Path(paths.get("work", ""))
        if paths.get("work"):
            procs.sweep(work, since=(m.get("start_epoch") or 0) - 1)
        if paths.get("state_dir"):
            memory.delete_state(Path(paths["state_dir"]))
        memory.UserMemoryGuard.recover(claude_home, user_memory_lock(repo_root))
        if paths.get("work"):
            shutil.rmtree(work, ignore_errors=True)
        mf.update(mpath, end={"state": RunState.INTERRUPTED.value, "end_epoch": time.time(),
                              "error": "harness crashed before finalizing", "censored_reason": "harness_crash",
                              "recovered": True})
        recovered.append(m["run_id"])
    return recovered
