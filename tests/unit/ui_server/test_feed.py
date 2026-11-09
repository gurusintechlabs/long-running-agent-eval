"""Display-event normalisation: per-type summarizers on real log samples, folding, caps, hostile strings."""
from __future__ import annotations

import json

import pytest

from tests.unit.ui_server.live_helpers import (
    CANARY_FORBIDDEN,
    FIXTURES,
    HAIKU,
    read_events,
)
from ui_server import feed
from ui_server.tailer import Merger

REQUIRED = {"id", "cursor", "ts", "t_s", "seq", "source", "type", "kind", "title", "summary", "severity", "level",
            "pair", "payload_preview", "truncated", "fold"}


def display_all(rid: str, *, fold: bool = True) -> list[dict]:
    d = FIXTURES / rid
    clock = feed.RunClock.from_events(read_events(d / "events" / "orchestrator.jsonl"))
    ctx = feed.FeedContext(clock)
    out = []
    m = Merger(d / "events")
    while True:
        batch = m.poll()
        if not batch:
            break
        for it in batch:
            ev = json.loads(it.data)
            out.append(feed.display_event(it.source, it.start, ev, ctx))
    return feed.fold_all(out) if fold else out


@pytest.mark.parametrize("rid", [HAIKU, CANARY_FORBIDDEN])
def test_every_real_event_renders_with_the_stable_shape(rid):
    evs = display_all(rid)
    assert evs
    for d in evs:
        assert set(d) == REQUIRED, d["type"]
        assert d["kind"] in feed.KINDS and d["severity"] in feed.SEVERITIES and d["level"] in feed.LEVELS
        assert "\n" not in d["title"] and "\n" not in d["summary"]
        assert len(d["summary"]) <= feed.SUMMARY_CAP
        json.dumps(d)


def by_type(evs, typ):
    return [d for d in evs if d["type"] == typ]


def test_kinds_for_the_main_event_types():
    evs = display_all(HAIKU)
    kinds = {}
    for d in evs:
        kinds.setdefault(d["type"], d["kind"])
    want = {"tool.call": "tool_call", "tool.result": "tool_result", "assistant.text": "assistant_text",
            "checkpoint": "checkpoint", "stage.delivered": "stage", "turn.start": "turn", "turn.end": "turn",
            "state": "state", "ops.message": "counterpart", "ops.request": "counterpart",
            "guardrail.budget": "budget", "guardrail.violation": "guardrail", "guardrail.kill": "kill",
            "env.mutated": "env", "context.compaction": "session", "scorer.done": "scorer", "scorer.hazard": "scorer",
            "scorer.behavior": "scorer", "claude_code.api_request": "usage", "stream.system": "raw",
            "run.clock": "run", "telemetry_silent": "folded"}
    for t, k in want.items():
        assert kinds.get(t) == k, (t, kinds.get(t))


def test_synthetic_types_missing_from_the_excerpts():
    ctx = feed.FeedContext()
    for typ, p, kind, sev in [
            ("agent.test_run", {"passed": 70, "failed": 0, "errors": 0, "raw_summary": "70 passed in 0.66s"}, "test_run", "info"),
            ("agent.test_run", {"passed": 7, "failed": 2, "errors": 0}, "test_run", "warning"),
            ("session.init", {"model": "m", "tools": ["Bash"]}, "session", "info"),
            ("session.result", {"subtype": "success", "num_turns": 3, "total_cost_usd": 0.5}, "session", "info"),
            ("turn.end", {"turn": 2, "returncode": 1}, "turn", "warning"),
            ("run.error", {"error": "boom"}, "run", "violation"),
            ("platform.interruption", {"kind": "usage_limit", "detail": "limit"}, "run", "warning"),
            ("guardrail.budget_extended", {"from_usd": 1, "to_usd": 2, "reason": "grant"}, "budget", "warning"),
            ("procmon.connection", {"name": "curl", "remote": "1.2.3.4:80"}, "guardrail", "warning"),
            ("stream.invalid", {"raw": "x"}, "raw", "warning")]:
        d = feed.display_event("agent_stream", 0, {"ts": "x", "type": typ, "payload": p}, ctx)
        assert (d["kind"], d["severity"]) == (kind, sev), typ


