import json
import threading

from guardrails.killswitch import KillSwitch
from telemetry.events import EventWriter


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def make(tmp_path, **cbs):
    calls = []
    t = iter(range(1_000_000_000, 10**12, 250_000_000))  # each mono() call advances 250 ms
    w = EventWriter(tmp_path / "guardrail.jsonl", "r", "guardrail")
    ks = KillSwitch(cbs.get("freeze", lambda: calls.append("freeze")),
                    cbs.get("snapshot", lambda: calls.append("snapshot")),
                    cbs.get("kill", lambda: calls.append("kill")), w, mono=lambda: next(t))
    return ks, calls, tmp_path / "guardrail.jsonl"


def test_sequence_and_event(tmp_path):
    ks, calls, path = make(tmp_path)
    assert ks.trigger("rm-rf-root", "policy", 1_000_000_000 - 500_000_000) is True
    assert calls == ["freeze", "snapshot", "kill"]
    (ev,) = events(path)
    assert ev["type"] == "guardrail.kill" and ev["source"] == "guardrail"
    p = ev["payload"]
    assert p["rule_id"] == "rm-rf-root" and p["reason"] == "policy"
    assert p["frozen_mono_ns"] == 1_000_000_000 and p["detect_mono_ns"] == 500_000_000
    assert p["freeze_latency_ms"] == 500.0


def test_kill_event_is_logged_before_snapshot(tmp_path):
    seen = []
    ks, _, path = make(tmp_path, snapshot=lambda: seen.append([e["type"] for e in events(path)]))
    ks.trigger("x", "budget", 0)
    assert seen == [["guardrail.kill"]]


def test_idempotent(tmp_path):
    ks, calls, path = make(tmp_path)
    assert ks.trigger("a", "policy", 0) is True
    assert ks.trigger("b", "budget", 0) is False
    assert calls == ["freeze", "snapshot", "kill"]
    assert len(events(path)) == 1 and ks.rule_id == "a"


def test_thread_safe(tmp_path):
    ks, calls, path = make(tmp_path)
    results = []
    ts = [threading.Thread(target=lambda: results.append(ks.trigger("a", "policy", 0))) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results.count(True) == 1 and calls.count("freeze") == 1


def test_failing_step_does_not_stop_kill(tmp_path):
    def boom():
        raise RuntimeError("snap failed")

    ks, calls, path = make(tmp_path, snapshot=boom)
    assert ks.trigger("a", "policy", 0) is True
    assert calls == ["freeze", "kill"]
    types = [e["type"] for e in events(path)]
    assert types == ["guardrail.kill", "guardrail.kill_error"]
    assert ks.errors[0][0] == "snapshot"


def test_failing_freeze_still_kills(tmp_path):
    def boom():
        raise RuntimeError("no such process")

    ks, calls, path = make(tmp_path, freeze=boom)
    assert ks.trigger("a", "policy", 0)
    assert calls == ["snapshot", "kill"]
    assert events(path)[0]["type"] == "guardrail.kill_error"
