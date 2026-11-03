import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from guardrails.monitor import GuardrailMonitor, integrity_hashes
from guardrails.policy import load_policy
from telemetry.events import EventWriter

RULES = Path(__file__).resolve().parents[2] / "guardrails" / "rules" / "default.yaml"


class FakeClock:
    def __init__(self):
        self.m = 1000.0
        self.w = 1_760_000_000.0

    def mono(self):
        return self.m

    def wall(self):
        return self.w

    def advance(self, s, wall_extra=0.0):
        self.m += s
        self.w += s + wall_extra


def iso(epoch):
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Rig:
    def __init__(self, tmp_path, **kw):
        self.base = tmp_path.resolve()
        self.home, self.work, self.repo = self.base / "home", self.base / "work", self.base / "repo"
        self.state = self.home / ".claude" / "projects" / "-work"
        for d in (self.home, self.work, self.repo / "fixtures" / "tasks" / "t" / "hidden", self.state):
            d.mkdir(parents=True, exist_ok=True)
        self.events = self.base / "events"
        self.events.mkdir()
        self.stream, self.otel = self.events / "agent_stream.jsonl", self.events / "otel.jsonl"
        self.clock = FakeClock()
        self.log = []
        self.guard = self.events / "guardrail.jsonl"
        self.writer = EventWriter(self.guard, "r", "guardrail")
        pol = load_policy(RULES).bind(self.work, self.repo, self.state, self.home)
        self.mon = GuardrailMonitor(
            events_dir=self.events, policy=pol, writer=self.writer, clock=self.clock,
            on_kill=lambda v: self.log.append(("kill", v.rule_id)),
            on_pause=lambda: self.log.append(("pause",)), on_resume=lambda: self.log.append(("resume",)),
            on_budget=lambda c, t: self.log.append(("budget", round(c, 4), t)),
            on_interrupt=lambda k, d: self.log.append(("interrupt", k)),
            workspace=self.work, seed_files={}, **kw)
        self.seq = 0

    def write(self, path, etype, payload, ts=None, raw=False):
        self.seq += 1
        ev = {"ts": ts or iso(self.clock.w), "mono_ns": 0, "run_id": "r", "source": "x", "type": etype,
              "seq": self.seq, "payload": payload}
        with open(path, "a") as fh:
            fh.write(json.dumps(ev) + "\n")

    def call(self, command, tool="Bash", **inp):
        self.write(self.stream, "tool.call", {"session_id": "s", "tool_use_id": "t", "tool": tool,
                                              "input": inp or {"command": command}})

    def api(self, cost, **extra):
        self.write(self.otel, "claude_code.api_request",
                   {"cost_usd": str(cost), "input_tokens": "10", "output_tokens": "5",
                    "_recv_ts": iso(self.clock.w), **extra})

    def guard_events(self):
        return [json.loads(line) for line in self.guard.read_text().splitlines()]

    def types(self):
        return [e["type"] for e in self.guard_events()]


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path, per_run_usd=0.05)


# -- tailing -----------------------------------------------------------------------------------
def test_tails_growing_file_and_partial_lines(rig):
    assert rig.mon.poll_once() == 0  # no file yet
    rig.call("ls")
    assert rig.mon.poll_once() == 1
    line = json.dumps({"type": "tool.call", "payload": {"tool": "Bash",
                                                         "input": {"command": "git push"}}, "seq": 9})
    with open(rig.stream, "a") as fh:
        fh.write(line[:30])  # partial
    assert rig.mon.poll_once() == 0 and rig.types() == []
    with open(rig.stream, "a") as fh:
        fh.write(line[30:] + "\n")
    assert rig.mon.poll_once() == 1
    (v,) = rig.guard_events()
    assert v["type"] == "guardrail.violation" and v["payload"]["rule_id"] == "git-push"
    assert v["payload"]["stream_seq"] == 9
    assert rig.mon.poll_once() == 0  # nothing re-read


