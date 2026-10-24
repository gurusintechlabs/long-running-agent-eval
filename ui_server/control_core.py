"""Control plane for the UI (phase U5): spec allowlist, server-computed estimate, single-use spend
nonces, harness-process verification, minimal subprocess env, and a one-job-at-a-time launcher.

No FastAPI imports here: ``ui_server/routes/control.py`` is the thin HTTP layer. Everything that can
spend money goes through ``Control.start_run_job`` and nothing else ever adds ``--confirm-spend``.
"""
from __future__ import annotations

import contextlib
import fcntl
import math
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

from spec.loader import LoadedSpec, SpecError
from ui_server import harness_proc, safefs, safeyaml, spend, store
from ui_server.safety import valid_run_id
from ui_server.settings import Settings

NONCE_TTL_S = 300.0
MAX_PENDING_NONCES = 20
MAX_CONFIRM_ATTEMPTS = 3
LOG_TAIL_BYTES = 8000
LAUNCH_WAIT_S = 30.0

# UI-7: the only host variables a CLI subprocess receives. The runner scrubs the *agent* env itself
# (runner/workdir.py build_agent_env: HOME USER LOGNAME LANG TERM + a fixed PATH); this is the env of
# the harness process, one step earlier, so it must carry no secret the harness would not need.
#   PATH     find git / claude / caffeinate and the python the harness spawns
#   HOME     real, the Claude CLI login lives under it (runner/memory.py also derives paths from it)
#   USER, LOGNAME, LANG, TERM   passed through to the agent by the runner anyway
#   PYTHONUNBUFFERED   so the launch log is live
ENV_ALLOW = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TERM")
ENV_FORCE = {"PYTHONUNBUFFERED": "1"}
# Never forwarded, whatever the allowlist says (belt and braces for extra_env mistakes).
ENV_NEVER_PREFIX = ("ANTHROPIC", "AWS_", "AZURE", "GOOGLE", "GCP", "OPENAI", "GITHUB", "GH_", "HF_", "LRAE_")


class ControlError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


# -- subprocess environment ----------------------------------------------------------------------

def build_env(base: dict[str, str], extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: base[k] for k in ENV_ALLOW if k in base}
    env.update(ENV_FORCE)
    for k, v in (extra or {}).items():
        if k.startswith(ENV_NEVER_PREFIX):
            raise ValueError(f"refusing to pass {k} to a subprocess")
        env[k] = v
    return env


# -- spec allowlist ------------------------------------------------------------------------------

_DRAFT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.ya?ml", re.ASCII)


def resolve_spec_path(roots: list[Path], repo_root: Path, spec_path: str | None, draft: str | None) -> Path:
    """The spec file's real path, or ControlError. Only ``*.yaml`` files that resolve (symlinks
    followed) inside one of ``roots`` are accepted; the client never names any other location."""
    if (spec_path is None) == (draft is None):
        raise ControlError(422, "bad_spec_ref", "give exactly one of spec_path or draft")
    if draft is not None:
        if not isinstance(draft, str) or not _DRAFT_NAME.fullmatch(draft):
            raise ControlError(422, "bad_spec_ref", "bad draft name")
        raw = repo_root / "spec" / "drafts" / draft
    else:
        if not isinstance(spec_path, str) or not spec_path or len(spec_path) > 512 or "\0" in spec_path:
            raise ControlError(422, "bad_spec_ref", "bad spec_path")
        raw = Path(spec_path)
        if not raw.is_absolute():
            raw = repo_root / raw
    if raw.suffix not in (".yaml", ".yml"):
        raise ControlError(422, "spec_not_allowed", "only .yaml spec files are accepted")
    try:
        real = raw.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ControlError(404, "spec_not_found", "no such spec file") from None
    if not real.is_file() or not any(real.is_relative_to(r.resolve()) for r in roots):
        raise ControlError(403, "spec_not_allowed", "spec must be a file under the repo's spec/ tree")
    return real


# -- estimate ------------------------------------------------------------------------------------

def _rel(repo_root: Path, p: Path) -> str:
    try:
        return p.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return p.name


def _norm_list(v, name: str) -> list | None:
    if v is None:
        return None
    return list(v) if isinstance(v, (list, tuple)) else [v]


