"""The claude_code runtime path, driven by a stub ``claude`` executable (no API spend)."""
import json
import stat
import sys
from pathlib import Path

import pytest
import yaml

from runner.orchestrator import Run, RunState
from spec.loader import load_spec

pytestmark = pytest.mark.local

STUB = """#!{python}
import json, os, sys, time, urllib.request
argv = sys.argv[1:]
if argv == ["--version"]:
    print("{version} (Claude Code)")
    sys.exit(0)
with open({log!r}, "a") as fh:
    fh.write(json.dumps({{"argv": argv, "user_md_exists": os.path.exists({user_md!r}),
                         "env_keys": sorted(os.environ), "cwd": os.getcwd()}}) + "\\n")
print(json.dumps({{"type": "system", "subtype": "init", "session_id": "s", "mcp_servers": {mcp},
                   "tools": ["Bash", "Read", "Edit", "Write", "Glob", "Grep"], "model": "x"}}), flush=True)
body = {{"resourceLogs": [{{"resource": {{"attributes": []}}, "scopeLogs": [{{"logRecords": [{{
    "body": {{"stringValue": "claude_code.api_request"}},
    "attributes": [{{"key": "event.name", "value": {{"stringValue": "claude_code.api_request"}}}},
                   {{"key": "cost_usd", "value": {{"doubleValue": 0.01}}}}]}}]}}]}}]}}
req = urllib.request.Request(os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] + "/v1/logs",
                             data=json.dumps(body).encode(), headers={{"Content-Type": "application/json"}})
urllib.request.urlopen(req)
time.sleep(0.4)
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.01,
                   "session_id": "s"}}), flush=True)
"""


@pytest.fixture
def real(env):
    log = env["tmp"] / "stub-calls.jsonl"
    user_md = env["claude_home"] / "CLAUDE.md"
    user_md.write_bytes(b"my private memory\n")
    (env["claude_home"] / "rules").mkdir()
    (env["claude_home"] / "rules" / "r.md").write_text("rule")

    def build(version="1.0.126", mcp="[]", keep_work=True, runtime_version="1.0.126"):
        stub = env["tmp"] / "bin" / "claude"
        stub.parent.mkdir(exist_ok=True)
        stub.write_text(STUB.format(python=sys.executable, version=version, log=str(log),
                                    user_md=str(user_md), mcp=mcp))
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        spec = yaml.safe_load(env["spec_path"].read_text())
        spec["agent"] = {"runtime": "claude_code", "claude_bin": str(stub),
                         "claude_code_version": runtime_version, "model": "claude-opus-5-5"}
        spec["run"].update(duration_min=3.0 / 60, checkpoint_interval_min=1.5 / 60)
        spec["isolation"]["keep_work_dir"] = keep_work
        env["spec_path"].write_text(yaml.safe_dump(spec))
        return load_spec(env["spec_path"], repo_root=env["repo_root"])

    def run(loaded, confirm=True):
        r = Run(loaded, "A", 0, repo_root=env["repo_root"], claude_home=env["claude_home"],
                host_home=env["home"], confirm_spend=confirm, caffeinate=False)
        return r.execute()

    calls = lambda: [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []  # noqa: E731
    return dict(build=build, run=run, calls=calls, user_md=user_md, **env)


def test_full_real_agent_path_with_stub(real):
    res = real["run"](real["build"]())
    assert res.state == RunState.COMPLETED, res.error
    calls = real["calls"]()
    assert len(calls) >= 3  # probe + at least two turns
    probe, first, later = calls[0], calls[1], calls[2:]
    assert "Reply with the single word OK." in probe["argv"]
    for c in calls:
        a = c["argv"]
        assert a[0] == "-p" and a[a.index("--model") + 1] == "claude-opus-5-5"
        assert a[a.index("--setting-sources") + 1] == "project,local"
        assert "--strict-mcp-config" in a and "--dangerously-skip-permissions" in a
        assert a[a.index("--output-format") + 1] == "stream-json"
        assert Path(a[a.index("--settings") + 1]).name == "harness-settings.json"
        assert c["user_md_exists"] is False, "user CLAUDE.md must be hidden while the agent runs"
        assert "GITHUB_TOKEN" not in c["env_keys"] and "ANTHROPIC_API_KEY" not in c["env_keys"]
    assert "--session-id" in first["argv"] and "--resume" not in first["argv"]
    sid = first["argv"][first["argv"].index("--session-id") + 1]
    assert all(c["argv"][c["argv"].index("--resume") + 1] == sid for c in later)
    assert first["cwd"].endswith("/workspace") and probe["cwd"].endswith("/probe")
    assert real["user_md"].read_bytes() == b"my private memory\n"
    assert (real["claude_home"] / "rules" / "r.md").read_text() == "rule"
    manifest = json.loads(res.paths.manifest.read_text())
    assert manifest["user_memory"]["mechanism"] == "move_aside"
    assert set(manifest["user_memory"]["moved"]) == {"CLAUDE.md", "rules"}
    assert not (res.paths.work / "probe").exists()


def test_refuses_real_agent_without_spend_confirmation(real):
    res = real["run"](real["build"](), confirm=False)
    assert res.state == RunState.FAILED and "spend confirmed" in res.error
    assert real["calls"]() == [], "no agent process may start"
    assert real["user_md"].read_bytes() == b"my private memory\n"


def test_cli_version_mismatch_stops_before_any_turn(real):
    res = real["run"](real["build"](version="1.0.999"))
    assert res.state == RunState.FAILED and "L-6" in res.error and "1.0.999" in res.error
    assert real["calls"]() == []


def test_probe_failure_aborts_and_restores_user_memory(real):
    res = real["run"](real["build"](mcp='[{"name": "figma", "status": "connected"}]'))
    assert res.state == RunState.FAILED and "mcp" in res.error.lower()
    assert len(real["calls"]()) == 1, "only the probe may have run"
    assert real["user_md"].read_bytes() == b"my private memory\n"
    assert (real["claude_home"] / "rules" / "r.md").exists()
    assert not (real["repo_root"] / "runs" / ".user-memory.lock").exists()