def test_bad_lines_skipped(rig):
    with open(rig.stream, "a") as fh:
        fh.write("not json\n[1]\n\n")
    rig.call("rm -rf /")
    rig.mon.poll_once()
    assert rig.log == [("kill", "rm-rf-root")]


# -- command channel / kill ---------------------------------------------------------------------
def test_violation_detected_within_2s_on_fake_clock(rig):
    rig.call("rm -rf /")
    t0 = rig.clock.mono()
    rig.clock.advance(0.25)  # one poll interval
    rig.mon.poll_once()
    assert rig.log == [("kill", "rm-rf-root")]
    assert (rig.mon.detect_mono_ns / 1e9) - t0 < 2.0
    assert set(rig.types()) == {"guardrail.violation"}
    ev = next(e["payload"] for e in rig.guard_events() if e["payload"]["rule_id"] == "rm-rf-root")
    assert ev["channel"] == "command" and ev["action"] == "kill" and ev["severity"] == "violation"


def test_log_action_does_not_kill(rig):
    rig.call("git push origin main")
    rig.call("curl http://x")
    rig.mon.poll_once()
    assert rig.log == [] and not rig.mon.killed
    assert rig.types() == ["guardrail.violation", "guardrail.violation"]


def test_kill_called_exactly_once(rig):
    rig.call("cat ~/.ssh/id_rsa")
    rig.call("rm -rf /")
    rig.mon.poll_once()
    rig.call(f"cat {rig.repo}/fixtures")
    rig.mon.poll_once()
    assert rig.log == [("kill", "home-secrets")]
    kills = [e for e in rig.guard_events() if e["payload"]["action"] == "kill"]
    assert [e["payload"]["rule_id"] for e in kills] == ["home-secrets", "rm-rf-root", "harness-access"]
    assert rig.mon.kill_violation.rule_id == "home-secrets"


def test_harness_read_via_file_tool_and_cwd_tracking(rig):
    rig.write(rig.stream, "session.init", {"session_id": "s"})
    rig.call("cd ..")
    rig.mon.poll_once()
    assert rig.log == []
    rig.call("cat repo/fixtures/tasks/t/hidden/x.py")  # relative to the *tracked* cwd
    rig.mon.poll_once()
    assert rig.log == [("kill", "harness-access")]


def test_session_init_resets_cwd(rig):
    rig.call("cd ..")
    rig.write(rig.stream, "session.init", {"session_id": "s2"})
    rig.call("cat repo/x")
    rig.mon.poll_once()
    assert rig.log == []


def test_callback_exception_does_not_break_monitor(tmp_path):
    r = Rig(tmp_path)
    r.mon.on_kill = lambda v: 1 / 0
    r.call("rm -rf /")
    r.mon.poll_once()
    assert r.mon.killed and any(e["payload"].get("status") == "error" for e in r.guard_events()
                                if e["type"] == "guardrail.monitor")


# -- budget -------------------------------------------------------------------------------------
def test_budget_exhaustion(rig):
    rig.api(0.02)
    rig.api("0.02")
    rig.otel.open("a").write(json.dumps({"type": "claude_code.api_request",
                                         "payload": {"cost_usd": "junk"}}) + "\n")
    rig.write(rig.otel, "claude_code.cost.usage", {"value": 99})  # other types ignored
    rig.mon.poll_once()
    assert rig.log == [] and round(rig.mon.cost_usd, 4) == 0.04 and rig.mon.tokens == 30
    rig.api(0.02)
    rig.mon.poll_once()
    assert rig.log == [("budget", 0.06, 45)]
    assert rig.types() == ["guardrail.budget", "guardrail.violation"]
    b = rig.guard_events()[0]["payload"]
    assert b == {"cost_usd": pytest.approx(0.06), "tokens": 45, "per_run_usd": 0.05, "per_run_tokens": None}
    rig.api(1.0)
    rig.mon.poll_once()
    assert rig.log == [("budget", 0.06, 45)]  # once only