def money(x: float) -> float:
    return round(float(x), 2)


MAX_SPEND_BASIS = (
    "worst case, API-equivalent: the CLI checks the experiment cap only before a run starts, so the last "
    "run that starts can overshoot it; each run is held to per_run_usd")


def worst_case_usd(n: int, per_run: float, exp_cap: float, spent: float) -> tuple[float, float]:
    """``(worst, nominal)``. ``runner.cli.cmd_run`` starts the next run while ``spent < experiment_usd``
    (spent = finished runs of this experiment and spec hash), so with ``remaining = cap - spent`` at most
    ``ceil(remaining / per_run)`` runs start, each costing at most ``per_run``. ``nominal`` is the
    (non-maximal) ``min(cap, n * per_run)``."""
    nominal = money(min(exp_cap, n * per_run))
    remaining = exp_cap - spent
    if remaining <= 0 or per_run <= 0:
        return 0.0, nominal
    starts = min(n, math.ceil(remaining / per_run - 1e-9))
    return money(starts * per_run), nominal


def outside_spec_hash(s) -> dict:
    """What the run will use that the spec hash does not cover (work_dir and seed_repo are excluded from
    the hash by design; prompt_file is hashed by content but shown so the user sees where it is)."""
    return {"work_dir": s.isolation.work_dir, "seed_repo": s.task.seed_repo, "prompt_file": s.task.prompt_file}


def compute_estimate(loaded: LoadedSpec, repo_root: Path, *, configs=None, repeats=None) -> dict:
    """Everything the user is asked to confirm, derived from the spec file alone."""
    s = loaded.spec
    all_cfgs = list(s.run.configs)
    cfgs = _norm_list(configs, "config") or all_cfgs
    bad = [c for c in cfgs if c not in all_cfgs]
    if bad or len(set(cfgs)) != len(cfgs):
        raise ControlError(422, "bad_selection", f"config must be a subset of {all_cfgs}")
    cfgs = [c for c in all_cfgs if c in cfgs]
    reps = _norm_list(repeats, "repeat")
    if reps is None:
        reps = list(range(s.run.repeats))
    if (not all(isinstance(r, int) and not isinstance(r, bool) and 0 <= r < s.run.repeats for r in reps)
            or len(set(reps)) != len(reps) or not reps):
        raise ControlError(422, "bad_selection", f"repeat must be distinct integers in [0, {s.run.repeats})")
    reps = sorted(reps)
    run_ids = [loaded.run_id(c, r) for c in cfgs for r in reps]
    n = len(run_ids)
    per_run = money(s.budget.per_run_usd)
    exp_cap = money(s.budget.experiment_usd)
    reasons = spend.spend_reasons(s)
    from runner.cli import experiment_spend
    spent = experiment_spend(repo_root, s.experiment_id, loaded.spec_hash)
    worst, nominal = worst_case_usd(n, per_run, exp_cap, spent)
    return {
        "experiment_id": s.experiment_id, "spec_hash": loaded.spec_hash,
        "runtime": s.agent.runtime, "model": s.agent.model, "claude_code_version": s.agent.claude_code_version,
        "judge_runtime": s.scoring.judge_runtime, "judge_model": s.scoring.judge_model,
        "real_spend": bool(reasons), "spend_reasons": reasons,
        "configs": cfgs, "repeats": reps, "run_ids": run_ids, "run_count": n,
        "per_run_usd": per_run, "per_run_tokens": s.budget.per_run_tokens, "experiment_usd": exp_cap,
        "max_spend_usd": worst, "nominal_cap_usd": nominal,
        "max_spend_basis": MAX_SPEND_BASIS,
        "spent_so_far_usd": money(spent),
        "outside_spec_hash": outside_spec_hash(s),
        "duration_min": s.run.duration_min, "checkpoint_interval_min": s.run.checkpoint_interval_min,
        "checkpoint_count": s.run.checkpoint_count,
        "max_wall_clock_min": round(n * s.run.duration_min, 2),
    }


def existing_conflicts(loaded: LoadedSpec, repo_root: Path, run_ids: list[str]) -> list[str]:
    work = Path(loaded.spec.isolation.work_dir)
    return [r for r in run_ids if (repo_root / "runs" / r).exists() or (work / r).exists()]


