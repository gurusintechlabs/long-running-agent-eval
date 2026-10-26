"""U3: normalised transcript."""
from __future__ import annotations

import pytest

from tests.unit.analysis.synth import make_run
from tests.unit.ui_server.u3_synth import add_orch, agent_stream, line, snapshot_tree, write_lines

LONG = "L" * 9000


@pytest.fixture
def run(runs_dir):
    rid = make_run(runs_dir, n_cp=2)
    rd = runs_dir / rid
    add_orch(rd, rid, [(0.05, "turn.start", {"first": True}), (100.0, "turn.end", {"turn": 1, "returncode": 0}),
                       (110.0, "turn.start", {"first": False}), (300.0, "turn.end", {"turn": 2, "returncode": 0})])
    agent_stream(rd, rid, [
        ("text", 5, "I will start by reading the readme"),
        ("tool", 6, "tu1", "Read", {"file_path": "/Users/tonylee/proj/README.md"}, "readme body", False),
        ("tool", 20, "tu2", "Bash", {"command": "pytest -q\necho second line"}, "3 failed, 5 passed\n" + LONG, True),
        ("test_run", 21, 5, 3),
        ("text", 30, "<script>alert(1)</script> tests fail"),
        ("compaction", 50, 900000),
        ("tool", 120, "tu3", "Bash", {"command": "ls"}, "a b c", False),
        ("text", 130, "second turn text"),
        ("tool", 140, "tu4", "Grep", {"pattern": "needle", "path": "src"}, "src/a.py:1:needle", False),
    ])
    return rid


