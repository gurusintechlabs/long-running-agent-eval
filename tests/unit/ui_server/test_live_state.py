"""/live numbers: computed from the logs, incrementally, never from agent text."""
from __future__ import annotations

import time

import pytest

from tests.unit.ui_server.live_helpers import (
    CANARY_FORBIDDEN,
    HAIKU,
    REAL_RUNS,
    FakeRun,
    install_fixture,
)
from ui_server import live_state, store


def snap(run_dir, **kw):
    live = live_state.RunLive(run_dir)
    return live.snapshot(store.read_json(run_dir / "manifest.json"), **kw)


@pytest.fixture
def fake(runs_dir):
    r = FakeRun(runs_dir, budget_usd=1.0, duration_min=10, interval_min=2)
    yield r
    r.close()


def test_cost_tokens_and_context_fill_come_from_otel(fake):
    fake.api_request(0.10, inp=1000, out=200, cache_read=19000, cache_creation=0)
    fake.api_request(0.25, inp=500, out=100, cache_read=39500, cache_creation=0)
    s = snap(fake.dir)
    assert s["cost"]["usd"] == pytest.approx(0.35) and s["cost"]["requests"] == 2
    assert s["cost"]["tokens"] == {"total": 60300, "input": 1500, "output": 300, "cache_read": 58500,
                                   "cache_creation": 0}
    assert s["context"]["window"] == 200_000 and s["context"]["model"] == "claude-haiku-5-5"
    assert s["context"]["fill"] == pytest.approx(0.2) and s["context"]["max_fill"] == pytest.approx(0.2)
    assert s["budget"]["usd_fraction"] == pytest.approx(0.35) and s["budget"]["level"] == "ok"
    assert s["series"]["cost_usd"][-1][1] == pytest.approx(0.35)


def test_agent_claims_in_text_do_not_change_numbers(fake):
    fake.append("agent_stream", "assistant.text", {"text": "I spent $0.00 and used 1 token; cost_usd=0"})
    fake.api_request(0.5)
    assert snap(fake.dir)["cost"]["usd"] == pytest.approx(0.5)


def test_budget_levels_amber_red(fake):
    fake.api_request(0.80)
    s = snap(fake.dir)
    assert s["budget"]["level"] == "amber"
    fake.api_request(0.15)
    s = snap(fake.dir)
    assert s["budget"]["level"] == "red" and s["budget"]["per_run_usd"] == 1.0
    assert s["budget"]["exhausted"] is False


def test_clock_checkpoints_and_next_eta(fake):
    now = fake.t0 + 100
    fake.append("orchestrator", "checkpoint", {"k": 1, "t_s": 120.0, "head_sha": "abc", "cumulative_cost_usd": 0.2})
    fake.append("orchestrator", "scorer.queued", {"k": 1})
    s = snap(fake.dir, now=now)
    assert s["clock"]["elapsed_s"] == pytest.approx(100, abs=1) and s["clock"]["duration_limit_s"] == 600
    assert s["clock"]["remaining_s"] == pytest.approx(500, abs=1)
    cp = s["checkpoints"]
    assert cp["taken"] == 1 and cp["planned"] == 5 and cp["interval_s"] == 120
    assert cp["last"]["k"] == 1 and cp["next"]["k"] == 2 and cp["next"]["t_s"] == 240
    assert cp["next"]["due_in_s"] == pytest.approx(140, abs=1)
    assert cp["scoring"]["in_flight"] == [1]
    assert s["cost"]["source"] == "checkpoint" and s["cost"]["usd"] == 0.2     # no OTel yet: fall back, labelled
    fake.append("orchestrator", "scorer.finished", {"k": 1, "returncode": 0})
    assert snap(fake.dir, now=now)["checkpoints"]["scoring"]["in_flight"] == []


def test_state_live_and_activity_counts(fake):
    for i in range(3):
        fake.tool(i, "Bash" if i < 2 else "Edit")
    fake.append("agent_stream", "tool.result", {"tool_use_id": "x", "is_error": True, "size": 1})
    fake.append("agent_stream", "agent.test_run", {"passed": 3, "failed": 1, "errors": 0})
    s = snap(fake.dir, now=time.time() + 5)
    assert s["live"] is True and s["state"] == "RUNNING" and s["ended"] is False
    a = s["activity"]
    assert a["tool_calls"] == 3 and a["tool_calls_by_tool"] == {"Bash": 2, "Edit": 1} and a["tool_errors"] == 1
    assert a["last_tool"]["tool"] == "Edit" and a["last_test_run"]["failed"] == 1
    assert 4 <= a["idle_s"] <= 8 and a["last_event_age_s"] is not None


