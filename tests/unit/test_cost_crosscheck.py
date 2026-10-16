import json
from pathlib import Path

import pytest

from telemetry.crosscheck import cost_crosscheck

FIX = Path(__file__).resolve().parents[2] / "fixtures"
SID = "6a49fe16-9d39-4849-8675-6a887075c797"


def write(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


def api(sid, cost):
    return {"type": "claude_code.api_request", "payload": {"session.id": sid, "cost_usd": cost}}


def res(sid, cost, t="session.result"):
    return {"type": t, "payload": {"session_id": sid, "total_cost_usd": cost}}


def test_recorded_fixtures_agree(tmp_path):
    # otel: real api_request from the raw capture; stream: real result message
    otel = []
    for line in (FIX / "otel" / "cli-1.0.126-haiku-ok.raw.jsonl").read_text().splitlines():
        for rl in json.loads(line)["body"].get("resourceLogs", []):
            for rec in rl["scopeLogs"][0]["logRecords"]:
                a = {x["key"]: x["value"]["stringValue"] for x in rec["attributes"]}
                if rec["body"]["stringValue"] == "claude_code.api_request":
                    otel.append({"type": "claude_code.api_request", "payload": a})
    stream = [json.loads(x) for x in (FIX / "stream" / "cli-1.0.126-haiku-ok.jsonl").read_text().splitlines()]
    out = cost_crosscheck(write(tmp_path / "o.jsonl", otel),
                          write(tmp_path / "s.jsonl", [{"type": "stream.result", "payload": m}
                                                       for m in stream if m["type"] == "result"]))
    assert out[SID]["ok"] and out[SID]["otel_usd"] == pytest.approx(0.0063735) and out[SID]["rel_diff"] == 0


def test_within_and_beyond_one_percent(tmp_path):
    o = write(tmp_path / "o.jsonl", [api("a", "1.0"), api("a", 1.0), api("b", "1.0")])
    s = write(tmp_path / "s.jsonl", [res("a", 2.015), res("b", 1.2)])
    out = cost_crosscheck(o, s)
    assert out["a"]["ok"] and out["a"]["rel_diff"] < 0.01
    assert not out["b"]["ok"] and out["b"]["rel_diff"] == pytest.approx(0.2 / 1.2)


def test_resume_invocations_are_summed(tmp_path):
    o = write(tmp_path / "o.jsonl", [api("a", 0.3), api("a", 0.2)])
    s = write(tmp_path / "s.jsonl", [res("a", 0.3), res("a", 0.2)])
    assert cost_crosscheck(o, s)["a"]["ok"]


def test_parsed_and_raw_results_are_not_double_counted(tmp_path):
    o = write(tmp_path / "o.jsonl", [api("a", 0.5)])
    s = write(tmp_path / "s.jsonl", [res("a", 0.5, "stream.result"), res("a", 0.5)])
    assert cost_crosscheck(o, s)["a"]["stream_usd"] == 0.5


def test_one_sided_sessions_and_bad_values(tmp_path):
    o = write(tmp_path / "o.jsonl", [api("a", "n/a"), api("a", 0.1), api("only_otel", 0.1)])
    s = write(tmp_path / "s.jsonl", [res("a", 0.1), res("only_stream", 0.1), res("c", None)])
    out = cost_crosscheck(o, s)
    assert out["a"]["ok"]
    assert out["only_otel"] == {"otel_usd": 0.1, "stream_usd": None, "rel_diff": None, "ok": False}
    assert out["only_stream"]["otel_usd"] is None and not out["only_stream"]["ok"]
    assert "c" not in out


def test_zero_cost_and_missing_files(tmp_path):
    o = write(tmp_path / "o.jsonl", [api("a", 0)])
    s = write(tmp_path / "s.jsonl", [res("a", 0)])
    assert cost_crosscheck(o, s)["a"]["ok"]
    assert cost_crosscheck(tmp_path / "x", tmp_path / "y") == {}
