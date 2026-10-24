"""Helpers for the U5 control tests: a throwaway repo with a scripted spec, and a fake spawner."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import psutil
import yaml

from tests.integration.conftest import DT_S, DURATION_S, git, make_script
from tests.unit.ui_server.conftest import AUTH, BASE

CODE_ROOT = Path(__file__).resolve().parents[3]
FAKE_PID = 4_000_001   # above the kernel's pid range: never a live process


def make_repo(tmp: Path, *, runtime: str = "scripted", judge: str = "scripted", name: str = "ctl-test") -> dict:
    """tmp/repo/spec/examples/<name>.yaml (+ assets), runs dir, claude home, fake HOME."""
    repo = tmp / "repo"
    (repo / "spec" / "examples").mkdir(parents=True)
    (repo / "runs").mkdir()
    assets = repo / "spec" / "assets"
    assets.mkdir()
    claude, home, seed = tmp / "claude", tmp / "home", tmp / "seed"
    for d in (claude, home, seed):
        d.mkdir()
    git(seed, "init", "-q", "-b", "main")
    (seed / "app.py").write_text("print('seed')\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "seed")
    sha = git(seed, "rev-parse", "HEAD")
    (assets / "prompt.md").write_text("Do the task.\n")
    (assets / "constraints.yaml").write_text("constraints: []\n")
    (assets / "policy.yaml").write_text("forbidden_commands: []\n")
    (assets / "req.lock").write_text("")
    (assets / "hidden").mkdir()
    (assets / "hidden" / "t.py").write_text("x=1\n")
    make_script(assets / "script.yaml")
    agent = ({"runtime": "scripted", "claude_code_version": "n/a", "script": "../assets/script.yaml"}
             if runtime == "scripted" else
             {"runtime": "claude_code", "claude_code_version": "2.1.301", "model": "claude-opus-5-5"})
    spec = {
        "spec_version": 1, "experiment_id": name,
        "task": {"id": "t", "class": "L1", "prompt_file": "../assets/prompt.md", "seed_repo": str(seed),
                 "seed_commit": sha, "seed_requirements_lock": "../assets/req.lock",
                 "constraints_file": "../assets/constraints.yaml", "hidden_tests": "../assets/hidden"},
        "agent": agent,
        "run": {"duration_min": DURATION_S / 60, "checkpoint_interval_min": DT_S / 60, "repeats": 2,
                "configs": ["A"], "seed": 1},
        "budget": {"per_run_usd": 3.0, "experiment_usd": 5.0},
        "isolation": {"mode": "local", "work_dir": str(home / "lrae-work")},
        "telemetry": {"export_interval_ms": 200},
        "guardrails": {"policy_file": "../assets/policy.yaml"},
        "scoring": {"judge_model": "claude-opus-5-5", "judge_runtime": judge},
    }
    path = repo / "spec" / "examples" / f"{name}.yaml"
    path.write_text(yaml.safe_dump(spec))
    return dict(tmp=tmp, repo=repo, runs=repo / "runs", claude=claude, home=home, spec=path,
                rel=f"spec/examples/{name}.yaml", assets=assets)


class FakeProc:
    def __init__(self, pid: int = FAKE_PID):
        self.pid, self.code = pid, None

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        return self.code

    def finish(self, code: int = 0):
        self.code = code


class FakeSpawner:
    """Records what would have been started; never starts anything."""

    def __init__(self):
        self.calls: list[dict] = []
        self.auto_finish = False

    def __call__(self, argv, env, cwd, log_path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("fake launch log\n")
        proc = FakeProc()
        if self.auto_finish:
            proc.finish(0)
        self.calls.append({"argv": list(argv), "env": dict(env), "cwd": cwd, "log": log_path, "proc": proc})
        return proc

    def verbs(self) -> list[str]:
        """The lrae verb of every spawn (run, resume, score, clean)."""
        out = []
        for c in self.calls:
            a = c["argv"]
            out.append(next(x for x in a[a.index("runner.cli") + 1:] if x in ("run", "resume", "score", "clean")))
        return out

    def spawning(self):
        return [c for c, v in zip(self.calls, self.verbs(), strict=True) if v in ("run", "resume")]


def make_client(settings, edit=None):
    from fastapi.testclient import TestClient

    from ui_server.app import create_app
    app = create_app(settings)
    if edit:
        edit(app.state.control)
    c = TestClient(app, base_url=BASE)
    c.headers.update(AUTH)
    return app, c


def spawn_lookalike(tmp: Path, *args: str) -> subprocess.Popen:
    """A sleeper whose command line is ``python -m runner.cli ... run`` (the module is a stub in tmp)."""
    d = tmp / "fakeharness"
    (d / "runner").mkdir(parents=True, exist_ok=True)
    (d / "runner" / "__init__.py").write_text("")
    (d / "runner" / "cli.py").write_text("import time\ntime.sleep(120)\n")
    return subprocess.Popen([sys.executable, "-m", "runner.cli", "--repo-root", str(tmp), "run", *args],
                            cwd=d, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def write_manifest(runs: Path, rid: str, **kw) -> Path:
    d = runs / rid
    d.mkdir(parents=True, exist_ok=True)
    m = {"run_id": rid, "experiment_id": "x", "config": "A", "repeat": 0, "spec_hash": "h",
         "start_epoch": time.time()}
    m.update(kw)
    (d / "manifest.json").write_text(json.dumps(m))
    return d / "manifest.json"


def alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