# -- nonces --------------------------------------------------------------------------------------

@dataclass
class NonceRecord:
    kind: str                    # "launch" | "resume"
    bound: dict                  # the estimate the user saw (incl. spec hash, run ids, caps)
    spec_file: Path
    expires: float
    argv_tail: list[str]         # everything after "lrae": built by the server at preview time
    attempts: int = 0
    meta: dict = field(default_factory=dict)


class NonceStore:
    def __init__(self, ttl_s: float = NONCE_TTL_S, clock: Callable[[], float] = time.monotonic):
        self.ttl_s, self.clock = ttl_s, clock
        self._lock = threading.Lock()
        self._live: dict[str, NonceRecord] = {}
        self._spent: dict[str, str] = {}

    def _gc(self) -> None:
        now = self.clock()
        for k in [k for k, r in self._live.items() if r.expires <= now]:
            self._live.pop(k)
            self._remember(k, "expired")

    def _remember(self, nonce: str, why: str) -> None:
        self._spent[nonce] = why
        while len(self._spent) > 200:
            self._spent.pop(next(iter(self._spent)))

    def issue(self, rec: NonceRecord) -> str:
        with self._lock:
            self._gc()
            while len(self._live) >= MAX_PENDING_NONCES:   # evict the oldest
                old = next(iter(self._live))
                self._live.pop(old)
                self._remember(old, "expired")
            n = secrets.token_urlsafe(32)
            self._live[n] = rec
            return n

    def peek(self, nonce: str, kind: str) -> NonceRecord:
        with self._lock:
            self._gc()
            rec = self._live.get(nonce) if isinstance(nonce, str) else None
            if rec is None or rec.kind != kind:
                why = self._spent.get(nonce) if isinstance(nonce, str) else None
                raise ControlError(400, "nonce_invalid",
                                   {"expired": "confirmation nonce expired; preview again",
                                    "used": "confirmation nonce was already used; preview again",
                                    "burned": "confirmation nonce was invalidated; preview again"}.get(
                                        why or "", "unknown confirmation nonce; preview first"))
            return rec

    def burn(self, nonce: str, why: str = "burned") -> None:
        with self._lock:
            if self._live.pop(nonce, None) is not None:
                self._remember(nonce, why)

    def consume(self, nonce: str) -> NonceRecord:
        """Atomically take the nonce (single use). Called only under the launch lock."""
        with self._lock:
            self._gc()
            rec = self._live.pop(nonce, None)
            if rec is None:
                raise ControlError(409, "nonce_invalid", "confirmation nonce already used or expired")
            self._remember(nonce, "used")
            return rec

    def bad_confirmation(self, nonce: str) -> None:
        with self._lock:
            rec = self._live.get(nonce)
            if rec is not None:
                rec.attempts += 1
                if rec.attempts >= MAX_CONFIRM_ATTEMPTS:
                    self._live.pop(nonce)
                    self._remember(nonce, "burned")

    def pending(self) -> int:
        with self._lock:
            self._gc()
            return len(self._live)


# may move between preview and launch without the spec changing (max_spend only downwards, checked)
VOLATILE = ("spent_so_far_usd", "max_spend_usd", "nominal_cap_usd")


def _stable(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in VOLATILE}


def check_confirmation(bound: dict, confirm_usd, confirm_runs) -> None:
    """Typed confirmation for real-spend runs: the user must echo the figures the server showed."""
    if not bound["real_spend"]:
        return
    try:
        usd_ok = confirm_usd is not None and not isinstance(confirm_usd, bool) \
            and abs(float(confirm_usd) - bound["max_spend_usd"]) < 0.005
    except (TypeError, ValueError):
        usd_ok = False
    runs_ok = isinstance(confirm_runs, int) and not isinstance(confirm_runs, bool) \
        and confirm_runs == bound["run_count"]
    if not (usd_ok and runs_ok):
        raise ControlError(422, "confirmation_mismatch",
                           "type the spend cap and the run count exactly as shown in the estimate",
                           expected_fields=["confirm_usd", "confirm_runs"])


# -- processes -----------------------------------------------------------------------------------

