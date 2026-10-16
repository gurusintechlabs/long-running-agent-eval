"""Per-run folders, the scrubbed agent environment and seed cloning (docs/spec.md §3.2, §5.1)."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from runner.memory import check_seed_checkout

# Host variables the agent may inherit (spec §3.2 L-2). Everything else is dropped.
ALLOWED_ENV_KEYS = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "TERM", "TMPDIR",
    "CLAUDE_CODE_ENABLE_TELEMETRY", "DISABLE_AUTOUPDATER", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
})
_PASSTHROUGH = ("HOME", "USER", "LOGNAME", "LANG", "TERM")
_SYSTEM_PATH = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]


class WorkdirError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    work: Path  # agent-facing, outside the repo
    art: Path   # harness artifacts, inside the repo (gitignored), never given to the agent

    @classmethod
    def for_run(cls, run_id: str, work_dir: Path, repo_root: Path) -> RunPaths:
        return cls(run_id, Path(work_dir) / run_id, Path(repo_root) / "runs" / run_id)

    workspace = property(lambda s: s.work / "workspace")
    tmp = property(lambda s: s.work / "tmp")
    venv = property(lambda s: s.work / "venv")
    events = property(lambda s: s.art / "events")
    otel_raw = property(lambda s: s.art / "events" / "otel")
    snapshots = property(lambda s: s.art / "snapshots")
    mirror = property(lambda s: s.art / "mirror.git")
    manifest = property(lambda s: s.art / "manifest.json")
    harness_settings = property(lambda s: s.art / "harness-settings.json")

    def create(self) -> None:
        for base in (self.work, self.art):
            if base.exists():
                raise FileExistsError(f"run folder already exists: {base}")
        for d in (self.workspace.parent, self.tmp, self.events, self.otel_raw, self.snapshots):
            d.mkdir(parents=True)

    def create_work(self) -> None:
        """Resume: artifacts already exist; recreate only the agent-facing folders."""
        if self.work.exists():
            raise FileExistsError(f"run folder already exists: {self.work}")
        self.workspace.parent.mkdir(parents=True)
        self.tmp.mkdir()
        for d in (self.events, self.otel_raw, self.snapshots):
            d.mkdir(parents=True, exist_ok=True)

    def remove_work(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)


def build_agent_env(*, host_env: dict[str, str], tmpdir: Path, path_dirs: list[str],
                    otel_endpoint: str, protocol: str, export_interval_ms: int,
                    resource_attrs: dict[str, str]) -> dict[str, str]:
    """Allowlisted environment for ``claude`` (spec §3.2 L-2). Nothing else is inherited."""
    env = {k: host_env[k] for k in _PASSTHROUGH if k in host_env}
    seen: list[str] = []
    for d in [*path_dirs, *_SYSTEM_PATH]:
        if d not in seen:
            seen.append(d)
    env["PATH"] = ":".join(seen)
    env["TMPDIR"] = str(tmpdir)
    env["DISABLE_AUTOUPDATER"] = "1"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    env.update(_otel_env(otel_endpoint, protocol, export_interval_ms, resource_attrs))
    return env


def _otel_env(endpoint: str, protocol: str, interval_ms: int, attrs: dict[str, str]) -> dict[str, str]:
    return {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": protocol,
        "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        "OTEL_METRIC_EXPORT_INTERVAL": str(interval_ms),
        "OTEL_LOGS_EXPORT_INTERVAL": str(interval_ms),
        "OTEL_RESOURCE_ATTRIBUTES": ",".join(f"{k}={v}" for k, v in attrs.items()),
    }


def harness_settings(*, otel_endpoint: str, protocol: str, export_interval_ms: int,
                     resource_attrs: dict[str, str], permissions_deny: list[str] | None = None) -> dict:
    """Contents of ``harness-settings.json`` passed with ``--settings`` (spec §3.2 L-5)."""
    settings: dict = {"env": _otel_env(otel_endpoint, protocol, export_interval_ms, resource_attrs)}
    if permissions_deny:
        settings["permissions"] = {"deny": permissions_deny}
    return settings


def _git(cwd: Path | None, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise WorkdirError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def clone_seed(seed_repo: Path, seed_commit: str, workspace: Path) -> None:
    """Clone the seed at an exact commit into ``workspace``; sever any link back to the fixture."""
    try:
        _git(None, "clone", "-q", "--no-hardlinks", str(seed_repo), str(workspace))
        _git(workspace, "checkout", "-q", "--detach", seed_commit)
    except WorkdirError as exc:
        shutil.rmtree(workspace, ignore_errors=True)
        raise WorkdirError(f"cannot check out seed commit {seed_commit}: {exc}") from exc
    head = _git(workspace, "rev-parse", "HEAD")
    if head != seed_commit:
        raise WorkdirError(f"seed HEAD {head} != expected {seed_commit}")
    _git(workspace, "remote", "remove", "origin")
    _git(workspace, "config", "--local", "user.name", "agent")
    _git(workspace, "config", "--local", "user.email", "agent@lrae.local")
    _git(workspace, "checkout", "-q", "-B", "main")
    try:
        check_seed_checkout(workspace)
    except Exception:
        shutil.rmtree(workspace, ignore_errors=True)
        raise


def build_venv(venv: Path, lock_file: Path, cache_dir: Path, python: str | None = None) -> None:
    """Create the run venv from the seed's requirements lock, using a shared wheel cache."""
    import sys
    subprocess.run([python or sys.executable, "-m", "venv", str(venv)], check=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(venv / "bin" / "pip"), "install", "-q", "--disable-pip-version-check",
                    "--cache-dir", str(cache_dir), "-r", str(lock_file)], check=True)


def pip_freeze(venv: Path) -> str:
    out = subprocess.run([str(venv / "bin" / "pip"), "freeze"], capture_output=True, text=True,
                         check=True)
    return out.stdout


def resolve_path_dirs(claude_bin: str, venv: Path | None) -> list[str]:
    """PATH directories for the agent: the run venv, the folder holding claude, and node's."""
    dirs: list[str] = []
    if venv is not None:
        dirs.append(str(venv / "bin"))
    for tool in (claude_bin, "node", "git"):
        found = shutil.which(tool)
        if found:
            d = str(Path(found).parent)
            if d not in dirs:
                dirs.append(d)
    return dirs
