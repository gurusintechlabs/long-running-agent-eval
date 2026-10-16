import json
from pathlib import Path

from telemetry.stream_parser import TEXT_LIMIT, parse_message

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "stream"


def load(name):
    return [json.loads(x) for x in (FIX / name).read_text().splitlines()]


def parse_all(name):
    return [e for m in load(name) for e in parse_message(m)]


def test_real_fixture_init_text_result():
    evs = parse_all("cli-1.0.126-haiku-ok.jsonl")
    assert [t for t, _ in evs] == ["session.init", "assistant.text", "session.result"]
    init, text, res = (p for _, p in evs)
    assert init["model"] == "claude-haiku-5-5" and init["apiKeySource"] == "none"
    assert init["permissionMode"] == "bypassPermissions" and "Bash" in init["tools"]
    assert text["text"] == "OK" and text["truncated"] is False and len(text["text_sha256"]) == 64
    assert res["total_cost_usd"] == 0.0063735 and res["is_error"] is False and res["num_turns"] == 1
    assert res["modelUsage"]["claude-haiku-5-5"]["contextWindow"] == 200000
    assert "result_text" not in res
    assert {init["session_id"], text["session_id"], res["session_id"]} == {"6a49fe16-9d39-4849-8675-6a887075c797"}


# SYNTHETIC fixture: shapes follow the documented stream-json format, not a real capture.
def test_synthetic_tools_and_compaction():
    evs = parse_all("synthetic-tools-compact.jsonl")  # first line is a _synthetic marker -> no events
    assert [t for t, _ in evs] == ["session.init", "assistant.text", "tool.call", "tool.result", "tool.call",
                                   "tool.result", "context.compaction", "session.result"]
    call = evs[2][1]
    assert call == {"session_id": "syn-sess-1", "tool_use_id": "toolu_01", "tool": "Bash",
                    "input": {"command": "pytest -q", "description": "run tests"}}
    assert evs[3][1] == {"session_id": "syn-sess-1", "tool_use_id": "toolu_01", "is_error": False,
                         "size": len("3 passed in 0.1s")}
    assert evs[5][1]["is_error"] is True and evs[5][1]["size"] == len("File does not exist.")
    assert evs[6][1] == {"session_id": "syn-sess-1", "trigger": "auto", "pre_tokens": 167000}
    res = evs[7][1]
    assert res["is_error"] and res["result_text"] == "API Error: 529 overloaded"


def test_long_text_truncated_with_hash():
    text = "x" * (TEXT_LIMIT + 5)
    (_, p), = parse_message({"type": "assistant", "session_id": "s",
                             "message": {"content": [{"type": "text", "text": text}]}})
    assert len(p["text"]) == TEXT_LIMIT and p["truncated"] is True
    import hashlib
    assert p["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()


def test_long_tool_input_truncated_nested_with_hash():
    inp = {"file_path": "a.py", "content": "y" * (TEXT_LIMIT + 1), "edits": [{"new": "z" * 30000}]}
    (_, p), = parse_message({"type": "assistant", "session_id": "s", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Write", "input": inp}]}})
    assert p["truncated"] is True and len(p["input"]["content"]) == TEXT_LIMIT
    assert len(p["input"]["edits"][0]["new"]) == TEXT_LIMIT and p["input"]["file_path"] == "a.py"
    canon = json.dumps(inp, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    import hashlib
    assert p["input_sha256"] == hashlib.sha256(canon.encode()).hexdigest()


def test_small_tool_input_has_no_truncation_fields():
    (_, p), = parse_message({"type": "assistant", "session_id": "s", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}})
    assert "input_sha256" not in p and "truncated" not in p


def test_result_text_truncated_to_2000_on_error_only():
    (_, p), = parse_message({"type": "result", "subtype": "error", "is_error": True, "session_id": "s",
                             "result": "e" * 5000})
    assert len(p["result_text"]) == 2000


def test_multiple_blocks_keep_order():
    evs = parse_message({"type": "assistant", "session_id": "s", "message": {"content": [
        {"type": "tool_use", "id": "a", "name": "Read", "input": {}}, {"type": "text", "text": "hi"},
        {"type": "thinking", "thinking": "..."}]}})
    assert [t for t, _ in evs] == ["tool.call", "assistant.text"]


def test_unknown_and_malformed_shapes_never_raise():
    for bad in [None, 5, "x", [], {}, {"type": "weird"}, {"type": "assistant"}, {"type": "assistant", "message": 3},
                {"type": "assistant", "message": {"content": [None, 5, {"type": "tool_use"}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
                {"type": "system", "subtype": "compact_boundary", "compact_metadata": "oops"},
                {"type": "system", "subtype": "other"}, {"type": "result", "result": object()}]:
        out = parse_message(bad)
        assert isinstance(out, list)