def _argv_is_harness(argv: list[str]) -> bool:
    """``python [-opts] -m runner.cli [opts] run|resume ...``, an ``lrae`` script or ``runner/cli.py``
    as the program, any case of ``Python`` (macOS re-execs as ``Python.app/.../MacOS/Python``). A
    ``-c`` program (e.g. a decoy quoting these words) never matches."""
    return harness_proc.looks_like_harness(argv)


def verify_harness(pid: Any, manifest: dict, repo_root: Path | None = None,
                   run_dir: Path | None = None) -> psutil.Process | None:
    """The live process of this run's harness, or None. See ``harness_proc.verify``: the process must
    be the manifest's pid, the run must not have ended, and the process must name THIS run in its
    command line, belong to this repo and not be younger than the run's ``start_epoch``."""
    if repo_root is None:
        return None     # fail closed: there is nothing to tie the process to
    return harness_proc.verify(pid, manifest, repo_root, run_dir)


def harness_state(pid: Any) -> str:
    """'alive' | 'unknown' (alive but unreadable: treated as busy, never signalled) | 'gone'."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return "gone"
    try:
        p = psutil.Process(pid)
        if p.status() == psutil.STATUS_ZOMBIE:
            return "gone"
        return "alive" if _argv_is_harness(p.cmdline()) else "gone"
    except psutil.AccessDenied:
        return "unknown"
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return "gone"


def active_manifest_runs(runs_dir: Path) -> list[dict]:
    out = []
    for mpath in sorted(runs_dir.glob("*/manifest.json")):
        m = store.read_json(mpath)
        if not m or "end" in m or not valid_run_id(m.get("run_id")):
            continue
        st = harness_state(m.get("harness_pid"))
        if st != "gone":
            out.append({"run_id": m["run_id"], "pid": m.get("harness_pid"), "state": "running",
                        "verified": st == "alive"})
    return out


def tail(path: Path | None, n: int = LOG_TAIL_BYTES) -> str:
    if path is None:
        return ""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - n))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def default_spawner(argv: list[str], env: dict[str, str], cwd: Path, log_path: Path):
    """Detached (own session: a UI crash does not kill the run); stdout/stderr to a log under
    ``ui_state/``; stdin closed. Returns the Popen."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        return subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=fd, stderr=fd,
                                start_new_session=True)
    finally:
        os.close(fd)


@dataclass
class ControlConfig:
    repo_root: Path
    runs_dir: Path
    state_dir: Path
    code_root: Path                       # cwd of the lrae subprocess (where ``runner`` is importable)
    spec_roots: list[Path]
    global_argv: list[str] = field(default_factory=list)   # e.g. --claude-home/--home (tests)
    run_argv: list[str] = field(default_factory=list)      # extra `run` flags (tests: --no-score ...)
    resume_argv: list[str] = field(default_factory=list)   # extra `resume` flags (tests)
    extra_env: dict[str, str] = field(default_factory=dict)
    python: str = sys.executable
    nonce_ttl_s: float = NONCE_TTL_S
    launch_wait_s: float = LAUNCH_WAIT_S
    spawner: Callable[..., Any] = default_spawner
    clock: Callable[[], float] = time.monotonic

    @property
    def disabled_reason(self) -> str | None:
        """The CLI is only ever given ``--repo-root``, so it reads and writes ``<repo>/runs``. If the UI was
        started with another ``--runs-dir``, its view of active runs, conflicts and spend would not be the
        CLI's: control is off rather than guessing."""
        want = (self.repo_root / "runs").resolve()
        if self.runs_dir.resolve() != want:
            return (f"the UI reads runs from {self.runs_dir} but lrae uses {want}; start the UI with the default "
                    "runs dir to control runs (viewing still works)")
        return None

    @classmethod
    def from_settings(cls, s: Settings) -> ControlConfig:
        root = s.repo_root.resolve()
        return cls(repo_root=root, runs_dir=s.runs_dir, state_dir=root / "ui_state", code_root=root,
                   spec_roots=[root / "spec"])