def get(client, rid, **params):
    r = client.get(f"/api/runs/{rid}/transcript", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_items_are_normalised_and_paired(client, run):
    body = get(client, run, limit=100)
    kinds = [i["kind"] for i in body["items"]]
    assert kinds == ["session", "text", "tool", "tool", "test_run", "text", "compaction", "tool", "text", "tool"]
    t = {i["tool_use_id"]: i for i in body["items"] if i["kind"] == "tool"}
    assert t["tu1"]["tool"] == "Read" and t["tu1"]["input_summary"].endswith("/proj/README.md")
    assert t["tu2"]["status"] == "error" and t["tu2"]["input_summary"] == "pytest -q"
    assert t["tu1"]["status"] == "ok" and t["tu1"]["dur_s"] == 0.5
    assert t["tu2"]["result_size"] == len(LONG) + len("3 failed, 5 passed\n")
    assert len(t["tu2"]["result_tail"]) <= 600
    assert t["tu1"]["has_result"] and t["tu1"]["result_cursor"].startswith("agent_stream:")
    assert body["eof"] is True and body["total_items"] == 10
    assert body["tools"][0] == {"tool": "Bash", "count": 2, "errors": 1}


def test_items_carry_cursor_seq_and_run_time(client, run):
    items = get(client, run, limit=100)["items"]
    assert all(i["cursor"].startswith("agent_stream:") and isinstance(i["seq"], int) for i in items)
    assert items[2]["t_s"] == 6.0 and items[3]["t_s"] == 20.0
    # the cursor leads to the exact event
    e = client.get(f"/api/runs/{run}/events/at", params={"cursor": items[3]["cursor"]}).json()["event"]
    assert e["type"] == "tool.call" and e["payload"]["tool_use_id"] == "tu2"


def test_turn_grouping(client, run):
    body = get(client, run, limit=100)
    assert [t["turn"] for t in body["turns"]] == [1, 2]
    by = {i["cursor"]: i["turn"] for i in body["items"]}
    turns = [i["turn"] for i in body["items"]]
    assert turns[:7] == [1] * 7 and turns[7:] == [2, 2, 2]
    only2 = get(client, run, turn=2)
    assert [i["kind"] for i in only2["items"]] == ["tool", "text", "tool"] and by


def test_paging_by_cursor(client, run):
    seen, after = [], None
    while True:
        b = get(client, run, limit=3, **({"after": after} if after else {}))
        seen += b["items"]
        after = b["next"]
        if b["eof"]:
            break
    assert len(seen) == 10 and len({i["cursor"] for i in seen}) == 10


def test_tool_filter_text_search_and_errors(client, run):
    assert [i["tool_use_id"] for i in get(client, run, tool="Bash")["items"]] == ["tu2", "tu3"]
    assert [i["tool_use_id"] for i in get(client, run, tool="Grep,Read")["items"]] == ["tu1", "tu4"]
    assert [i["kind"] for i in get(client, run, kind="text")["items"]] == ["text"] * 3
    assert [i["tool_use_id"] for i in get(client, run, q="NEEDLE")["items"]] == ["tu4"]
    assert [i["tool_use_id"] for i in get(client, run, q="readme")["items"] if i["kind"] == "tool"] == ["tu1"]
    assert [i["tool_use_id"] for i in get(client, run, errors_only="true")["items"]] == ["tu2"]
    assert get(client, run, q="zzzz")["items"] == []
    assert client.get(f"/api/runs/{run}/transcript", params={"kind": "bogus"}).status_code == 400


def test_around_returns_context_window(client, run):
    items = get(client, run, limit=100)["items"]
    c = items[5]["cursor"]
    b = get(client, run, around=c, before=2, after_n=1)
    assert [i["cursor"] for i in b["items"]] == [i["cursor"] for i in items[3:7]]
    assert b["anchor"] == c and b["mode"] == "around"
    b = get(client, run, around_seq=items[3]["seq"], before=0, after_n=0)
    assert [i["cursor"] for i in b["items"]] == [items[3]["cursor"]]
    b = get(client, run, around_t_s=30, before=0, after_n=0)
    assert b["items"][0]["kind"] == "text" and b["items"][0]["t_s"] == 30.0


def test_hostile_text_is_data(client, run):
    texts = [i["text"] for i in get(client, run, kind="text")["items"]]
    assert "<script>alert(1)</script> tests fail" in texts       # returned verbatim as a JSON string
    r = client.get(f"/api/runs/{run}/transcript")
    assert r.headers["content-type"].startswith("application/json")


def test_long_text_is_cut_in_list_and_full_in_detail(client, runs_dir):
    rid = make_run(runs_dir, n_cp=1)
    agent_stream(runs_dir / rid, rid, [("text", 5, "T" * 30_000)])
    it = get(client, rid, kind="text", max_chars=100)["items"][0]
    assert len(it["text"]) == 100 and it["text_truncated"] is True and it["chars"] == 30_000
    d = client.get(f"/api/runs/{rid}/transcript/item", params={"cursor": it["cursor"]}).json()
    assert len(d["event"]["payload"]["text"]) == 30_000


def test_item_detail_has_full_input_and_result_text(client, run):
    items = get(client, run, limit=100)["items"]
    tu2 = next(i for i in items if i.get("tool_use_id") == "tu2")
    d = client.get(f"/api/runs/{run}/transcript/item", params={"cursor": tu2["cursor"]}).json()
    assert d["event"]["payload"]["input"]["command"] == "pytest -q\necho second line"
    assert d["result_text"].startswith("3 failed, 5 passed") and len(d["result_text"]) == tu2["result_size"]
    assert d["result_event"]["type"] == "tool.result" and d["item"]["status"] == "error"


def test_item_detail_rejects_non_item_cursors(client, run):
    # the raw stream.assistant line is not a transcript item
    first = client.get(f"/api/runs/{run}/events", params={"source": "agent_stream", "limit": 3}).json()["events"]
    raw = next(e for e in first if e["type"] == "stream.assistant")
    assert client.get(f"/api/runs/{run}/transcript/item", params={"cursor": raw["cursor"]}).status_code == 404
    for bad in ("otel:0", "agent_stream:x", "../x", "agent_stream:5"):
        assert client.get(f"/api/runs/{run}/transcript/item", params={"cursor": bad}).status_code in (400, 404)


def test_result_without_call_and_pending_call(client, runs_dir):
    rid = make_run(runs_dir, n_cp=1)
    lines = [
        line(rid, "agent_stream", "tool.call", 0, {"tool_use_id": "p1", "tool": "Bash", "input": {"command": "sleep"}}, 1),
        line(rid, "agent_stream", "tool.result", 1, {"tool_use_id": "ghost", "is_error": False, "size": 3,
                                                     "text_tail": "abc"}, 2),
    ]
    write_lines(runs_dir / rid / "events" / "agent_stream.jsonl", lines)
    items = get(client, rid)["items"]
    assert items[0]["status"] == "pending" and items[0]["has_result"] is False
    assert items[1]["tool"] is None and items[1]["status"] == "ok"


def test_missing_stream_is_empty(client, runs_dir):
    rid = make_run(runs_dir, n_cp=1)
    b = get(client, rid)
    assert b["items"] == [] and b["eof"] is True and b["total_items"] == 0


def test_index_grows_with_the_file(client, run, runs_dir):
    assert get(client, run)["total_items"] == 10
    from tests.unit.ui_server.u3_synth import append
    append(runs_dir / run / "events" / "agent_stream.jsonl",
           line(run, "agent_stream", "assistant.text", 900, {"session_id": "s1", "text": "newest"}, 200.0) + "\n")
    b = get(client, run)
    assert b["total_items"] == 11 and b["items"][-1]["text"] == "newest"


def test_no_writes(client, run, runs_dir):
    before = snapshot_tree(runs_dir)
    items = get(client, run)["items"]
    client.get(f"/api/runs/{run}/transcript/item", params={"cursor": items[2]["cursor"]})
    assert snapshot_tree(runs_dir) == before


def test_paths_are_scrubbed_like_u1(client, run):
    import pathlib
    home = str(pathlib.Path.home())
    body = client.get(f"/api/runs/{run}/transcript", params={"limit": 100}).text
    assert home not in body
