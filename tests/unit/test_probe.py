import stat
import sys

import pytest

from runner import memory
from runner.probe import run_probe
from runner.runtimes.claude_code import ClaudeCodeRuntime
from telemetry.events import EventWriter
from telemetry.otlp_receiver import OtlpReceiver

STUB = """#!{python}
import json, os, sys, urllib.request
init = {init}
print(json.dumps(init), flush=True)
if {post}:
    body = {{"resourceLogs": [{{"resource": {{"attributes": []}}, "scopeLogs": [{{"logRecords": [{{
        "body": {{"stringValue": "claude_code.api_request"}},
        "attributes": [{{"key": "event.name", "value": {{"stringValue": "claude_code.api_request"}}}}]}}]}}]}}]}}
    req = urllib.request.Request(os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] + "/v1/logs",
                                 data=json.dumps(body).encode(), headers={{"Content-Type": "application/json"}})
    urllib.request.urlopen(req)
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.03,
                   "session_id": "s"}}), flush=True)
sys.exit({rc})
"""

GOOD_INIT = {"type": "system", "subtype": "init", "session_id": "s", "mcp_servers": [],
             "tools": ["Bash", "Read", "Edit", "Write", "Glob", "Grep"], "model": "x"}


def stub(tmp_path, init=GOOD_INIT, post=True, rc=0):
    p = tmp_path / "claude"
    p.write_text(STUB.format(python=sys.executable, init=repr(init), post=post, rc=rc))
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


@pytest.fixture
def rx(tmp_path):
    w = EventWriter(tmp_path / "otel.jsonl", "r", "otel")
    r = OtlpReceiver(tmp_path / "raw.jsonl", w)
    r.start()
    yield r
    r.stop()


def probe(tmp_path, rx, claude, **kw):
    rt = ClaudeCodeRuntime(claude, "claude-opus-5-5")
    env = {"PATH": "/usr/bin:/bin", "OTEL_EXPORTER_OTLP_ENDPOINT": rx.endpoint}
    return run_probe(runtime=rt, env=env, receiver=rx, probe_dir=tmp_path / "work" / "probe",
                     art=tmp_path / "art", settings_path=tmp_path / "art" / "hs.json",
                     claude_home=tmp_path / "claude-home", otel_wait_s=2.0, **kw)


def test_clean_probe_passes_all_checks(tmp_path, rx):
    res = probe(tmp_path, rx, stub(tmp_path))
    assert all(c.ok for c in res.checks), [c for c in res.checks if not c.ok]
    assert res.cost_usd == 0.03
    assert not (tmp_path / "work" / "probe").exists()


def test_probe_flags_mcp_servers(tmp_path, rx):
    init = dict(GOOD_INIT, mcp_servers=[{"name": "figma", "status": "connected"}])
    res = probe(tmp_path, rx, stub(tmp_path, init=init))
    assert any(not c.ok and "mcp" in c.name for c in res.checks)


def test_probe_flags_missing_telemetry(tmp_path, rx):
    res = probe(tmp_path, rx, stub(tmp_path, post=False))
    bad = [c for c in res.checks if not c.ok]
    assert [c.name for c in bad] == ["L-5 telemetry reaches receiver"]


def test_probe_flags_failed_turn(tmp_path, rx):
    res = probe(tmp_path, rx, stub(tmp_path, rc=1))
    assert any(not c.ok and c.name == "probe: agent replied" for c in res.checks)


def test_probe_deletes_its_state_dir(tmp_path, rx):
    probe_dir = tmp_path / "work" / "probe"
    sd = memory.state_dir(probe_dir, tmp_path / "claude-home")

    # simulate the CLI creating a state dir for the probe cwd while it runs
    class Spy(ClaudeCodeRuntime):
        def build_command(self, ctx):
            sd.mkdir(parents=True, exist_ok=True)
            (sd / "sess.jsonl").write_text("{}")
            return super().build_command(ctx)

    rt = Spy(stub(tmp_path), "claude-opus-5-5")
    env = {"PATH": "/usr/bin:/bin", "OTEL_EXPORTER_OTLP_ENDPOINT": rx.endpoint}
    run_probe(runtime=rt, env=env, receiver=rx, probe_dir=probe_dir, art=tmp_path / "art",
              settings_path=tmp_path / "art" / "hs.json", claude_home=tmp_path / "claude-home",
              otel_wait_s=1.0)
    assert not sd.exists()


def test_probe_failure_detail_carries_the_api_error_text(tmp_path, rx):
    # CLI 1.0.126 + claude-opus-5-5 returns an is_error result explaining the version requirement
    msg = "API Error: 400 Claude Code 1.0.126 does not support this model; version 2.1.280 or newer is required."
    result = {"type": "result", "subtype": "success", "is_error": True, "result": msg}
    stub_path = tmp_path / "claude"
    stub_path.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        f"print(json.dumps({GOOD_INIT!r}), flush=True)\n"
        f"print(json.dumps({result!r}), flush=True)\n"
        "sys.exit(1)\n")
    stub_path.chmod(stub_path.stat().st_mode | stat.S_IEXEC)
    res = probe(tmp_path, rx, str(stub_path))
    bad = next(c for c in res.checks if c.name == "probe: agent replied")
    assert not bad.ok and "2.1.280" in bad.detail