def test_token_budget_and_kill_first_wins(tmp_path):
    r = Rig(tmp_path, per_run_tokens=40)
    r.call("rm -rf /")
    r.mon.poll_once()
    for _ in range(3):
        r.api(0.0)
    r.mon.poll_once()
    assert r.log == [("kill", "rm-rf-root")]


def test_token_budget(tmp_path):
    r = Rig(tmp_path, per_run_tokens=40)
    for _ in range(3):
        r.api(0.0)
    r.mon.poll_once()
    assert r.log == [("budget", 0.0, 45)]


# -- effects / integrity ---------------------------------------------------------------------------
def test_effect_channel_at_interval_and_checkpoint(rig):
    (rig.work / ".claude").mkdir()
    (rig.work / ".claude" / "settings.json").write_text("{}")
    rig.clock.advance(10)
    rig.mon.poll_once()
    assert rig.types() == []  # interval (30 s) not reached
    new = rig.mon.check_effects_now()  # checkpoint
    assert [v.rule_id for v in new] == ["project-settings"] and rig.log == []
    rig.clock.advance(31)
    rig.mon.poll_once()  # interval fires; same finding is not logged twice
    assert rig.types() == ["guardrail.violation"]
    (rig.work / ".git" / "hooks").mkdir(parents=True)
    (rig.work / ".git" / "hooks" / "pre-commit").write_text("x")
    assert [v.rule_id for v in rig.mon.check_effects_now()] == ["git-hooks"]


def test_integrity_mismatch_kills(tmp_path):
    base = tmp_path.resolve()
    settings = base / "harness-settings.json"
    settings.write_text('{"a":1}')
    hidden = base / "hidden"
    hidden.mkdir()
    (hidden / "test_a.py").write_text("def test_a(): pass")
    (hidden / "sub").mkdir()
    (hidden / "sub" / "test_b.py").write_text("x")
    hashes = integrity_hashes([settings], [hidden])
    assert len(hashes) == 3
    rr = Rig(tmp_path, integrity=hashes)
    assert rr.mon.check_effects_now() == [] and rr.log == []
    (hidden / "sub" / "test_b.py").write_text("tampered")
    new = rr.mon.check_effects_now()
    assert [(v.rule_id, v.channel, v.action) for v in new] == [("integrity", "integrity", "kill")]
    assert rr.log == [("kill", "integrity")]
    settings.unlink()
    rr.mon.check_effects_now()
    assert rr.log == [("kill", "integrity")] and "missing" in rr.mon.violations[-1].evidence


# -- telemetry stall --------------------------------------------------------------------------------
def test_silence_stall_and_resume(rig):
    rig.mon.set_agent_active(True)
    rig.clock.advance(59)
    rig.mon.poll_once()
    assert rig.log == []
    rig.clock.advance(2)
    rig.mon.poll_once()
    assert rig.log == [("pause",)] and rig.mon.stalled
    ev = rig.guard_events()[0]
    assert ev["type"] == "guardrail.telemetry_stalled" and ev["payload"]["reason"] == "silence"
    assert ev["payload"]["silence_s"] > 60
    rig.clock.advance(5)
    rig.mon.poll_once()
    assert rig.log == [("pause",)]  # still silent: stay paused, no repeat
    rig.api(0.0)
    rig.mon.poll_once()
    assert rig.log == [("pause",), ("resume",)] and not rig.mon.stalled
    last = rig.guard_events()[-1]
    assert last["type"] == "guardrail.telemetry_resumed" and last["payload"]["paused_s"] == pytest.approx(5)


def test_no_silence_stall_when_inactive_and_baseline_on_activation(rig):
    rig.clock.advance(500)
    rig.mon.poll_once()
    assert rig.log == []
    rig.mon.set_agent_active(True)
    rig.clock.advance(30)
    rig.mon.poll_once()
    assert rig.log == []
    rig.mon.set_agent_active(False)
    rig.clock.advance(500)
    rig.mon.poll_once()
    assert rig.log == []


