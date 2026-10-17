import json

import pytest

from telemetry.counters import cumulative_cost


def write(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def api(cost):
    return {"type": "claude_code.api_request", "payload": {"cost_usd": cost}}


def test_sums_string_and_numeric_costs(tmp_path):
    # the live CLI exports cost_usd as a *string* attribute
    p = tmp_path / "otel.jsonl"
    write(p, [api("0.0063735"), api(0.01), api("0.02")])
    assert cumulative_cost(p) == pytest.approx(0.0363735)


def test_ignores_other_events_and_bad_values(tmp_path):
    p = tmp_path / "otel.jsonl"
    write(p, [{"type": "claude_code.user_prompt", "payload": {"cost_usd": "9"}}, api("n/a"), api(None), api("0.5")])
    p.write_text(p.read_text() + "not json\n")
    assert cumulative_cost(p) == pytest.approx(0.5)


def test_missing_file_is_zero(tmp_path):
    assert cumulative_cost(tmp_path / "nope.jsonl") == 0.0


# --- cumulative_tokens and interval_counters (Phase 2) ------------------------------------------

from telemetry.counters import (  # noqa: E402
    context_window,
    cumulative_tokens,
    interval_boundaries,
    interval_counters,
)


def req(sid, inp, out=10, cr=0, cc=0, cost="0.1", model="claude-opus-5-5", lag=None, mono=0):
    p = {"session.id": sid, "model": model, "input_tokens": str(inp), "output_tokens": str(out),
         "cache_read_tokens": str(cr), "cache_creation_tokens": str(cc), "cost_usd": cost}
    if lag is not None:
        p["_otel_lag_ms"] = lag
    return {"type": "claude_code.api_request", "mono_ns": mono, "payload": p}


def ev(t, mono, **payload):
    return {"type": t, "mono_ns": mono, "payload": payload}


def build(tmp_path, orch, otel=(), stream=()):
    d = tmp_path / "events"
    d.mkdir()
    write(d / "orchestrator.jsonl", orch)
    write(d / "otel.jsonl", list(otel))
    write(d / "agent_stream.jsonl", list(stream))
    return d


def orch_two(start=1000, c1=2000, c2=3000):
    return [ev("state", 10, to="PREPARING"), ev("run.clock", start - 5, start_epoch=0, offset_s=0),
            ev("state", start, to="RUNNING"), ev("turn.start", start + 1, turn=1),
            ev("checkpoint", c1, k=1), ev("state", c1 + 1, to="RUNNING"), ev("turn.start", c1 + 2, turn=2),
            ev("turn.start", c1 + 3, turn=3), ev("checkpoint", c2, k=2, final="budget")]


def test_cumulative_tokens_sums_four_fields_and_skips_garbage(tmp_path):
    p = tmp_path / "o.jsonl"
    write(p, [req("s", 4, 4, 21005), req("s", "x", None, "7", 1), ev("claude_code.user_prompt", 0, input_tokens="99")])
    assert cumulative_tokens(p) == 4 + 4 + 21005 + 7 + 1
    assert cumulative_tokens(tmp_path / "none") == 0


def test_boundaries_use_running_after_clock_and_checkpoints():
    assert interval_boundaries(orch_two()) == [1000, 2000, 3000]
    assert interval_boundaries([]) == []
    assert interval_boundaries([ev("run.clock", 7)]) == [7]  # no RUNNING event: falls back to the clock


def test_interval_sums_and_cumulative(tmp_path):
    d = build(tmp_path, orch_two(), otel=[
        req("s1", 100, 5, 900, 0, "0.25", mono=1500), req("s1", 200, 6, 1800, 50, "0.5", mono=1600),
        req("s1", 10, 1, 3000, 0, "1.0", mono=2500), req("s1", 1, 1, 3000, mono=500),   # before start: ignored
        req("s1", 1, 1, 3000, mono=3500),                                              # after last checkpoint
        ev("claude_code.api_error", 1700), ev("claude_code.api_error", 2600)],
        stream=[ev("tool.call", 1550, tool="Bash"), ev("tool.call", 1560, tool="Read"),
                ev("tool.call", 2700, tool="Bash"), ev("session.init", 1001, session_id="s1")])
    a, b = interval_counters(d)
    assert (a["k"], b["k"]) == (1, 2)
    assert a["tokens_in"] == 300 and a["tokens_out"] == 11 and a["tokens_cache_read"] == 2700
    assert a["tokens_cache_creation"] == 50 and a["cost_usd"] == pytest.approx(0.75)
    assert a["tool_calls"] == 2 and b["tool_calls"] == 1
    assert a["turns"] == 1 and b["turns"] == 2
    assert a["api_errors"] == 1 and b["api_errors"] == 1
    assert a["sessions"] == 1 and b["sessions"] == 1
    assert b["tokens_in"] == 10 and b["cost_usd"] == pytest.approx(1.0)
    assert b["cum_cost_usd"] == pytest.approx(1.75) and b["cum_tokens_in"] == 310
    assert b["cum_tool_calls"] == 3 and b["cum_turns"] == 3 and b["cum_compactions"] == 0


def test_context_fill_max_and_last_with_models_yaml(tmp_path):
    y = tmp_path / "m.yaml"
    y.write_text("default_context_window: 1000\nmodels:\n  big: 10000\n")
    d = build(tmp_path, orch_two(), otel=[
        req("s", 100, cr=400, model="big", mono=1100),    # 500/10000
        req("s", 600, cr=300, cc=100, model="other", mono=1200),   # 1000/1000 (default)
        req("s", 250, model="big-2026", mono=1300)])       # prefix match: 250/10000
    a, b = interval_counters(d, models_yaml=y)
    assert a["context_fill_max"] == pytest.approx(1.0) and a["context_fill_last"] == pytest.approx(0.025)
    assert b["context_fill_max"] is None and b["context_fill_last"] is None


def test_context_window_resolution_order():
    table = {"claude-opus-5-5": 200000, "claude-haiku": 1}
    assert context_window("claude-opus-5-5", table, {}, 7) == 200000
    assert context_window("claude-haiku-5-5", table, {"claude-haiku-5-5": 9}, 7) == 9   # the CLI's report wins
    assert context_window("claude-haiku-5-5", table, {}, 7) == 1                         # then table prefix
    assert context_window("mystery", table, {"mystery": 123}, 7) == 123                  # stream fallback
    assert context_window("mystery", table, {}, 200000) == 200000
    assert context_window("zzz[1m]", table, {}, 7) == 1_000_000


def test_real_models_yaml_default_and_stream_window(tmp_path):
    d = build(tmp_path, orch_two(), otel=[req("s", 1000, model="claude-opus-5-5", mono=1100),
                                          req("s", 1000, model="brand-new", mono=1200)],
              stream=[{"type": "session.result", "mono_ns": 1900,
                       "payload": {"modelUsage": {"brand-new": {"contextWindow": 500000}}}}])
    a, _ = interval_counters(d)
    assert a["context_fill_max"] == pytest.approx(1000 / 500000)    # brand-new: the CLI's own 500k
    assert a["context_fill_last"] == pytest.approx(1000 / 500000)
    # claude-opus-5-5 from the real models.yaml (1M, as CLI 2.1.301 reports) gives 1000/1e6


def test_compactions_from_stream_events(tmp_path):
    d = build(tmp_path, orch_two(), otel=[req("s", 10, cr=100000, mono=1100), req("s", 10, cr=100, mono=1200)],
              stream=[ev("context.compaction", 1250, session_id="s", trigger="auto", pre_tokens=1),
                      ev("context.compaction", 2250, session_id="s", trigger="manual", pre_tokens=1)])
    a, b = interval_counters(d)
    assert a["compactions"] == 1 and b["compactions"] == 1  # heuristic suppressed for session s
    assert b["cum_compactions"] == 2


def test_compactions_heuristic_when_no_events(tmp_path):
    d = build(tmp_path, orch_two(), otel=[
        req("s", 10, cr=100000, mono=1100), req("s", 10, cr=120000, mono=1200),
        req("s", 10, cr=40000, mono=1300),            # drop >50% -> compaction
        req("s", 10, cr=60000, mono=2100),             # growth
        req("s", 10, cr=10000, mono=2200),             # drop >50% again, next interval
        req("t", 10, cr=50000, mono=2300),             # other session: no previous request
        req("t", 10, cr=26000, mono=2400)])            # exactly 48% drop: not > 50%
    a, b = interval_counters(d)
    assert a["compactions"] == 1 and b["compactions"] == 1


def test_heuristic_only_for_sessions_without_events(tmp_path):
    d = build(tmp_path, orch_two(), otel=[
        req("a", 10, cr=100000, mono=1100), req("a", 10, cr=1000, mono=1200),
        req("b", 10, cr=100000, mono=1300), req("b", 10, cr=1000, mono=1400)],
        stream=[ev("context.compaction", 1250, session_id="a")])
    a, _ = interval_counters(d)
    assert a["compactions"] == 2  # a: 1 event (heuristic off); b: heuristic 1


def test_lag_p95_and_garbage_values(tmp_path):
    reqs = [req("s", 1, lag=i, mono=1100 + i) for i in range(1, 21)]   # 1..20 -> p95 = 19
    reqs.append(req("s", 1, lag="bad", mono=1500))
    d = build(tmp_path, orch_two(), otel=reqs + [ev("claude_code.cost.usage", 1600, _otel_lag_ms=None)])
    a, b = interval_counters(d)
    assert a["otel_lag_ms_p95"] == 19 and b["otel_lag_ms_p95"] is None


def test_string_and_nonnumeric_attributes_do_not_crash(tmp_path):
    d = build(tmp_path, orch_two(), otel=[
        req("s", "n/a", "nan", "inf", None, "free", mono=1100), req("s", "5", "6", "7", "8", "0.5", mono=1200)])
    a, _ = interval_counters(d)
    assert (a["tokens_in"], a["tokens_out"], a["tokens_cache_read"], a["tokens_cache_creation"]) == (5, 6, 7, 8)
    assert a["cost_usd"] == pytest.approx(0.5)


def test_no_checkpoints_or_no_files(tmp_path):
    d = build(tmp_path, [ev("run.clock", 5), ev("state", 6, to="RUNNING")])
    assert interval_counters(d) == []
    assert interval_counters(tmp_path / "missing") == []


def test_real_fixture_session_counted(tmp_path):
    import json as _json
    from pathlib import Path
    fx = Path(__file__).resolve().parents[2] / "fixtures"
    attrs = None
    for line in (fx / "otel" / "cli-1.0.126-haiku-ok.raw.jsonl").read_text().splitlines():
        for rl in _json.loads(line)["body"].get("resourceLogs", []):
            for rec in rl["scopeLogs"][0]["logRecords"]:
                if rec["body"]["stringValue"] == "claude_code.api_request":
                    attrs = {x["key"]: x["value"]["stringValue"] for x in rec["attributes"]}
    d = build(tmp_path, orch_two(), otel=[{"type": "claude_code.api_request", "mono_ns": 1500, "payload": attrs}])
    a, _ = interval_counters(d)
    assert a["sessions"] == 1 and a["context_fill_last"] == pytest.approx(21009 / 200000)
    assert a["cost_usd"] == pytest.approx(0.0063735)
