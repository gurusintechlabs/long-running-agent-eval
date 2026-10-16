import io
import json
import os
import subprocess

import pytest
import yaml

from runner.runtimes.scripted_agent import ScriptedAgent, ScriptError, load_script
from telemetry.events import EventWriter
from telemetry.otlp_receiver import OtlpReceiver


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(round(s, 6))
        self.t += s


def git(cwd, *a):
    env = dict(os.environ, GIT_AUTHOR_NAME="a", GIT_AUTHOR_EMAIL="a@a", GIT_COMMITTER_NAME="a",
               GIT_COMMITTER_EMAIL="a@a")
    return subprocess.run(["git", *a], cwd=cwd, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    w.mkdir()
    git(w, "init", "-q", "-b", "main")
    (w / "seed.txt").write_text("seed\n")
    git(w, "add", "-A")
    git(w, "commit", "-q", "-m", "seed")
    return w


def script(tmp_path, actions, **hdr):
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump({"actions": actions, **hdr}))
    return load_script(p)


def agent(tmp_path, ws, actions, clock=None, run_start=1000.0, endpoint=None, **hdr):
    clock = clock or FakeClock()
    out = io.StringIO()
    a = ScriptedAgent(script(tmp_path, actions, **hdr), workspace=ws, otel_endpoint=endpoint,
                      run_start_epoch=run_start, session_id="sess-1", out=out,
                      state_path=tmp_path / "state.json", clock=clock.now, sleep=clock.sleep)
    return a, out, clock


def stream(out):
    return [json.loads(x) for x in out.getvalue().splitlines()]


def test_load_rejects_unknown_action(tmp_path):
    with pytest.raises(ScriptError):
        script(tmp_path, [{"do": "explode"}])


def test_load_rejects_missing_fields(tmp_path):
    with pytest.raises(ScriptError):
        script(tmp_path, [{"do": "write_file", "path": "a"}])


def test_actions_run_in_order_and_stream_shape(tmp_path, ws):
    a, out, _ = agent(tmp_path, ws, [
        {"do": "write_file", "path": "n.txt", "content": "hi\n"},
        {"do": "bash", "cmd": "echo ok > b.txt"},
        {"do": "git_commit", "message": "add"},
    ])
    a.run()
    assert (ws / "n.txt").read_text() == "hi\n" and (ws / "b.txt").read_text().strip() == "ok"
    assert git(ws, "log", "--format=%s", "-1") == "add"
    msgs = stream(out)
    assert msgs[0]["type"] == "system" and msgs[0]["subtype"] == "init"
    assert msgs[0]["session_id"] == "sess-1" and msgs[0]["mcp_servers"] == []
    tools = [m["message"]["content"][0] for m in msgs if m["type"] == "assistant"]
    assert [t["name"] for t in tools] == ["Write", "Bash", "Bash"]
    assert tools[1]["input"]["command"] == "echo ok > b.txt"
    assert msgs[-1]["type"] == "result" and msgs[-1]["subtype"] == "success"


def test_at_offsets_sleep_until_run_start_plus_at(tmp_path, ws):
    a, _, clock = agent(tmp_path, ws, [
        {"at": 2.0, "do": "bash", "cmd": "true"}, {"at": 5.0, "do": "bash", "cmd": "true"}],
        run_start=1000.0, idle_s=0)
    a.run()
    assert clock.sleeps[:2] == [2.0, 3.0]


def test_at_in_the_past_does_not_sleep(tmp_path, ws):
    clock = FakeClock(t=1010.0)
    a, _, _ = agent(tmp_path, ws, [{"at": 1.0, "do": "bash", "cmd": "true"}], clock=clock,
                    run_start=1000.0, idle_s=0)
    a.run()
    assert clock.sleeps == []


