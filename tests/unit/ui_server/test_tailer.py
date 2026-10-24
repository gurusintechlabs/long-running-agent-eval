"""Read-only tailing: torn lines, late files, oversize lines, ordering, cursors, backlog start."""
from __future__ import annotations

import json
import os

import pytest

from ui_server import tailer
from ui_server.tailer import (
    CursorError,
    FileTail,
    Merger,
    encode_cursor,
    locate_tail,
    parse_cursor,
    parse_ref,
)


def line(ts, typ="x", **p):
    return json.dumps({"ts": ts, "mono_ns": 1, "run_id": "r", "source": "s", "type": typ, "seq": 0,
                       "payload": p}) + "\n"


def test_cursor_roundtrip_and_rejects_garbage():
    pos = {"agent_stream": 12, "guardrail": 0}
    assert parse_cursor(encode_cursor(pos)) == pos
    assert parse_cursor("v1:") == {}
    for bad in ("", "v2:a=1", "v1:a", "v1:a=-1", "v1:a=1.5", "v1:../x=1", "v1:a=1;b=2", "v1:a=" + "9" * 30,
                None, 5, "v1:" + "a=1," * 1000):
        with pytest.raises(CursorError):
            parse_cursor(bad)
    assert parse_ref("agent_stream:123") == ("agent_stream", 123)
    for bad in ("agent_stream", "a/b:1", "a:-1", ":1"):
        with pytest.raises(CursorError):
            parse_ref(bad)


