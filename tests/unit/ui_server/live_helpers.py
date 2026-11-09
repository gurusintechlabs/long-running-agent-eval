"""Helpers for the live-view tests: real-run fixtures and a synthetic appending run."""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ui" / "runs"
HAIKU = "minidb-v3-pilot-haiku-A-r00-f47fe80e"
CANARY_FORBIDDEN = "canary-forbidden-A-r00-fc5ddbfb"
CANARY_HARNESS = "canary-harness-read-A-r00-d8278178"
REAL_RUNS = Path(os.environ.get("LRAE_REAL_RUNS", "/Users/tonylee/Documents/coding/longhorizon_testing/runs"))


def install_fixture(runs_dir: Path, rid: str) -> Path:
    dst = runs_dir / rid
    shutil.copytree(FIXTURES / rid, dst)
    return dst


def read_events(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def envelope(run_id: str, source: str, typ: str, seq: int, payload: dict, ts: str) -> dict:
    return {"ts": ts, "mono_ns": seq * 1000, "run_id": run_id, "source": source, "type": typ, "seq": seq,
            "payload": payload}


def iso(epoch: float) -> str:
    from datetime import UTC, datetime
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


class FakeRun:
    """A run directory a thread appends to the way the harness does (fsync'd JSONL, one file per source).

    ``start()`` begins a background writer; ``append`` writes one event now. The run has no ``end`` in
    its manifest until ``finish()`` and its ``harness_pid`` is this process, so it counts as live.
    """

    def __init__(self, runs_dir: Path, rid: str = "fake-live-A-r00-deadbeef", *, budget_usd=1.0,
                 duration_min=10.0, interval_min=2.0):
        self.rid = rid
        self.dir = runs_dir / rid
        (self.dir / "events").mkdir(parents=True)
        self.t0 = time.time()
        self.seq: dict[str, int] = {}
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.fds: dict[str, int] = {}
        self.manifest = {
            "run_id": rid, "experiment_id": "fake-live", "config": "A", "repeat": 0, "model": "claude-haiku-5-5",
            "runtime": "scripted", "spec_hash": "ab" * 32, "isolation_mode": "local", "start_epoch": self.t0,
            "harness_pid": os.getpid(), "resumed": False, "policy_sha256": "0" * 64,
            "spec": {"experiment_id": "fake-live",
                     "budget": {"per_run_usd": budget_usd, "per_run_tokens": 1_000_000, "experiment_usd": 5.0},
                     "run": {"duration_min": duration_min, "checkpoint_interval_min": interval_min},
                     "agent": {"model": "claude-haiku-5-5", "runtime": "scripted"}},
        }
        self.write_manifest()
        self.append("orchestrator", "run.clock", {"start_epoch": self.t0, "offset_s": 0.0})
        self.append("orchestrator", "state", {"from": "PREPARING", "to": "RUNNING"})

    def write_manifest(self) -> None:
        (self.dir / "manifest.json").write_text(json.dumps(self.manifest))

    def append(self, source: str, typ: str, payload: dict, raw: bytes | None = None) -> None:
        fd = self.fds.get(source)
        if fd is None:
            fd = self.fds[source] = os.open(self.dir / "events" / f"{source}.jsonl",
                                            os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        seq = self.seq.get(source, 0)
        self.seq[source] = seq + 1
        if raw is None:
            raw = (json.dumps(envelope(self.rid, source, typ, seq, payload, iso(time.time()))) + "\n").encode()
        os.write(fd, raw)
        os.fsync(fd)

    def tool(self, n: int, tool: str = "Bash", command: str = "ls") -> None:
        self.append("agent_stream", "tool.call", {"session_id": "s", "tool_use_id": f"t{n}", "tool": tool,
                                                  "input": {"command": command}})
        self.append("agent_stream", "tool.result", {"session_id": "s", "tool_use_id": f"t{n}", "is_error": False,
                                                    "size": 10})

    def api_request(self, cost: float, inp=1000, out=100, cache_read=0, cache_creation=0, source=None) -> None:
        p = {"model": "claude-haiku-5-5", "input_tokens": str(inp), "output_tokens": str(out),
             "cache_read_tokens": str(cache_read), "cache_creation_tokens": str(cache_creation),
             "cost_usd": str(cost)}
        if source is not None:
            p["query_source"] = source
        self.append("otel", "claude_code.api_request", p)

    def start(self, interval_s: float = 0.05, n: int = 10_000) -> None:
        def run():
            i = 0
            while not self.stop.is_set() and i < n:
                self.tool(i)
                self.api_request(0.001)
                i += 1
                time.sleep(interval_s)
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def finish(self, state: str = "COMPLETED", cost: float = 0.0, tokens: int = 0) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(5)
        self.append("orchestrator", "state", {"from": "RUNNING", "to": state})
        self.manifest["end"] = {"state": state, "end_epoch": time.time(), "error": None, "checkpoints": 0,
                                "cost_usd": cost, "tokens": tokens}
        self.write_manifest()

    def close(self) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(5)
        for fd in self.fds.values():
            os.close(fd)
        self.fds.clear()


def snapshot_tree(root: Path) -> dict[str, tuple[int, int, str | None]]:
    """``{relative path: (size, mtime_ns, content digest)}`` of every file below ``root``."""
    import hashlib
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
        else:
            out[str(p.relative_to(root)) + "/"] = (0, 0, None)
    return out