class Control:
    def __init__(self, cfg: ControlConfig):
        self.cfg = cfg
        self.nonces = NonceStore(cfg.nonce_ttl_s, cfg.clock)
        self._mutex = threading.Lock()
        self.job: dict | None = None     # {kind, proc, pid, log, started, run_ids, expect_run}
        self._stop_requested: dict[int, float] = {}

    def require_enabled(self) -> None:
        why = self.cfg.disabled_reason
        if why:
            raise ControlError(409, "control_disabled", why)

    def argv(self, *tail: str) -> list[str]:
        c = self.cfg
        return [c.python, "-m", "runner.cli", "--repo-root", str(c.repo_root), *c.global_argv, *tail]

    def env(self) -> dict[str, str]:
        return build_env(dict(os.environ), self.cfg.extra_env)

    # -- state ---------------------------------------------------------------------------------
    def _job_alive(self) -> bool:
        j = self.job
        return bool(j) and j["proc"].poll() is None

    def active(self) -> list[dict]:
        out = []
        if self._job_alive():
            j = self.job
            out.append({"run_id": (j.get("run_ids") or [None])[0], "pid": j["pid"], "state": "running",
                        "source": f"tracked-{j['kind']}", "verified": True})
        seen = {a["pid"] for a in out}
        for a in active_manifest_runs(self.cfg.runs_dir):
            if a["pid"] not in seen:
                out.append({**a, "source": "manifest"})
        seen |= {a["pid"] for a in out}
        # a terminal-launched run is visible by its command line even before its manifest exists
        for p in harness_proc.scan(self.cfg.repo_root):
            if p.pid not in seen:
                info = harness_proc.parse_argv(p.cmdline()) or {}
                out.append({"run_id": info.get("run_id"), "pid": p.pid, "state": "running",
                            "source": "process", "verified": True})
        return out

    def state(self) -> dict:
        act = self.active()
        j = self.job
        off = self.cfg.disabled_reason
        return {
            "active": bool(act), "run": act[0] if act else None, "active_all": act,
            "control_enabled": off is None, "control_disabled_reason": off,
            "launch_allowed": not act and off is None,
            "reason": None if not act else f"a harness process is alive (run {act[0]['run_id']}, pid {act[0]['pid']}); "
                                           "one run at a time",
            "job": None if not j else {"kind": j["kind"], "pid": j["pid"], "started_epoch": j["started"],
                                       "alive": j["proc"].poll() is None, "exit_code": j["proc"].poll(),
                                       "run_ids": j.get("run_ids")},
            "log_tail": tail(j["log"]) if j else "",
            "pending_nonces": self.nonces.pending(),
        }

    # -- exclusive start -----------------------------------------------------------------------
    @contextlib.contextmanager
    def exclusive(self):
        """One start at a time: an in-process mutex plus an flock for a second UI server."""
        if not self._mutex.acquire(blocking=False):
            raise ControlError(409, "busy", "another start request is in progress")
        fd = None
        try:
            self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.cfg.state_dir / "control.lock", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ControlError(409, "busy", "another UI server is starting a job") from None
            yield
        finally:
            if fd is not None:
                os.close(fd)
            self._mutex.release()

    def _refuse_if_active(self) -> None:
        act = self.active()
        if act:
            raise ControlError(409, "run_active",
                               f"a harness process is alive (run {act[0]['run_id']}, pid {act[0]['pid']}); "
                               "one run at a time", run=act[0])

    def _spawn(self, kind: str, tail_argv: list[str], run_ids: list[str] | None) -> dict:
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        log = self.cfg.state_dir / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}.log"
        argv = self.argv(*tail_argv)
        proc = self.cfg.spawner(argv, self.env(), self.cfg.code_root, log)
        self.job = {"kind": kind, "proc": proc, "pid": proc.pid, "log": log, "started": time.time(),
                    "run_ids": run_ids}
        return self.job

    def start_run_job(self, nonce: str, kind: str, confirm_usd, confirm_runs) -> dict:
        """The only code path that can start a spending process (launch and resume).

        Order: nonce known/unexpired -> spec re-read and the whole estimate recomputed and equal to the
        bound one -> typed confirmation (real spend) -> exclusive lock -> nothing alive -> consume nonce
        -> spawn. ``--confirm-spend`` is appended here and only here, only when ``real_spend``."""
        rec = self.nonces.peek(nonce, kind)
        fresh = self._fresh_bound(rec)
        if _stable(fresh) != _stable(rec.bound):
            self.nonces.burn(nonce)
            raise ControlError(409, "spec_changed",
                               "the spec (or the selection) changed since the preview; preview again")
        if fresh["max_spend_usd"] > rec.bound["max_spend_usd"] + 0.005:   # only a smaller worst case is safe
            self.nonces.burn(nonce)
            raise ControlError(409, "spec_changed", "the worst-case spend grew since the preview; preview again")
        try:
            check_confirmation(rec.bound, confirm_usd, confirm_runs)
        except ControlError:
            self.nonces.bad_confirmation(nonce)
            raise
        with self.exclusive():
            self._refuse_if_active()
            rec = self.nonces.consume(nonce)
            tail_argv = [*rec.argv_tail, *(self.cfg.run_argv if kind == "launch" else self.cfg.resume_argv)]
            if rec.bound["real_spend"]:
                tail_argv.append("--confirm-spend")
            job = self._spawn("run", tail_argv, rec.bound["run_ids"])
            return self._wait_manifest(job, rec)

    def _fresh_bound(self, rec: NonceRecord) -> dict:
        """Re-derive the estimate from the file on disk (what the CLI will load a moment later)."""
        try:
            loaded = safeyaml.load_spec_safe(rec.spec_file, self.cfg.repo_root)
        except (SpecError, OSError) as exc:
            raise ControlError(409, "spec_changed", f"spec no longer loads: {str(exc)[:300]}") from None
        if rec.kind == "resume":
            return resume_estimate(self.cfg, loaded, rec.meta["run_id"], rec.meta["from_k"])
        return compute_estimate(loaded, self.cfg.repo_root, configs=rec.bound["configs"],
                                repeats=rec.bound["repeats"]) | {"kind": "launch", "spec_path": rec.bound["spec_path"]}

    def _wait_manifest(self, job: dict, rec: NonceRecord) -> dict:
        proc, bound = job["proc"], rec.bound
        want = bound["run_ids"][0]
        deadline = time.monotonic() + self.cfg.launch_wait_s
        while time.monotonic() < deadline:
            m = store.read_json(self.cfg.runs_dir / want / "manifest.json") if valid_run_id(want) else None
            if m and m.get("harness_pid") == proc.pid:
                if m.get("spec_hash") != bound["spec_hash"]:
                    self._emergency_stop(m)
                    raise ControlError(409, "spec_changed", "spec changed during start; run stopped")
                return {"started": True, "manifest_seen": True, "pid": proc.pid, "run_id": want,
                        "run_ids": bound["run_ids"], "log": job["log"].name}
            code = proc.poll()
            if code is not None:
                raise ControlError(500, "launch_failed", f"lrae exited with code {code} before the run started",
                                   log_tail=tail(job["log"]), exit_code=code)
            time.sleep(0.1)
        return {"started": True, "manifest_seen": False, "pid": proc.pid, "run_id": want,
                "run_ids": bound["run_ids"], "log": job["log"].name}

    def _emergency_stop(self, manifest: dict) -> None:
        p = verify_harness(manifest.get("harness_pid"), manifest, self.cfg.repo_root,
                           self.cfg.runs_dir / str(manifest.get("run_id")))
        if p is not None:
            with contextlib.suppress(OSError, psutil.Error):
                os.kill(p.pid, signal.SIGINT)

    # -- other jobs ----------------------------------------------------------------------------
    def start_simple_job(self, kind: str, tail_argv: list[str], wait_s: float) -> dict:
        with self.exclusive():
            self._refuse_if_active()
            job = self._spawn(kind, tail_argv, None)
        proc = job["proc"]
        end = time.monotonic() + wait_s
        while time.monotonic() < end and proc.poll() is None:
            time.sleep(0.1)
        code = proc.poll()
        return {"started": True, "finished": code is not None, "exit_code": code, "pid": proc.pid,
                "log": job["log"].name, "output_tail": tail(job["log"], 4000)}

    # -- signals -------------------------------------------------------------------------------
    def _target(self, run_id: str, manifest: dict) -> psutil.Process:
        p = verify_harness(manifest.get("harness_pid"), manifest, self.cfg.repo_root, self.cfg.runs_dir / run_id)
        if p is None:
            raise ControlError(409, "not_a_live_harness",
                               "no live harness process is verified for this run; nothing was signalled")
        return p

    def stop(self, run_id: str, manifest: dict) -> dict:
        """Graceful stop: SIGINT to the harness pid only. ``lrae run`` has no SIGINT handler, so
        Python raises KeyboardInterrupt in the orchestrator; ``Run.execute`` has no except clause for
        it (only Exception), so its ``finally: _finalize()`` runs: agent terminated, orphans swept,
        decoys/state dir removed, user memory restored, manifest ``end`` written (state FAILED, no
        error text), queued scoring drained. The CLI then exits with the traceback."""
        p = self._target(run_id, manifest)
        if p.pid in self._stop_requested:
            raise ControlError(409, "stop_already_requested",
                               "a stop was already sent; finalizing can take a while. Use kill if it hangs")
        self._stop_requested[p.pid] = time.time()
        os.kill(p.pid, signal.SIGINT)
        return {"signalled": "SIGINT", "pid": p.pid, "run_id": run_id}

    def kill(self, run_id: str, manifest: dict) -> dict:
        """Hard stop: SIGKILL the harness (no cleanup runs), then ``lrae clean`` for the orphans."""
        p = self._target(run_id, manifest)
        pid = p.pid
        os.kill(pid, signal.SIGKILL)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and harness_state(pid) != "gone":
            time.sleep(0.05)
        self._stop_requested.pop(pid, None)
        if self._job_alive() and self.job["pid"] == pid:
            with contextlib.suppress(Exception):
                self.job["proc"].wait(timeout=5)
        cleaned = self.start_simple_job("clean", ["clean"], wait_s=120.0)
        return {"signalled": "SIGKILL", "pid": pid, "run_id": run_id, "clean": cleaned}


