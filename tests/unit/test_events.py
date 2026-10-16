import json
import threading

from telemetry.events import EventWriter, redact


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_envelope_fields_and_seq(tmp_path):
    w = EventWriter(tmp_path / "e.jsonl", run_id="r1", source="orchestrator")
    w.emit("a", {"x": 1})
    w.emit("b", {"y": 2})
    ev = read(tmp_path / "e.jsonl")
    assert [e["seq"] for e in ev] == [0, 1]
    assert ev[0]["run_id"] == "r1" and ev[0]["source"] == "orchestrator"
    assert ev[0]["type"] == "a" and ev[0]["payload"] == {"x": 1}
    assert ev[0]["ts"].endswith("Z") and isinstance(ev[0]["mono_ns"], int)
    assert ev[1]["mono_ns"] >= ev[0]["mono_ns"]


def test_reopen_appends_and_continues_seq(tmp_path):
    p = tmp_path / "e.jsonl"
    EventWriter(p, "r", "s").emit("a", {})
    EventWriter(p, "r", "s").emit("b", {})
    ev = read(p)
    assert [e["seq"] for e in ev] == [0, 1] and [e["type"] for e in ev] == ["a", "b"]


def test_never_truncates_existing_file(tmp_path):
    p = tmp_path / "e.jsonl"
    p.write_text('{"seq": 7, "type": "old"}\n')
    EventWriter(p, "r", "s").emit("new", {})
    lines = p.read_text().splitlines()
    assert json.loads(lines[0])["type"] == "old" and json.loads(lines[1])["seq"] == 8


def test_explicit_ts_override(tmp_path):
    w = EventWriter(tmp_path / "e.jsonl", "r", "otel")
    w.emit("t", {}, ts="2026-01-01T00:00:00.000000Z")
    assert read(tmp_path / "e.jsonl")[0]["ts"] == "2026-01-01T00:00:00.000000Z"


def test_redaction_of_token_like_strings(tmp_path):
    w = EventWriter(tmp_path / "e.jsonl", "r", "s")
    w.emit("t", {"k": "sk-ant-api03-ABCDEFGHIJKLMNOP", "h": "Bearer abcdef0123456789abcdef",
                 "g": "ghp_abcdefghijklmnopqrstuvwxyz0123456789", "ok": "plain text"})
    text = (tmp_path / "e.jsonl").read_text()
    assert "ABCDEFGHIJKLMNOP" not in text and "abcdef0123456789abcdef" not in text
    assert "ghp_abcdef" not in text and "plain text" in text
    assert "[REDACTED]" in text


def test_redact_nested_structures():
    out = redact({"a": ["sk-ant-oat01-" + "z" * 30, {"b": "x"}]})
    assert out["a"][0] == "[REDACTED]" and out["a"][1] == {"b": "x"}


def test_thread_safety_unique_ordered_seq(tmp_path):
    p = tmp_path / "e.jsonl"
    w = EventWriter(p, "r", "s")

    def work():
        for i in range(50):
            w.emit("t", {"i": i})

    ts = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    seqs = [e["seq"] for e in read(p)]
    assert seqs == list(range(200))


def test_non_serialisable_payload_does_not_crash(tmp_path):
    w = EventWriter(tmp_path / "e.jsonl", "r", "s")
    w.emit("t", {"p": tmp_path})
    assert read(tmp_path / "e.jsonl")[0]["payload"]["p"] == str(tmp_path)