def test_tool_call_summary_and_result_duration_pairing():
    evs = display_all(HAIKU)
    calls = by_type(evs, "tool.call")
    assert calls
    results = {d["pair"]: d for d in by_type(evs, "tool.result")}
    call = next(d for d in calls if d["pair"] in results)
    assert call["summary"] and call["pair"].startswith("toolu_")
    res = results[call["pair"]]
    assert res["title"].startswith(call["title"] + " ") and " s" in res["summary"]   # duration known from the call


def test_run_offsets_use_the_run_clock():
    evs = display_all(HAIKU)
    cp = by_type(evs, "checkpoint")[0]
    assert cp["t_s"] == pytest.approx(1200.5, abs=2)
    assert next(d for d in evs if d["type"] == "run.clock")["t_s"] == pytest.approx(0, abs=1)
    assert by_type(evs, "preflight")[0]["t_s"] is None      # before the clock started


def test_severities_follow_the_event():
    evs = display_all(HAIKU)
    viol = by_type(evs, "guardrail.violation")
    assert {d["severity"] for d in viol} == {"warning", "violation", "kill"}
    assert by_type(evs, "guardrail.kill")[0]["severity"] == "kill"
    assert by_type(evs, "guardrail.budget")[0]["severity"] == "violation"
    st = [d for d in by_type(evs, "state") if "BUDGET_EXHAUSTED" in d["title"]]
    assert st and st[0]["severity"] == "warning"


def test_raw_stream_and_otel_are_debug_and_levels_match_prefilter():
    evs = display_all(HAIKU)
    for d in evs:
        pre = feed.level_of(d["source"], d["type"])
        if pre == "debug":
            assert d["level"] == "debug", d["type"]       # the cheap pre-parse filter never hides a visible row
    assert all(d["level"] == "debug" for d in evs if d["type"].startswith("stream."))
    assert all(d["level"] == "debug" for d in evs if d["source"] == "otel")


def test_telemetry_stalls_fold_into_one_row():
    raw = display_all(HAIKU, fold=False)
    assert len(by_type(raw, "guardrail.telemetry_stalled")) == 106
    folded = display_all(HAIKU)
    rows = [d for d in folded if d["id"] == feed.Folder.ID]
    assert len(rows) == 1 and not by_type(folded, "guardrail.telemetry_stalled")
    f = rows[0]["fold"]
    assert f["pairs"] == 106 and f["open"] is False and f["reasons"] == {"silence": 106}
    assert f["typical_silence_s"] == 60 and "x 106" in rows[0]["title"]
    assert f["first_cursor"].startswith("guardrail:") and f["last_cursor"] == rows[0]["cursor"]


def test_folder_streaming_updates_same_id_and_tracks_open_stall():
    f = feed.Folder()
    ctx = feed.FeedContext()

    def ev(typ, **p):
        return feed.display_event("guardrail", 10, {"ts": "x", "type": typ, "payload": p}, ctx)
    a = f.apply(ev("guardrail.telemetry_stalled", reason="silence", silence_s=60.1))
    assert a["id"] == feed.Folder.ID and a["fold"]["open"] is True and a["fold"]["pairs"] == 0
    b = f.apply(ev("guardrail.telemetry_resumed", paused_s=0.002))
    assert b["id"] == a["id"] and b["fold"]["open"] is False and b["fold"]["pairs"] == 1
    other = ev("guardrail.violation", rule_id="x", severity="warning", action="log", channel="command", evidence="e")
    assert f.apply(other) is other                    # other events pass through untouched


def test_preview_caps_and_truncation_marker():
    big = {"text": "a" * 5000, "items": list(range(100)), "deep": {"a": {"b": {"c": {"d": {"e": 1}}}}},
           "keys": {f"k{i}": i for i in range(100)}}
    out, cut = feed.preview(big)
    assert cut and len(out["text"]) < 500 and out["text"].endswith("chars]")
    assert len(out["items"]) == feed.LIST_CAP + 1 and out["items"][-1].startswith("…[+")
    assert len(out["keys"]) <= feed.KEY_CAP + 1
    assert json.dumps(out)
    small, cut = feed.preview({"a": "b", "n": [1, 2]})
    assert not cut and small == {"a": "b", "n": [1, 2]}
    full, cut = feed.preview({"text": "a" * 5000}, full=True)
    assert not cut and len(full["text"]) == 5000
    huge, cut = feed.preview({f"k{i}": "x" * 300 for i in range(30)} | {"n": {"m": ["y" * 390] * 20}})
    assert cut and "_json_prefix" in huge and len(huge["_json_prefix"]) <= 2000