# -- resume --------------------------------------------------------------------------------------

def parse_from(text: Any) -> int:
    m = re.fullmatch(r"t?(\d{1,4})", text.strip()) if isinstance(text, str) else None
    if not m or int(m.group(1)) < 1:
        raise ControlError(422, "bad_checkpoint", "from must look like 't2'")
    return int(m.group(1))


def resume_estimate(cfg: ControlConfig, loaded: LoadedSpec, run_id: str, k: int) -> dict:
    mpath = cfg.runs_dir / run_id / "manifest.json"
    m = store.read_json(mpath)
    if not m:
        raise ControlError(404, "no_such_run", "no such run")
    s = loaded.spec
    if loaded.spec_hash != m.get("spec_hash"):
        raise ControlError(409, "spec_changed", "spec changed since the run started; the CLI would refuse to resume")
    if not safefs.is_file(cfg.runs_dir / run_id / "snapshots" / f"t{k}" / "meta.json"):
        raise ControlError(422, "no_snapshot", f"run has no snapshot t{k}")
    done = (m.get("end") or {})
    reasons = spend.spend_reasons(s)
    per_run = money(s.budget.per_run_usd)
    return {
        "kind": "resume", "experiment_id": s.experiment_id, "spec_hash": loaded.spec_hash,
        "spec_path": _rel(cfg.repo_root, loaded.path), "run_id": run_id, "from": f"t{k}",
        "runtime": s.agent.runtime, "model": s.agent.model, "claude_code_version": s.agent.claude_code_version,
        "judge_runtime": s.scoring.judge_runtime, "judge_model": s.scoring.judge_model,
        "real_spend": bool(reasons), "spend_reasons": reasons,
        "configs": [m.get("config")], "repeats": [m.get("repeat")], "run_ids": [run_id], "run_count": 1,
        "per_run_usd": per_run, "per_run_tokens": s.budget.per_run_tokens,
        "experiment_usd": money(s.budget.experiment_usd), "max_spend_usd": per_run, "nominal_cap_usd": per_run,
        "max_spend_basis": "a resume runs one run; the CLI applies no experiment cap to it, only per_run_usd",
        "outside_spec_hash": outside_spec_hash(s),
        "spent_so_far_usd": money(done.get("cost_usd") or 0),
        "duration_min": s.run.duration_min, "checkpoint_interval_min": s.run.checkpoint_interval_min,
        "checkpoint_count": s.run.checkpoint_count,
        "remaining_checkpoints": max(0, s.run.checkpoint_count - k),
        "max_wall_clock_min": round(max(0, s.run.checkpoint_count - k) * s.run.checkpoint_interval_min, 2),
    }


def which_claude() -> str | None:
    return shutil.which("claude")