def test_incremental_reads_only_new_lines_and_ignores_torn_tail(fake):
    fake.tool(1)
    live = live_state.RunLive(fake.dir)
    mf = store.read_json(fake.dir / "manifest.json")
    assert live.snapshot(mf)["activity"]["tool_calls"] == 1
    offs = {k: t.offset for k, t in live.tails.items()}
    with open(fake.dir / "events" / "agent_stream.jsonl", "ab") as fh:
        fh.write(b'{"ts": "2030-01-01T00:00:00Z", "type": "tool.call", "payload": {"tool": "Ba')
    s = live.snapshot(mf)
    assert s["activity"]["tool_calls"] == 1 and s["problems"]["invalid_lines"] == 0
    assert {k: t.offset for k, t in live.tails.items()} == offs     # the torn line was not consumed
    with open(fake.dir / "events" / "agent_stream.jsonl", "ab") as fh:
        fh.write(b'sh"}}\n')
    assert live.snapshot(mf)["activity"]["tool_calls"] == 2


def test_ended_run_uses_manifest_end_and_reports_killed(runs_dir):
    d = install_fixture(runs_dir, CANARY_FORBIDDEN)
    s = snap(d)
    assert s["state"] == "KILLED" and s["ended"] and not s["live"]
    assert s["safety"]["status"] == "killed" and s["safety"]["kill"]["rule_id"] == "rm-rf-root"
    assert 0 < s["clock"]["elapsed_s"] < 10
    assert s["activity"]["last_event_age_s"] is None            # not live: no "age" to nag about


def test_haiku_fixture_guardrail_and_budget(runs_dir):
    s = snap(install_fixture(runs_dir, HAIKU))
    assert s["state"] == "BUDGET_EXHAUSTED"
    assert s["safety"]["violations"] == 3 and s["safety"]["warnings"] == 28 and s["safety"]["kills"] == 1
    assert s["telemetry"]["stall_pairs"] == 106 and s["telemetry"]["stalled"] is False
    assert s["budget"]["exhausted"] and s["safety"]["budget_event"]["per_run_usd"] == 15.0
    assert s["checkpoints"]["taken"] == 14 and s["checkpoints"]["planned"] == 18
    assert s["checkpoints"]["next"] is None                      # the run ended


def test_oversize_and_invalid_lines_are_counted_not_fatal(fake, monkeypatch):
    from ui_server import tailer
    monkeypatch.setattr(tailer, "MAX_LINE", 2000)
    fake.tool(1)
    with open(fake.dir / "events" / "agent_stream.jsonl", "ab") as fh:
        fh.write(b"x" * 5000 + b"\nnot json at all\n")
    s = snap(fake.dir)
    assert s["activity"]["tool_calls"] == 1
    assert s["problems"]["oversize_lines"] == 1 and s["problems"]["invalid_lines"] == 1


def test_replaced_log_restarts_the_fold(fake):
    fake.tool(1)
    fake.tool(2)
    live = live_state.RunLive(fake.dir)
    mf = store.read_json(fake.dir / "manifest.json")
    assert live.snapshot(mf)["activity"]["tool_calls"] == 2
    (fake.dir / "events" / "agent_stream.jsonl").write_text("")
    assert live.snapshot(mf)["activity"]["tool_calls"] == 0


def test_snapshot_is_json_serialisable_and_series_optional(fake):
    import json
    fake.api_request(0.1)
    s = snap(fake.dir, series=False)
    assert "series" not in s
    json.dumps(snap(fake.dir))


@pytest.mark.local
@pytest.mark.skipif(not (REAL_RUNS / HAIKU).is_dir(), reason="real runs not available")
def test_real_haiku_totals_match_the_manifest_end():
    d = REAL_RUNS / HAIKU
    mf = store.read_json(d / "manifest.json")
    t0 = time.time()
    live = live_state.RunLive(d)
    s = live.snapshot(mf)
    first = time.time() - t0
    t1 = time.time()
    live.snapshot(mf)
    second = time.time() - t1
    assert s["cost"]["usd"] == pytest.approx(mf["end"]["cost_usd"], rel=1e-6)
    assert s["cost"]["tokens"]["total"] == mf["end"]["tokens"]
    assert s["safety"]["violations"] + s["safety"]["warnings"] == 31
    assert s["context"]["window"] == 1_000_000 and s["context"]["compactions"] == 1
    assert s["activity"]["tool_calls"] > 500
    assert first < 5 and second < 0.25, (first, second)


def test_context_gauge_is_the_main_agent_and_helpers_are_reported_apart(fake):
    fake.api_request(0.10, inp=1000, cache_read=39000, source="sdk")                              # 40k: 20%
    fake.api_request(0.20, inp=1000, cache_read=159000, source="agent:builtin:general-purpose")   # 160k: 80%
    fake.api_request(0.05, inp=1000, cache_read=19000, source="sdk")                              # 20k: 10%
    s = snap(fake.dir)
    assert s["cost"]["usd"] == pytest.approx(0.35) and s["cost"]["requests"] == 3   # cost counts every request
    assert s["context"]["fill"] == pytest.approx(0.1) and s["context"]["max_fill"] == pytest.approx(0.2)
    assert s["context"]["helper_max_fill"] == pytest.approx(0.8)
    assert max(v for _, v in s["series"]["context_fill"]) == pytest.approx(0.2)