def test_filetail_torn_line_waits_for_newline(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text(line("1") + '{"ts": "2", "ty')
    t = FileTail(f)
    lines, eof = t.read()
    assert [ln.start for ln in lines] == [0] and eof
    assert t.offset == len(line("1"))
    assert t.read() == ([], True)                     # still torn
    with open(f, "a") as fh:
        fh.write('pe": "x"}\n')
    lines, _ = t.read()
    assert len(lines) == 1 and lines[0].data.endswith(b'"x"}')


def test_filetail_missing_file_then_appears(tmp_path):
    t = FileTail(tmp_path / "later.jsonl")
    assert t.read() == ([], True)
    (tmp_path / "later.jsonl").write_text(line("1"))
    assert len(t.read()[0]) == 1


def test_filetail_oversize_line_is_skipped_not_buffered(tmp_path, monkeypatch):
    monkeypatch.setattr(tailer, "MAX_LINE", 1000)
    monkeypatch.setattr(tailer, "CHUNK", 400)
    f = tmp_path / "a.jsonl"
    big = "x" * 5000
    f.write_text(line("1") + big)                     # a huge line still being written
    t = FileTail(f)
    lines, _ = t.read()
    assert len(lines) == 1                            # only the first complete line
    with open(f, "a") as fh:
        fh.write("y" * 100 + "\n" + line("3"))
    lines, _ = t.read()
    assert [ln.data is None for ln in lines] == [True, False]
    assert lines[0].size == 5100
    assert json.loads(lines[1].data)["ts"] == "3"


def test_filetail_line_longer_than_chunk_but_under_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(tailer, "CHUNK", 300)
    f = tmp_path / "a.jsonl"
    f.write_text(line("1", t="z" * 900) + line("2"))
    got = []
    t = FileTail(f)
    for _ in range(5):
        got += t.read()[0]
    assert [json.loads(g.data)["ts"] for g in got] == ["1", "2"]


def test_filetail_replaced_shorter_file_restarts(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text(line("1") * 3)
    t = FileTail(f)
    assert len(t.read()[0]) == 3
    f.write_text(line("9"))
    lines, _ = t.read()
    assert len(lines) == 1 and t.restarted


def test_filetail_never_follows_symlinks(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text('{"ts": "1"}\n')
    link = tmp_path / "a.jsonl"
    link.symlink_to(secret)
    assert FileTail(link).read() == ([], True)
    assert tailer.list_event_files(tmp_path) == {}


def test_merger_orders_by_ts_across_files_and_keeps_file_order(tmp_path):
    (tmp_path / "a.jsonl").write_text(line("2026-01-01T00:00:01Z", "a1") + line("2026-01-01T00:00:03Z", "a2"))
    (tmp_path / "b.jsonl").write_text(line("2026-01-01T00:00:02Z", "b1") + line("2026-01-01T00:00:04Z", "b2"))
    m = Merger(tmp_path)
    items = m.poll()
    assert [i.type for i in items] == ["a1", "b1", "a2", "b2"]
    assert m.poll() == [] and m.drained()


def test_merger_large_backlog_is_ordered_in_bounded_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(tailer, "CHUNK", 2000)
    a, b = [], []
    for i in range(300):
        (a if i % 3 else b).append(line(f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z", f"e{i}"))
    (tmp_path / "a.jsonl").write_text("".join(a))
    (tmp_path / "b.jsonl").write_text("".join(b))
    m = Merger(tmp_path)
    got = []
    for _ in range(500):
        batch = m.poll(max_events=50)
        if not batch:
            break
        assert len(batch) <= 50
        got += batch
    assert [i.type for i in got] == [f"e{i}" for i in range(300)]
    assert max(len(q) for q in m.buf.values()) <= 100   # bounded buffering


def test_merger_picks_up_late_files_and_resumes_from_offsets(tmp_path):
    (tmp_path / "a.jsonl").write_text(line("1", "a1"))
    m = Merger(tmp_path)
    assert [i.type for i in m.poll()] == ["a1"]
    (tmp_path / "b.jsonl").write_text(line("2", "b1"))
    (tmp_path / "a.jsonl").open("a").write(line("3", "a2"))
    items = m.poll()
    assert [i.type for i in items] == ["b1", "a2"]
    # resume from the end offsets of what was delivered
    pos = {"a": items[1].end, "b": items[0].end}
    m2 = Merger(tmp_path, pos)
    assert m2.poll() == []
    (tmp_path / "b.jsonl").open("a").write(line("4", "b2"))
    assert [i.type for i in m2.poll()] == ["b2"]


def test_merger_torn_last_line_not_delivered_until_complete(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text(line("1", "a1") + '{"ts": "2", "type": "a2", "se')
    m = Merger(tmp_path)
    assert [i.type for i in m.poll()] == ["a1"]
    with open(f, "a") as fh:
        fh.write('q": 1, "payload": {}}\n')
    assert [i.type for i in m.poll()] == ["a2"]


def test_peek_handles_spaced_and_compact_json_and_garbage():
    assert tailer.peek(line("T", "tool.call").encode()) == ("T", "tool.call")
    assert tailer.peek(b'{"ts":"T","mono_ns":1,"type":"x","seq":1}') == ("T", "x")
    assert tailer.peek(b"not json") is None
    # a hostile payload cannot spoof the envelope type: the prefix before payload wins
    evil = json.dumps({"ts": "T", "type": "real", "payload": {"type": "spoof"}}).encode()
    assert tailer.peek(evil)[1] == "real"


def test_locate_tail_starts_at_last_n_visible_events(tmp_path):
    rows_a = [line(f"2026-01-01T00:00:{i:02d}Z", "keep" if i % 2 else "noise") for i in range(0, 40, 2)]
    rows_b = [line(f"2026-01-01T00:00:{i:02d}Z", "keep") for i in range(1, 40, 2)]
    (tmp_path / "a.jsonl").write_text("".join(rows_a))
    (tmp_path / "b.jsonl").write_text("".join(rows_b))
    start = locate_tail(tmp_path, 5, lambda s, t: t == "keep")
    m = Merger(tmp_path, start)
    types = []
    while True:
        batch = m.poll()
        if not batch:
            break
        types += [(i.ts[-3:-1], i.type) for i in batch]
    visible = [t for t in types if t[1] == "keep"]
    assert len(visible) == 5 and visible[-1][0] == "39"
    # n=0 means "from now": nothing is replayed
    now = locate_tail(tmp_path, 0, lambda s, t: True)
    assert Merger(tmp_path, now).poll() == []


def test_locate_tail_ignores_torn_trailing_line(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text(line("1", "k") + line("2", "k") + '{"ts": "3", "ty')
    start = locate_tail(tmp_path, 10, lambda s, t: True)
    assert start["a"] == 0
    now = locate_tail(tmp_path, 0, lambda s, t: True)
    assert now["a"] == len(line("1", "k") + line("2", "k"))
    with open(f, "a") as fh:
        fh.write('pe": "k"}\n')                       # the torn line completes after `now`
    assert [i.ts for i in Merger(tmp_path, now).poll()] == ["3"]


def test_check_boundary(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text(line("1") + line("2"))
    n1 = len(line("1"))
    assert tailer.check_boundary(f, 0) == 0
    assert tailer.check_boundary(f, n1) == n1
    assert tailer.check_boundary(f, n1 * 2) == n1 * 2
    assert tailer.check_boundary(f, n1 * 9) == 0      # file replaced by a shorter one
    with pytest.raises(CursorError):
        tailer.check_boundary(f, 7)


def test_read_line_at(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text(line("1") + line("2") + "torn")
    n1 = len(line("1"))
    data, n = tailer.read_line_at(f, n1)
    assert json.loads(data)["ts"] == "2" and n == n1 - 1
    assert tailer.read_line_at(f, n1 * 2)[0] is None   # torn
    assert tailer.read_line_at(f, 5)[0] is None        # not a boundary
    assert tailer.read_line_at(tmp_path / "nope.jsonl", 0)[0] is None


def test_tailer_is_read_only(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text(line("1"))
    before = (os.stat(f).st_mtime_ns, os.stat(f).st_size, sorted(os.listdir(tmp_path)))
    m = Merger(tmp_path)
    m.poll()
    locate_tail(tmp_path, 10, lambda s, t: True)
    after = (os.stat(f).st_mtime_ns, os.stat(f).st_size, sorted(os.listdir(tmp_path)))
    assert before == after
