"""Scripted stand-in for ``claude -p`` (docs/spec.md §5.3).

Replays a YAML script of timed actions inside the workspace, emits Claude-Code-shaped
``stream-json`` on stdout and OTLP records to the run's receiver. It runs as a real subprocess
so the harness exercises exactly the same pause/kill/sweep paths as with the real agent.
Used for every automated test and for the guardrail canaries (no API spend, deterministic).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml

REQUIRED = {
    "write_file": {"path", "content"},
    "git_commit": {"message"},
    "bash": {"cmd"},
    "emit_otel": {"event"},
    "emit_otel_metric": {"name", "value"},
    "emit_stream_event": {"event"},
    "sleep": {"seconds"},
    "mcp_call": {"server", "tool"},  # call a tool of a counterpart MCP server (as the CLI would)
    "http": {"method", "url"},       # a request to a counterpart; {VAR} in url/headers from the env
    "end_turn": set(),   # finish this turn (the agent declares its current work done)
    "fail_turn": set(),  # end this turn with a non-zero exit (crash / API error)
}
FIXED_DATE = "2026-01-01T00:00:00Z"


class ScriptError(ValueError):
    pass


def load_script(path: Path | str) -> dict:
    doc = yaml.safe_load(Path(path).read_text()) or {}
    actions = doc.get("actions", [])
    for i, act in enumerate(actions):
        kind = act.get("do")
        if kind not in REQUIRED:
            raise ScriptError(f"action {i}: unknown 'do': {kind!r}")
        missing = REQUIRED[kind] - set(act)
        if missing:
            raise ScriptError(f"action {i} ({kind}): missing {sorted(missing)}")
    doc["actions"] = actions
    doc.setdefault("idle_s", 0.2)
    return doc


def _attr(key: str, value) -> dict:
    if isinstance(value, bool):
        v = {"boolValue": value}
    elif isinstance(value, int):
        v = {"intValue": str(value)}
    elif isinstance(value, float):
        v = {"doubleValue": value}
    else:
        v = {"stringValue": str(value)}
    return {"key": key, "value": v}


def _resource_attrs() -> list[dict]:
    raw = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
    pairs = [kv.split("=", 1) for kv in raw.split(",") if "=" in kv]
    return [_attr(k, v) for k, v in pairs]


def otlp_log_payload(event: str, attrs: dict) -> dict:
    now = str(int(time.time() * 1e9))
    rec = {"timeUnixNano": now, "body": {"stringValue": event},
           "attributes": [_attr("event.name", event), *[_attr(k, v) for k, v in attrs.items()]]}
    return {"resourceLogs": [{"resource": {"attributes": _resource_attrs()},
                              "scopeLogs": [{"logRecords": [rec]}]}]}


def otlp_metric_payload(name: str, value: float, attrs: dict) -> dict:
    dp = {"timeUnixNano": str(int(time.time() * 1e9)), "asDouble": float(value),
          "attributes": [_attr(k, v) for k, v in attrs.items()]}
    return {"resourceMetrics": [{"resource": {"attributes": _resource_attrs()},
                                 "scopeMetrics": [{"metrics": [{"name": name,
                                                                "sum": {"dataPoints": [dp]}}]}]}]}


class ScriptedAgent:
    def __init__(self, script: dict, *, workspace: Path, otel_endpoint: str | None,
                 run_start_epoch: float, session_id: str, out, state_path: Path,
                 clock=time.time, sleep=time.sleep, mcp_config: Path | None = None):
        self.script = script
        self.workspace = Path(workspace).resolve()
        self.endpoint = otel_endpoint
        self.run_start = run_start_epoch
        self.session_id = session_id
        self.out = out
        self.state_path = Path(state_path)
        self.clock = clock
        self.sleep = sleep
        self.max_actions_per_turn: int | None = None
        self.mcp_config = Path(mcp_config) if mcp_config else None
        self.cost_total = 0.0
        self._n = 0

    # -- output ---------------------------------------------------------------------------
    def _emit(self, msg: dict) -> None:
        msg.setdefault("session_id", self.session_id)
        self.out.write(json.dumps(msg) + "\n")
        self.out.flush()

    def _tool_use(self, name: str, tool_input: dict) -> None:
        self._n += 1
        self._emit({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"toolu_{self._n:04d}", "name": name, "input": tool_input}]}})

    def _post(self, path: str, payload: dict) -> None:
        if not self.endpoint:
            return
        req = urllib.request.Request(self.endpoint + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:  # like the CLI's exporter: a failed export is dropped, the agent keeps working
            with urllib.request.urlopen(req, timeout=10):
                pass
        except OSError as exc:
            print(f"otel export failed: {exc}", file=sys.stderr)

    # -- state across turns ---------------------------------------------------------------
    def _done(self) -> int:
        try:
            return int(json.loads(self.state_path.read_text())["done"])
        except (OSError, ValueError, KeyError):
            return 0

    def _set_done(self, n: int) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"done": n}))

    # -- actions --------------------------------------------------------------------------
    def _inside(self, path: Path, allow_outside: bool) -> Path:
        full = (self.workspace / path).resolve()
        if not allow_outside and self.workspace not in (full, *full.parents):
            raise ScriptError(f"write_file path is outside the workspace: {path}")
        return full

    def _do(self, act: dict) -> None:
        kind = act["do"]
        if kind == "write_file":
            full = self._inside(Path(act["path"]), bool(act.get("allow_outside")))
            self._tool_use("Write", {"file_path": str(full), "content": act["content"]})
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(act["content"])
        elif kind == "git_commit":
            self._tool_use("Bash", {"command": f"git add -A && git commit -m {json.dumps(act['message'])}"})
            env = dict(os.environ, GIT_AUTHOR_DATE=FIXED_DATE, GIT_COMMITTER_DATE=FIXED_DATE)
            # explicit identity: the scripted agent must not depend on the host's git config
            for cmd in (["git", "add", "-A"],
                        ["git", "-c", "user.name=agent", "-c", "user.email=agent@lrae.local",
                         "commit", "-q", "--allow-empty", "-m", act["message"]]):
                subprocess.run(cmd, cwd=self.workspace, env=env, check=False, capture_output=True)
        elif kind == "bash":
            self._tool_use("Bash", {"command": act["cmd"]})
            subprocess.run(act["cmd"], shell=True, cwd=self.workspace, timeout=act.get("timeout", 120),
                           check=False, capture_output=True)
        elif kind == "emit_otel":
            attrs = dict(act.get("attrs", {}))
            self.cost_total += float(attrs.get("cost_usd", 0) or 0)
            self._post("/v1/logs", otlp_log_payload(act["event"], attrs))
        elif kind == "emit_otel_metric":
            self._post("/v1/metrics", otlp_metric_payload(act["name"], act["value"],
                                                          act.get("attrs", {})))
        elif kind == "emit_stream_event":
            self._emit(dict(act["event"]))
        elif kind == "sleep":
            self.sleep(float(act["seconds"]))
        elif kind == "mcp_call":
            self._mcp_call(act["server"], act["tool"], act.get("arguments") or {})
        elif kind == "http":
            self._http(act)

    def _mcp_call(self, server: str, tool: str, arguments: dict) -> None:
        """Start the server from the run's MCP config and speak JSON-RPC over stdio, as the CLI does."""
        if self.mcp_config is None:
            raise ScriptError("mcp_call needs --mcp-config")
        cfg = json.loads(self.mcp_config.read_text())["mcpServers"][server]
        self._tool_use(f"mcp__{server}__{tool}", arguments)
        use_id = f"toolu_{self._n:04d}"
        proc = subprocess.Popen([cfg["command"], *cfg.get("args", [])], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True, env={**os.environ, **cfg.get("env", {})})
        try:
            def rpc(msg):
                proc.stdin.write(json.dumps(msg) + "\n")
                proc.stdin.flush()
                return json.loads(proc.stdout.readline()) if "id" in msg else None
            rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "scripted", "version": "0"}}})
            rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
            out = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": tool, "arguments": arguments}})["result"]
        finally:
            proc.stdin.close()
            proc.wait(timeout=10)
        self._emit({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": use_id, "is_error": bool(out.get("isError")),
             "content": out["content"]}]}})

    def _http(self, act: dict) -> None:
        """A request to a counterpart (e.g. ``{EMBED_URL}/v1/embed``); only the effect, no tool event."""
        fmt = lambda s: str(s).format(**os.environ)  # noqa: E731
        data = json.dumps(act["json"]).encode() if "json" in act else None
        req = urllib.request.Request(fmt(act["url"]), data=data, method=act["method"],
                                     headers={"Content-Type": "application/json",
                                              **{k: fmt(v) for k, v in (act.get("headers") or {}).items()}})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=10):
                pass
        except OSError:  # 4xx/5xx are the counterpart's answer; the scripted agent just moves on
            pass

    def run(self) -> int:
        """Replay actions up to the next ``end_turn``/``fail_turn`` (or the end). Returns the exit code."""
        self._emit({"type": "system", "subtype": "init", "cwd": str(self.workspace),
                    "tools": ["Bash", "Edit", "Read", "Write", "Glob", "Grep"], "mcp_servers": [],
                    "model": "scripted", "permissionMode": "bypassPermissions"})
        actions = self.script["actions"]
        done = self._done()
        ran = 0
        while done < len(actions) and (self.max_actions_per_turn is None or ran < self.max_actions_per_turn):
            act = actions[done]
            if act["do"] in ("end_turn", "fail_turn"):
                self._set_done(done + 1)
                if act["do"] == "fail_turn":
                    self._emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
                                "total_cost_usd": self.cost_total, "num_turns": ran})
                    return 1
                break
            if "at" in act:
                wait = self.run_start + float(act["at"]) - self.clock()
                if wait > 0:
                    self.sleep(wait)
            self._do(act)
            done += 1
            ran += 1
            self._set_done(done)
        if ran == 0:
            idle = float(self.script.get("idle_s", 0.2))
            if idle > 0:
                self.sleep(idle)
        self._emit({"type": "result", "subtype": "success", "is_error": False,
                    "total_cost_usd": self.cost_total, "num_turns": ran})
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--otel", default=None)
    ap.add_argument("--run-start", type=float, required=True)
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--mcp-config", default=None)
    args = ap.parse_args(argv)
    agent = ScriptedAgent(load_script(args.script), workspace=Path(args.workspace),
                          otel_endpoint=args.otel, run_start_epoch=args.run_start,
                          session_id=args.session_id, out=sys.stdout, state_path=Path(args.state),
                          mcp_config=args.mcp_config)
    return agent.run()


if __name__ == "__main__":
    sys.exit(main())