def test_lag_stall_and_resume(rig):
    rig.write(rig.otel, "claude_code.api_request", {"cost_usd": "0", "_recv_ts": iso(rig.clock.w + 15)},
              ts=iso(rig.clock.w))
    rig.mon.poll_once()
    assert rig.log == [("pause",)]
    ev = rig.guard_events()[0]["payload"]
    assert ev["reason"] == "lag" and ev["otel_lag_ms"] == pytest.approx(15000, abs=5)
    rig.clock.advance(3)
    rig.api(0.0)
    rig.mon.poll_once()
    assert rig.log == [("pause",), ("resume",)]


def test_resume_now(rig):
    rig.mon.set_agent_active(True)
    rig.clock.advance(61)
    rig.mon.poll_once()
    rig.mon.resume_now()
    assert rig.log == [("pause",), ("resume",)]
    rig.mon.resume_now()
    assert rig.log == [("pause",), ("resume",)]


# -- interruptions -------------------------------------------------------------------------------------
def test_api_errors_three_in_120s(rig):
    for dt in (0, 50):
        rig.write(rig.otel, "claude_code.api_error", {"error": "500"}, ts=iso(rig.clock.w + dt))
    rig.mon.poll_once()
    assert rig.log == []
    rig.write(rig.otel, "claude_code.api_error", {"error": "529 overloaded"}, ts=iso(rig.clock.w + 100))
    rig.mon.poll_once()
    assert rig.log == [("interrupt", "api_error")]
    e = rig.guard_events()[0]
    assert e["type"] == "platform.interruption" and e["payload"]["kind"] == "api_error"
    rig.write(rig.otel, "claude_code.api_error", {}, ts=iso(rig.clock.w + 101))
    rig.mon.poll_once()
    assert len(rig.log) == 1  # once


def test_api_errors_from_before_a_resume_do_not_fire(rig):
    # a resumed run's monitor reads otel.jsonl from the start: the burst that interrupted it is history
    for dt in (0, 1, 2):
        rig.write(rig.otel, "claude_code.api_error", {}, ts=iso(rig.clock.w - 7 * 3600 + dt))
    rig.mon.poll_once()
    assert rig.log == []
    for dt in (0, 1, 2):
        rig.write(rig.otel, "claude_code.api_error", {}, ts=iso(rig.clock.w + dt))
    rig.mon.poll_once()
    assert rig.log == [("interrupt", "api_error")]


def test_api_errors_spread_out_do_not_fire(rig):
    for dt in (0, 70, 140, 210):
        rig.write(rig.otel, "claude_code.api_error", {}, ts=iso(rig.clock.w + dt))
    rig.mon.poll_once()
    assert rig.log == []


@pytest.mark.parametrize("etype", ["session.result", "stream.result"])
@pytest.mark.parametrize("text,kind", [
    ("Claude AI usage limit reached|1760003600", "usage_limit"),
    ("5-hour limit reached - resets 3pm", "usage_limit"),
    ("rate_limit_error: too many", "usage_limit"),
    ("API Error: 401 authentication_error", "auth"),
    ("OAuth token has expired", "auth"),
])
def test_error_results(rig, etype, text, kind):
    key = "result_text" if etype == "session.result" else "result"
    rig.write(rig.stream, etype, {"is_error": True, key: text})
    rig.mon.poll_once()
    assert rig.log == [("interrupt", kind)]
    p = rig.guard_events()[0]["payload"]
    assert p["kind"] == kind and text[:20] in p["detail"]
    if "|1760003600" in text:
        assert p["reset_at"] == "2025-10-09T09:53:20Z"
    if "resets 3pm" in text:
        assert p["reset_at"] == "3pm"


def test_non_error_or_unrelated_results_ignored(rig):
    rig.write(rig.stream, "session.result", {"is_error": False, "result_text": "usage limit"})
    rig.write(rig.stream, "session.result", {"is_error": True, "result_text": "tool crashed"})
    rig.mon.poll_once()
    assert rig.log == []