def test_second_turn_resumes_remaining_actions_only(tmp_path, ws):
    acts = [{"do": "bash", "cmd": "echo 1 >> count.txt"}, {"do": "bash", "cmd": "echo 2 >> count.txt"}]
    a, _, _ = agent(tmp_path, ws, acts, idle_s=0)
    a.max_actions_per_turn = 1
    a.run()
    assert (ws / "count.txt").read_text() == "1\n"
    a2, out2, _ = agent(tmp_path, ws, acts, idle_s=0)
    a2.max_actions_per_turn = 1
    a2.run()
    assert (ws / "count.txt").read_text() == "1\n2\n"
    a3, out3, _ = agent(tmp_path, ws, acts, idle_s=0)  # nothing left: idles, still emits a result
    a3.run()
    assert (ws / "count.txt").read_text() == "1\n2\n" and stream(out3)[-1]["type"] == "result"


def test_idle_turn_sleeps_idle_s(tmp_path, ws):
    a, _, clock = agent(tmp_path, ws, [], idle_s=0.7)
    a.run()
    assert clock.sleeps == [0.7]


def test_write_file_outside_workspace_rejected_unless_allowed(tmp_path, ws):
    a, _, _ = agent(tmp_path, ws, [{"do": "write_file", "path": "../escape.txt", "content": "x"}])
    with pytest.raises(ScriptError, match="outside"):
        a.run()
    assert not (tmp_path / "escape.txt").exists()
    a2, _, _ = agent(tmp_path, ws, [{"do": "write_file", "path": "../ok.txt", "content": "x",
                                     "allow_outside": True}])
    (tmp_path / "state.json").unlink(missing_ok=True)
    a2.run()
    assert (tmp_path / "ok.txt").exists()


def test_failed_bash_is_reported_not_fatal(tmp_path, ws):
    a, out, _ = agent(tmp_path, ws, [{"do": "bash", "cmd": "exit 3"}, {"do": "bash", "cmd": "echo after > a.txt"}])
    a.run()
    assert (ws / "a.txt").exists()


def test_emit_otel_reaches_receiver(tmp_path, ws):
    w = EventWriter(tmp_path / "otel.jsonl", "r1", "otel")
    rx = OtlpReceiver(tmp_path / "raw.jsonl", w)
    rx.start()
    try:
        a, _, _ = agent(tmp_path, ws, [
            {"do": "emit_otel", "event": "claude_code.api_request",
             "attrs": {"cost_usd": 0.02, "input_tokens": 120, "model": "claude-opus-5-5"}},
            {"do": "emit_otel_metric", "name": "claude_code.cost.usage", "value": 0.02,
             "attrs": {"model": "claude-opus-5-5"}}],
            endpoint=rx.endpoint)
        os.environ["OTEL_RESOURCE_ATTRIBUTES"] = "lrae.run_id=r1"
        a.run()
    finally:
        os.environ.pop("OTEL_RESOURCE_ATTRIBUTES", None)
        rx.stop()
    ev = [json.loads(x) for x in (tmp_path / "otel.jsonl").read_text().splitlines()]
    assert [e["type"] for e in ev] == ["claude_code.api_request", "claude_code.cost.usage"]
    assert ev[0]["payload"]["cost_usd"] == 0.02 and ev[0]["payload"]["_resource"] == {"lrae.run_id": "r1"}


def test_result_reports_scripted_cost_total(tmp_path, ws):
    a, out, _ = agent(tmp_path, ws, [
        {"do": "emit_otel", "event": "claude_code.api_request", "attrs": {"cost_usd": 0.02}},
        {"do": "emit_otel", "event": "claude_code.api_request", "attrs": {"cost_usd": 0.03}}],
        endpoint=None)
    a.run()
    assert stream(out)[-1]["total_cost_usd"] == pytest.approx(0.05)


def test_emit_stream_event_passthrough(tmp_path, ws):
    a, out, _ = agent(tmp_path, ws, [{"do": "emit_stream_event", "event": {"type": "custom", "x": 1}}])
    a.run()
    assert {"type": "custom", "x": 1, "session_id": "sess-1"} in stream(out)
