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

from guardrails.killswitch import KillSwitch
from guardrails.monitor import GuardrailMonitor, SystemClock, integrity_hashes
from guardrails.policy import load_policy, sha256_file
from runner import manifest as mf
from runner import memory, preflight, procs, snapshot
from runner.loop_driver import LoopDriver, TurnFailure, TurnHandle, ensure_supported
from runner.preflight import PreflightError
from runner.probe import run_probe
from runner.prompt import assemble_prompt
from runner.runtimes.base import TurnContext
from runner.runtimes.claude_code import ClaudeCodeRuntime
from runner.runtimes.scripted import ScriptedRuntime
from runner.scoring import ScorerQueue
from runner.seed import ensure_seed_repo
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
from telemetry.counters import cumulative_cost, cumulative_tokens
from telemetry.events import EventWriter
from telemetry.otlp_receiver import OtlpReceiver
from telemetry.stream_parser import parse_message


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
                 caffeinate: bool = True, score: bool = False, guard_opts: dict | None = None):
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
        self.score = score
        self.guard_opts = dict(guard_opts or {})

        self.run_id = loaded.run_id(config_name, repeat)
        self.paths = RunPaths.for_run(self.run_id, Path(self.spec.isolation.work_dir), self.repo_root)
        self.runtime = make_runtime(loaded)
        self.config = load_harness_config(config_name)
        self.state = RunState.PENDING
        self.final_state: RunState | None = None
        self.error: str | None = None
        self.censored_reason: str | None = None
        self.snapshots: list = []
        self._scorer: ScorerQueue | None = None
        self._gev: EventWriter | None = None
        self._monitor: GuardrailMonitor | None = None
        self._killswitch: KillSwitch | None = None
        self._halt_lock = threading.Lock()
        self._halting = False
        self._halt_done = threading.Event()
        self._guard_paused = False
        self._stall_since = 0.0
        self._final_tag: str | None = None

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
        self._gev = EventWriter(self.paths.events / "guardrail.jsonl", self.run_id, "guardrail")
        self._stderr = open(self.paths.events / "agent_stderr.log", "a")
        if self.score:
            self._scorer = ScorerQueue(self.paths.art, self.loaded.path, self._ev, repo_root=self.repo_root)
        self._set_state(RunState.PREPARING)

        self._start_epoch = time.time()
        if resuming:
            self._restore_for_resume()
            self._write_manifest()
        else:
            self._session_id = str(uuid.uuid4())
            self._write_manifest()  # before cloning, so even an early failure records its end state
            seed_repo = ensure_seed_repo(Path(self.spec.task.seed_repo), self.spec.task.seed_commit,
                                         self.repo_root / "runs" / ".seed-cache")
            clone_seed(seed_repo, self.spec.task.seed_commit, self.paths.workspace)

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
        self._setup_guardrails()
        if self.runtime.uses_real_agent:
            self._guard = memory.UserMemoryGuard(self.claude_home, user_memory_lock(self.repo_root))
            moved = self._guard.engage()
            self._ev.emit("user_memory", {"mechanism": "move_aside" if moved else "none_present",
                                          "moved": moved})
            mf.update(self.paths.manifest, user_memory={"mechanism": "move_aside" if moved else "none_present",
                                                        "moved": moved})
            self._probe()  # after user memory is hidden, so it tests real run conditions
        ensure_supported(self.config)

    # -- guardrails (spec §7) ---------------------------------------------------------------
    def _seed_files(self) -> dict[str, str]:
        """sha256 of every seed file (plus .git/hooks) for the effect channel; kept across resume."""
        path = self.paths.art / "seed-files.json"
        if path.exists():
            return json.loads(path.read_text())
        ws = self.paths.workspace
        out = {}
        for f in sorted(ws.rglob("*")):
            rel = f.relative_to(ws).as_posix()
            if f.is_file() and not f.is_symlink() and (not rel.startswith(".git/") or rel.startswith(".git/hooks/")):
                out[rel] = sha256_file(f)
        path.write_text(json.dumps(out, indent=1, sort_keys=True))
        return out

    def _setup_guardrails(self) -> None:
        policy = load_policy(self.spec.guardrails.policy_file)
        bound = policy.bind(work=self.paths.work, repo=self.repo_root, agent_state=self.state_dir,
                            home=self.host_home)
        o = self.guard_opts
        wall = o.get("wall")
        clock = SystemClock()
        if wall:  # tests inject a jumping wall clock
            clock.wall = wall
        self._killswitch = KillSwitch(freeze=self._freeze_agent, snapshot=self._final_snapshot,
                                      kill=self._kill_agent, writer=self._gev)
        self._monitor = GuardrailMonitor(
            events_dir=self.paths.events, policy=bound, writer=self._gev,
            on_kill=lambda v: self._halt(RunState.KILLED, "kill", rule_id=v.rule_id, reason="policy"),
            on_budget=lambda cost, tokens: self._halt(RunState.BUDGET_EXHAUSTED, "budget",
                                                      rule_id="budget", reason="budget"),
            on_pause=self._stall_pause, on_resume=self._stall_resume,
            on_interrupt=lambda kind, detail: self._halt(RunState.INTERRUPTED, "interrupt", censored=kind),
            per_run_usd=self.spec.budget.per_run_usd, per_run_tokens=self.spec.budget.per_run_tokens,
            workspace=self.paths.workspace, seed_files=self._seed_files(),
            integrity=integrity_hashes(files=[self.paths.harness_settings],
                                       dirs=[Path(self.spec.task.hidden_tests)]),
            clock=clock, poll_interval=o.get("poll_s", 0.2),
            effect_interval=o.get("effect_interval_s", 30.0),
            lag_threshold_s=o.get("stall_lag_s", 10.0),
            silence_threshold_s=o.get("stall_silence_s", 60.0))
        self._ev.emit("guardrails", {"policy_sha256": policy.sha256})
        mf.update(self.paths.manifest, policy_sha256=policy.sha256)
        self._monitor.start()

    def _halt(self, state: RunState, final: str, *, rule_id: str | None = None,
              reason: str | None = None, censored: str | None = None) -> None:
        """End the run from a guardrail: freeze, final snapshot, kill (spec §7.3). First call wins."""
        with self._halt_lock:
            if self._halting or self.final_state is not None:
                return
            self._halting = True
            self.final_state = state
            self.censored_reason = censored
            self._final_tag = final
        try:
            if rule_id is not None:
                self._killswitch.trigger(rule_id, reason, self._monitor.detect_mono_ns)
            else:  # platform interruption: same freeze + snapshot, but not a policy kill
                for step in (self._freeze_agent, self._final_snapshot, self._kill_agent):
                    try:
                        step()
                    except Exception as exc:
                        self._ev.emit("cleanup.error", {"step": f"halt:{step.__name__}", "error": str(exc)})
        finally:
            self.stop.set()
            self._halt_done.set()

    def _freeze_agent(self) -> None:
        with self.snap_lock:  # no new turn can be spawned once stop is set under this lock
            self.stop.set()
            if self.current and self.current.alive():
                self.current.proc.pause()

    def _final_snapshot(self) -> None:
        if not self.paths.workspace.exists():
            return
        done = [int(p.name[1:]) for p in self.paths.snapshots.glob("t*") if p.name[1:].isdigit()]
        self._checkpoint(max(done, default=0) + 1, final=self._final_tag, pause=False)

    def _kill_agent(self) -> None:
        if self.current:
            self.current.proc.kill()
        procs.sweep(self.paths.work, since=self._start_epoch - 1)

    def _stall_pause(self) -> None:
        # Silence alone is not a telemetry failure while the receiver is up: a real agent can sit
        # in one long tool call with nothing to export. Pause only when telemetry is really lost.
        if self._monitor._stalled == "silence" and self._receiver and self._receiver.healthy():
            self._monitor.resume_now()
            return
        with self.snap_lock:
            self._guard_paused = True
            self._stall_since = time.monotonic()
            if self.current and self.current.alive():
                self.current.proc.pause()

    def _stall_resume(self) -> None:
        with self.snap_lock:
            if not self._guard_paused:
                return
            self._guard_paused = False
            if self.current and self.current.alive():
                self.current.proc.resume()

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
        self._ev.emit("run.clock", {"start_epoch": self._start_epoch_run, "offset_s": self._offset_s})
        self._set_state(RunState.RUNNING)
        initial = assemble_prompt(self.spec.task.prompt_file, self.spec.task.constraints_file)
        driver = LoopDriver(spawn_turn=lambda p, first: self._spawn_turn(p, first), stop=self.stop,
                            initial_prompt=initial, continuation_prompt=self.config.continuation_prompt,
                            snap_lock=self.snap_lock, first_turn=self.resume_from is None,
                            on_turn=self._on_turn_end)
        ckpt = threading.Thread(target=self._checkpointer, name="checkpointer", daemon=True)
        ckpt.start()
        try:
            driver.run()
        finally:
            self.stop.set()
            ckpt.join(timeout=60)
            if self._halting:  # a guardrail is freezing/snapshotting; let it finish first
                self._halt_done.wait(300)
        if self._checkpoint_error:
            raise self._checkpoint_error
        if self.final_state is None and self._guard_paused:
            self.final_state, self.censored_reason = RunState.INTERRUPTED, "telemetry_stalled"

    def _on_turn_end(self, n: int, rc: int | None) -> None:
        if self._monitor:
            self._monitor.set_agent_active(False)
        self._ev.emit("turn.end", {"turn": n, "returncode": rc})

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
        if self._guard_paused:  # telemetry is stalled: the new turn starts frozen too
            proc.pause()
        if self._monitor:
            self._monitor.set_agent_active(True)
        return handle

    def _pump(self, proc) -> None:
        for line in proc.popen.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self._stream.emit("stream.invalid", {"raw": line[:2000]})
                continue
            if not isinstance(msg, dict):
                self._stream.emit("stream.invalid", {"raw": line[:2000]})
                continue
            self._stream.emit(f"stream.{msg.get('type', 'unknown')}", msg)
            try:  # parsed events (tool.call, ...) feed the guardrail command channel
                parsed = parse_message(msg)
            except Exception as exc:  # a parser bug must not lose the raw stream
                self._stream.emit("stream.parse_error", {"error": str(exc)[:500]})
                continue
            for etype, payload in parsed:
                self._stream.emit(etype, payload)

    def _checkpointer(self) -> None:
        dt = self.spec.run.checkpoint_interval_min * 60
        total = self.spec.run.checkpoint_count
        start_k = self.resume_from or 0
        try:
            for k in range(start_k + 1, total + 1):
                while self.elapsed_s() < k * dt:
                    if self.stop.wait(min(0.05, max(0.0, k * dt - self.elapsed_s()))):
                        return
                    if self._guard_paused and (time.monotonic() - self._stall_since
                                               > self.guard_opts.get("max_stall_s", 300.0)):
                        self._halt(RunState.INTERRUPTED, "interrupt", censored="telemetry_stalled")
                        return
                self._checkpoint(k)
            self.stop.set()  # deadline reached
        except BaseException as exc:  # noqa: BLE001 - surfaced by _run_loop
            self._checkpoint_error = exc
            self.stop.set()

    def _checkpoint(self, k: int, final: str | None = None, pause: bool = True) -> None:
        """Snapshot checkpoint ``k``. ``final`` marks a snapshot taken by the kill switch
        (``kill``/``budget``/``interrupt``); its agent is already frozen, so ``pause`` is False."""
        with self.snap_lock:
            if final is None and self._halting:
                return  # the kill switch takes the final snapshot
            pause = pause and not self._guard_paused  # already frozen by a telemetry stall
            self._set_state(RunState.CHECKPOINTING, k=k)
            cost = cumulative_cost(self.paths.events / "otel.jsonl")
            freeze = pip_freeze(self.paths.venv) if self.paths.venv.exists() else None
            proc = self.current.proc if (self.current and pause) else None
            info = snapshot.take_snapshot(self.paths, k, state_dir=self.state_dir, proc=proc,
                                          cumulative_cost_usd=cost, pip_freeze_text=freeze,
                                          extra_meta={"final": final} if final else None)
            self.snapshots.append(info)
            self._ev.emit("checkpoint", {"k": k, "t_s": round(self.elapsed_s(), 3), **info.meta})
            if final is None:
                self._set_state(RunState.RUNNING)
        if self._monitor and final is None:
            self._monitor.check_effects_now()
        if self._scorer:
            self._scorer.submit(k)

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
            ("stop guardrail monitor", lambda: self._monitor and self._monitor.stop()),
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
        otel = self.paths.events / "otel.jsonl"
        manifest_end = {"state": final.value, "end_epoch": time.time(), "error": self.error,
                        "checkpoints": len(self.snapshots), "censored_reason": self.censored_reason,
                        "cost_usd": cumulative_cost(otel), "tokens": cumulative_tokens(otel)}
        try:
            mf.update(self.paths.manifest, end=manifest_end)
        except OSError:
            pass
        self.state = final
        if self._ev:
            self._ev.emit("state", {"from": "FINALIZING", "to": final.value})
        if self._scorer:  # the agent is gone; the scorer reads only the artifact dir
            self._scorer.drain()
        for w in (self._ev, self._stream, self._otel, self._gev):
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