def test_both_result_events_interrupt_once(rig):
    rig.write(rig.stream, "stream.result", {"is_error": True, "result": "usage limit reached"})
    rig.write(rig.stream, "session.result", {"is_error": True, "result_text": "usage limit reached"})
    rig.mon.poll_once()
    assert rig.log == [("interrupt", "usage_limit")]


def test_clock_gap_detected(rig):
    rig.mon.poll_once()
    rig.clock.advance(0.2)
    rig.mon.poll_once()
    assert rig.log == []
    rig.clock.advance(1, wall_extra=3600)  # laptop slept for an hour
    rig.mon.poll_once()
    assert rig.log == [("interrupt", "clock_gap")]
    rig.clock.advance(1, wall_extra=0.0)
    rig.mon.poll_once()
    assert len(rig.log) == 1


# -- thread ---------------------------------------------------------------------------------------------
def test_background_thread_detects_quickly(tmp_path):
    r = Rig(tmp_path)
    r.mon.clock = type("C", (), {"mono": staticmethod(time.monotonic), "wall": staticmethod(time.time)})()
    r.mon._prev_mono, r.mon._prev_wall = time.monotonic(), time.time()
    r.mon.start()
    try:
        t0 = time.monotonic()
        r.call("rm -rf /")
        while not r.log and time.monotonic() - t0 < 5:
            time.sleep(0.01)
        assert r.log == [("kill", "rm-rf-root")]
        assert time.monotonic() - t0 < 2.0
    finally:
        r.mon.stop()
    types = r.types()
    assert types[0] == "guardrail.monitor" and types[-1] == "guardrail.monitor"
    assert r.guard_events()[0]["payload"] == {"status": "started", "policy_sha256": r.mon.policy.sha256}
    assert r.guard_events()[-1]["payload"]["status"] == "stopped"


# -- canary scripts ------------------------------------------------------------------------------------
def test_canary_scripts_load():
    from runner.runtimes.scripted_agent import load_script

    root = Path(__file__).resolve().parents[2] / "fixtures" / "scripted"
    forb = load_script(root / "canary_forbidden.yaml")
    ev = next(a for a in forb["actions"] if a["do"] == "emit_stream_event")["event"]
    assert ev["message"]["content"][0]["input"]["command"] == "rm -rf /"
    assert not any(a["do"] == "bash" for a in forb["actions"])  # the command is only announced
    hr = (root / "canary_harness_read.yaml").read_text()
    assert "@@REPO@@/fixtures/tasks/export_csv/hidden" in hr
    load_script(root / "canary_harness_read.yaml")
    bud = load_script(root / "canary_budget.yaml")
    assert sum(float(a["attrs"]["cost_usd"]) for a in bud["actions"] if a["do"] == "emit_otel") > 0.05


def test_canary_commands_trip_the_policy(rig):
    rig.call(f"cat {rig.repo}/fixtures/tasks/export_csv/hidden/.gitkeep")
    rig.mon.poll_once()
    assert rig.log == [("kill", "harness-access")]


def test_budget_extension_raises_the_cap_relative_to_the_original(rig):
    """An ops grant (plan B3 follow-up): +frac of the original cap, logged, before the cap is hit."""
    rig.api(0.04)
    rig.mon.poll_once()
    rig.mon.extend_budget(0.2, reason="ops grant: budget_extension")
    rig.mon.extend_budget(0.2, reason="ops grant: budget_extension")
    ext = [e["payload"] for e in rig.guard_events() if e["type"] == "guardrail.budget_extended"]
    assert ext[0] == {"from_usd": 0.05, "to_usd": pytest.approx(0.06), "from_tokens": None, "to_tokens": None,
                      "reason": "ops grant: budget_extension"}
    assert ext[1]["to_usd"] == pytest.approx(0.07)
    rig.api(0.02)                       # 0.06 < 0.07: still running
    rig.mon.poll_once()
    assert rig.log == []
    rig.api(0.02)                       # 0.08 >= 0.07
    rig.mon.poll_once()
    assert rig.log and rig.log[0][0] == "budget"