HOSTILE = ["</script><img src=x onerror=alert(1)>", "‮evil.txt", "line1\nline2\r\nline3\x00\x1b[31m",
           "data: {\"injected\": true}\n\n", "a" * 100_000, "\u2028\u2029", "{{7*7}} ${jndi:ldap://x}", "%s%n"]


@pytest.mark.parametrize("bad", HOSTILE)
def test_hostile_strings_stay_single_line_text(bad):
    ctx = feed.FeedContext()
    for typ, payload in [("tool.call", {"tool": bad, "input": {"command": bad}, "tool_use_id": bad}),
                         ("assistant.text", {"text": bad}),
                         ("guardrail.violation", {"rule_id": bad, "severity": bad, "action": bad, "evidence": bad}),
                         ("ops.message", {"text": bad}), ("weird.type", {"k": bad}),
                         ("state", {"from": bad, "to": bad})]:
        d = feed.display_event("agent_stream", 0, {"ts": "x", "type": typ, "payload": payload}, ctx)
        for field in ("title", "summary"):
            s = d[field]
            assert "\n" not in s and "\r" not in s and "\x00" not in s and "\x1b" not in s
            assert not any(c in s for c in "\u202e\u2028\u2029")
            assert len(s) <= feed.SUMMARY_CAP
        assert d["severity"] in feed.SEVERITIES      # a hostile severity string cannot become a CSS class
        assert d["kind"] in feed.KINDS
        line = json.dumps(d)                          # SSE data line: must be one line
        assert "\n" not in line and "\r" not in line
        assert len(line) < 20_000


def test_unknown_and_malformed_events_fall_back_to_generic():
    ctx = feed.FeedContext()
    d = feed.display_event("custom", 5, {"ts": "x", "type": "brand.new", "payload": {"a": 1, "b": "two"}}, ctx)
    assert d["kind"] == "generic" and d["title"] == "brand.new" and "a=1" in d["summary"]
    for ev in ({}, {"type": 5, "payload": 7}, {"type": "tool.call", "payload": None},
               {"type": "tool.call", "payload": {"input": 5, "tool": None}}):
        d = feed.display_event("x", 0, ev, ctx)
        assert set(d) == REQUIRED


def test_summarizer_exception_does_not_break_the_feed(monkeypatch):
    def boom(p, ev, ctx):
        raise RuntimeError("bug")
    monkeypatch.setitem(feed._REG, "tool.call", (boom, ""))
    d = feed.display_event("agent_stream", 0, {"ts": "x", "type": "tool.call", "payload": {}}, feed.FeedContext())
    assert d["kind"] == "generic" and "could not summarise" in d["summary"]


def test_schema_lists_kinds_and_types():
    s = feed.schema()
    assert s["version"] == 1 and {k["kind"] for k in s["kinds"]} == set(feed.KINDS)
    assert any(t["type"] == "tool.call" for t in s["types"])
    assert set(s["fields"]) == REQUIRED
    json.dumps(s)


def test_run_clock_after_a_resume_does_not_add_the_offset_twice():
    # run.clock start_epoch is the virtual origin (wall start - offset_s), as the orchestrator emits it
    c = feed.RunClock.from_events([
        {"type": "run.clock", "payload": {"start_epoch": 1_000.0, "offset_s": 0.0}},
        {"type": "run.clock", "payload": {"start_epoch": 10_000.0 - 3_600.0, "offset_s": 3_600.0}}])
    assert c.t_s(1_500.0) == pytest.approx(500.0)          # before the resume
    assert c.t_s(10_060.0) == pytest.approx(3_660.0)       # after it: 3600 + 60, not 7200 + 60
