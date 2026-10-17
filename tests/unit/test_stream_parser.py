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
    assert [t for t, _ in evs] == ["session.init", "assistant.text", "tool.call", "tool.result",
                                   "agent.test_run", "tool.call", "tool.result", "context.compaction",
                                   "session.result"]
    assert evs[4][1]["passed"] == 3 and evs[4][1]["failed"] == 0
    evs = [e for e in evs if e[0] != "agent.test_run"]
    call = evs[2][1]
    assert call == {"session_id": "syn-sess-1", "tool_use_id": "toolu_01", "tool": "Bash",
                    "input": {"command": "pytest -q", "description": "run tests"}}
    assert evs[3][1] == {"session_id": "syn-sess-1", "tool_use_id": "toolu_01", "is_error": False,
                         "size": len("3 passed in 0.1s"),
                         "text_tail": "3 passed in 0.1s"}
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


def _result_events(text):
    msg = {"type": "user", "session_id": "s", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": text}]}}
    return parse_message(msg)


def _run(text):
    evs = [p for t, p in _result_events(text) if t == "agent.test_run"]
    return evs[0] if evs else None


def test_text_tail_is_last_2000_chars_and_blocks_are_joined():
    big = "x" * 5000 + "END"
    (_, p), = _result_events(big)
    assert p["text_tail"] == big[-2000:] and p["size"] == 5003
    msg = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t",
           "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}]}}
    assert parse_message(msg)[0][1]["text_tail"] == "a\nb"


def test_agent_test_run_realistic_outputs():
    full = ("============================= test session starts ==============================\n"
            "collected 12 items\n\ntests/test_a.py ....F.\n\n=================================== FAILURES"
            " ===================================\n...\n=========================== short test summary info"
            " ============================\nFAILED tests/test_a.py::test_x - assert 1 == 2\n"
            "========================= 1 failed, 11 passed in 1.23s =========================\n")
    r = _run(full)
    assert (r["passed"], r["failed"], r["errors"], r["skipped"]) == (11, 1, 0, 0)
    assert r["raw_summary"] == "1 failed, 11 passed in 1.23s" and r["tool_use_id"] == "t1"
    assert [t for t, _ in _result_events(full)] == ["tool.result", "agent.test_run"]


def test_agent_test_run_variants():
    r = _run("===== 3 passed, 2 skipped, 1 xfailed, 4 warnings in 0.50s =====")
    assert (r["passed"], r["failed"], r["errors"], r["skipped"]) == (3, 0, 0, 2)
    r = _run("2 errors in 0.31s")
    assert (r["passed"], r["errors"]) == (0, 2)
    r = _run("== 1 error, 4 passed, 2 failed ==")           # no timing, any order
    assert (r["passed"], r["failed"], r["errors"]) == (4, 2, 1)
    r = _run("5 passed in 2.10s (0:00:02)")
    assert r["passed"] == 5
    r = _run("collected 0 items\n\n============================ no tests ran in 0.01s ============================")
    assert r == {"session_id": "s", "tool_use_id": "t1", "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
                 "raw_summary": "no tests ran in 0.01s"}
    r = _run("1 failed in 0.1s\n...rerun...\n7 passed in 0.2s")   # last summary wins
    assert r["passed"] == 7


def test_no_test_run_for_other_output():
    assert _run("ls output\n3 passed the gate, then 2 failed")  is None
    assert _run("Ran 5 tests in 0.1s\nOK") is None
    assert _run("") is None
