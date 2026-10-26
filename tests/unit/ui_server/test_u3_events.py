"""U3: paged and merged event access."""
from __future__ import annotations

import json
import os

import pytest

from tests.unit.analysis.synth import make_run
from tests.unit.ui_server.u3_synth import (
    add_orch,
    agent_stream,
    append,
    guardrail,
    line,
    snapshot_tree,
    write_lines,
)
from ui_server import eventlog as el


@pytest.fixture
def run(runs_dir):
    rid = make_run(runs_dir, n_cp=2)
    rd = runs_dir / rid
    script = [("text", 10 + i, f"thinking about thing {i}") for i in range(30)]
    agent_stream(rd, rid, script)
    guardrail(rd, rid, [(20.5, "guardrail.violation", {"rule_id": "r1", "severity": "warning", "action": "log",
                                                      "channel": "command", "evidence": "x"}),
                        (25.5, "guardrail.kill", {"rule_id": "r2", "reason": "policy"})])
    return rid


def ev(client, rid, **params):
    r = client.get(f"/api/runs/{rid}/events", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def walk(client, rid, **params):
    seen, after = [], None
    for _ in range(500):
        body = ev(client, rid, **({"after": after} if after else {}), **params)
        seen += body["events"]
        after = body["next"]
        if body["eof"] and not body["events"]:
            break
        if body["eof"]:
            break
    return seen, after


def test_single_source_paging_covers_everything_once(client, run):
    first = ev(client, run, source="agent_stream", limit=7)
    assert len(first["events"]) == 7 and first["eof"] is False and first["mode"] == "single"
    seen, after = walk(client, run, source="agent_stream", limit=7)
    seqs = [e["seq"] for e in seen]
    assert seqs == list(range(len(seqs))) and len(seqs) > 60
    assert len({e["cursor"] for e in seen}) == len(seen)
    # polling again at the end returns nothing new but keeps a usable cursor
    again = ev(client, run, source="agent_stream", after=after)
    assert again["events"] == [] and again["eof"] is True and again["next"] == after


def test_limit_is_clamped(client, run):
    body = ev(client, run, source="agent_stream", limit=10**6)
    assert body["limit"] == el.MAX_LIMIT
    assert client.get(f"/api/runs/{run}/events", params={"limit": 0}).status_code == 422


def test_torn_last_line_is_invisible_until_complete(client, run, runs_dir):
    p = runs_dir / run / "events" / "agent_stream.jsonl"
    full = line(run, "agent_stream", "assistant.text", 9999, {"session_id": "s", "text": "late"}, 99.0)
    append(p, full[:40])                                  # torn
    seen, after = walk(client, run, source="agent_stream", limit=50)
    assert all(e["seq"] != 9999 for e in seen)
    append(p, full[40:] + "\n")                           # completed
    body = ev(client, run, source="agent_stream", after=after)
    assert [e["seq"] for e in body["events"]] == [9999]


def test_malformed_middle_line_is_skipped(client, runs_dir):
    rid = make_run(runs_dir, n_cp=1)
    p = runs_dir / rid / "events" / "env.jsonl"
    write_lines(p, [line(rid, "env", "env.mutated", 0, {"a": 1}, 1.0), "{not json", "",
                    line(rid, "env", "env.mutated", 1, {"a": 2}, 2.0)])
    body = ev(client, rid, source="env")
    assert [e["seq"] for e in body["events"]] == [0, 1]


def test_merged_view_is_time_ordered_with_stable_cursor(client, run):
    seen, _ = walk(client, run, source="agent_stream,guardrail,orchestrator", limit=9)
    keys = [el.ts_epoch(e["ts"]) for e in seen if e["ts"] != "x"]
    assert keys == sorted(keys)
    assert {e["source"] for e in seen} == {"agent_stream", "guardrail", "orchestrator"}
    assert len({e["cursor"] for e in seen}) == len(seen)
    # same events as the three single-source walks
    singles = 0
    for s in ("agent_stream", "guardrail", "orchestrator"):
        singles += len(walk(client, run, source=s, limit=50)[0])
    assert len(seen) == singles
    page = ev(client, run, source="agent_stream,guardrail", limit=3)
    assert page["mode"] == "merged" and page["next"].startswith("m:")


def test_default_is_all_sources_merged(client, run):
    body = ev(client, run, limit=5)
    assert body["mode"] == "merged" and set(body["sources"]) == set(el.SOURCES)


def test_cursor_mode_mismatch_is_rejected(client, run):
    merged_next = ev(client, run, source="agent_stream,guardrail", limit=2)["next"]
    r = client.get(f"/api/runs/{run}/events", params={"source": "agent_stream", "after": merged_next})
    assert r.status_code == 400
    single = ev(client, run, source="agent_stream", limit=2)["next"]
    r = client.get(f"/api/runs/{run}/events", params={"source": "guardrail", "after": single})
    assert r.status_code == 400


def test_type_filter_exact_and_glob(client, run):
    body = ev(client, run, source="agent_stream", type="assistant.text", limit=1000)
    assert body["events"] and {e["type"] for e in body["events"]} == {"assistant.text"}
    body = ev(client, run, source="agent_stream", type="stream.*,session.init", limit=1000)
    assert {e["type"] for e in body["events"]} == {"stream.assistant", "session.init"}
    assert client.get(f"/api/runs/{run}/events", params={"type": "a b;"}).status_code == 400


def test_substring_search_case_insensitive(client, run):
    body = ev(client, run, source="agent_stream", q="THING 17", limit=100)
    assert [e["payload"]["text"] for e in body["events"]] == ["thinking about thing 17"]
    assert ev(client, run, source="agent_stream", q="no such words")["events"] == []
    assert client.get(f"/api/runs/{run}/events", params={"q": "x" * 401}).status_code == 422


def test_scan_cap_returns_resumable_cursor(run, runs_dir):
    rl = el.RunLog(runs_dir / run)
    flt = el.Filters.make(None, "zzz-nothing")
    r1 = el.read_page(rl, ["agent_stream"], None, flt, 10, max_scan=2000)
    assert r1["scan_capped"] is True and r1["eof"] is False and r1["events"] == []
    assert r1["next"] != "agent_stream:0"
    r2 = el.read_page(rl, ["agent_stream"], r1["next"], flt, 10, max_scan=10**7)
    assert r2["eof"] is True and r2["scan_capped"] is False


def test_huge_payload_is_truncated_and_full_fetch_works(client, runs_dir):
    rid = make_run(runs_dir, n_cp=1)
    big = "A" * 500_000
    p = runs_dir / rid / "events" / "counterpart.jsonl"
    write_lines(p, [line(rid, "counterpart", "ops.message", 0, {"text": big, "n": 1}, 5.0),
                    line(rid, "counterpart", "ops.message", 1, {"nested": {"deep": ["B" * 5000] * 20}}, 6.0)])
    body = ev(client, rid, source="counterpart")
    e0, e1 = body["events"]
    assert e0["truncated"] is True and len(e0["payload"]["text"]) < 3000 and "truncated" in e0["payload"]["text"]
    assert e0["payload"]["n"] == 1 and e0["bytes"] > 500_000
    assert e1["truncated"] is True
    assert len(json.dumps(e1)) < el.EVENT_JSON_CAP + 2000
    full = client.get(f"/api/runs/{rid}/events/at", params={"cursor": e0["cursor"]}).json()["event"]
    assert full["payload"]["text"] == big and full["truncated"] is False
    small = ev(client, rid, source="counterpart", max_chars=100)["events"][0]
    assert len(small["payload"]["text"]) < 200


def test_oversized_line_is_reported_not_parsed(client, runs_dir, monkeypatch):
    rid = make_run(runs_dir, n_cp=1)
    monkeypatch.setattr(el, "MAX_LINE", 1000)
    p = runs_dir / rid / "events" / "env.jsonl"
    write_lines(p, [line(rid, "env", "env.mutated", 0, {"x": "y" * 5000}, 1.0),
                    line(rid, "env", "env.mutated", 1, {"x": "ok"}, 2.0)])
    el.clear_cache()
    body = ev(client, rid, source="env")
    assert [e["type"] for e in body["events"]] == ["_oversized", "env.mutated"]
    assert body["events"][1]["payload"] == {"x": "ok"}


@pytest.mark.parametrize("bad", ["", "agent_stream", "agent_stream:", "agent_stream:-1", "agent_stream:1.5",
                                 "../../etc/passwd:0", "agent_stream:0/../x", "agent_stream:99999999999",
                                 "agent_stream:1", "otel:0,agent_stream:1", "m:agent_stream=1", "m:x=0",
                                 "AGENT_STREAM:0", "agent_stream:00000000000000000000"])
def test_bad_cursors_are_400(client, run, bad):
    r = client.get(f"/api/runs/{run}/events", params={"source": "agent_stream", "after": bad})
    if bad == "":
        assert r.status_code == 200      # empty = start
    else:
        assert r.status_code == 400, bad
    r = client.get(f"/api/runs/{run}/events/at", params={"cursor": bad})
    assert r.status_code in (400, 404, 422)


def test_unknown_or_repeated_source_is_400(client, run):
    for s in ("nope", "../x", "agent_stream,agent_stream", "agent_stream.jsonl", "otel/../scorer"):
        assert client.get(f"/api/runs/{run}/events", params={"source": s}).status_code == 400, s


def test_events_at_requires_a_line_start(client, run):
    first = ev(client, run, source="agent_stream", limit=2)["events"]
    off = int(first[1]["cursor"].split(":")[1])
    assert client.get(f"/api/runs/{run}/events/at", params={"cursor": f"agent_stream:{off}"}).status_code == 200
    assert client.get(f"/api/runs/{run}/events/at", params={"cursor": f"agent_stream:{off + 3}"}).status_code == 400


def test_cursor_past_end_is_400(client, run, runs_dir):
    size = (runs_dir / run / "events" / "agent_stream.jsonl").stat().st_size
    r = client.get(f"/api/runs/{run}/events", params={"source": "agent_stream", "after": f"agent_stream:{size}"})
    assert r.status_code == 200 and r.json()["events"] == []
    r = client.get(f"/api/runs/{run}/events", params={"source": "agent_stream", "after": f"agent_stream:{size + 5}"})
    assert r.status_code == 400


def test_summary_counts_and_clock(client, run):
    s = client.get(f"/api/runs/{run}/events/summary").json()
    a = s["sources"]["agent_stream"]
    assert a["counts"]["assistant.text"] == 30 and a["counts"]["session.init"] == 1
    assert a["lines"] == sum(a["counts"].values()) and a["bytes"] > 0 and a["bad_lines"] == 0
    assert "otel" not in s["sources"]            # missing files are simply absent
    assert s["clocks"] == [{"start_epoch": 1_800_000_000.0, "offset_s": 0.0}]


def test_index_is_cached_and_extended_incrementally(run, runs_dir):
    p = runs_dir / run / "events" / "agent_stream.jsonl"
    i1 = el.get_index(p)
    assert el.get_index(p) is i1
    n = i1.lines
    append(p, line(run, "agent_stream", "assistant.text", 5000, {"text": "more"}, 80.0) + "\n")
    i2 = el.get_index(p)
    assert i2.lines == n + 1 and i2.counts["assistant.text"] == 31
    assert i2.end == p.stat().st_size


def test_locate_by_seq_and_time(client, run):
    r = client.get(f"/api/runs/{run}/events/locate", params={"source": "agent_stream", "seq": 40}).json()
    assert r["found"] is True
    e = client.get(f"/api/runs/{run}/events/at", params={"cursor": r["cursor"]}).json()["event"]
    assert e["seq"] == 40
    r = client.get(f"/api/runs/{run}/events/locate", params={"source": "agent_stream", "t_s": 20.2}).json()
    e = client.get(f"/api/runs/{run}/events/at", params={"cursor": r["cursor"]}).json()["event"]
    assert e["t_s"] >= 20.2 and e["t_s"] < 22
    miss = client.get(f"/api/runs/{run}/events/locate", params={"source": "agent_stream", "seq": 10**6}).json()
    assert miss["found"] is False
    assert client.get(f"/api/runs/{run}/events/locate", params={"source": "agent_stream"}).status_code == 400


def test_event_t_s_uses_the_run_clock(client, run):
    gr = ev(client, run, source="guardrail")["events"]
    assert [e["t_s"] for e in gr] == [20.5, 25.5]


def test_resumed_run_clock_offset(client, runs_dir):
    rid = make_run(runs_dir, n_cp=1)
    add_orch(runs_dir / rid, rid, [(100.0, "run.clock", {"start_epoch": 1_800_000_100.0, "offset_s": 500.0})])
    guardrail(runs_dir / rid, rid, [(150.0, "guardrail.violation", {"rule_id": "r"})])
    e = ev(client, rid, source="guardrail")["events"][0]
    assert e["t_s"] == 550.0


def test_run_id_checks_apply(client, run):
    for rid in ("..", "nope", "a%2F..%2Fb", ".hidden"):
        assert client.get(f"/api/runs/{rid}/events").status_code == 404, rid


def test_symlinked_event_file_is_not_followed(client, runs_dir, tmp_path):
    rid = make_run(runs_dir, n_cp=1)
    outside = tmp_path / "secret.jsonl"
    outside.write_text(line(rid, "env", "env.mutated", 0, {"secret": "yes"}, 1.0) + "\n")
    os.symlink(outside, runs_dir / rid / "events" / "env.jsonl")
    body = ev(client, rid, source="env")
    assert body["events"] == []


def test_no_writes_to_the_run_dir(client, run, runs_dir):
    before = snapshot_tree(runs_dir)
    for path, params in [("events", {}), ("events", {"source": "agent_stream", "q": "thing"}), ("events/summary", {}),
                         ("events/locate", {"source": "agent_stream", "seq": 3}),
                         ("events/at", {"cursor": "agent_stream:0"})]:
        assert client.get(f"/api/runs/{run}/{path}", params=params).status_code == 200
    assert snapshot_tree(runs_dir) == before


def test_token_required(client, run):
    r = client.get(f"/api/runs/{run}/events", headers={"X-LRAE-Token": "wrong"})
    assert r.status_code in (401, 403)
