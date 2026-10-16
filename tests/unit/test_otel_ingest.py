"""Recorded OTLP captures -> envelope events; dedup and lag (docs/spec.md §6.2)."""
import copy
import json
import time
from pathlib import Path

import pytest

from telemetry.counters import cumulative_cost, cumulative_tokens
from telemetry.events import EventWriter
from telemetry.otlp_receiver import OtlpReceiver

from .test_otlp_receiver import lines, post

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "otel"
SID = "6a49fe16-9d39-4849-8675-6a887075c797"


@pytest.fixture
def rx(tmp_path):
    w = EventWriter(tmp_path / "otel.jsonl", "r1", "otel")
    r = OtlpReceiver(raw_path=tmp_path / "raw.jsonl", events=w)
    r.start()
    yield r, tmp_path
    r.stop()


def replay_real(r):
    for line in (FIX / "cli-1.0.126-haiku-ok.raw.jsonl").read_text().splitlines():
        d = json.loads(line)
        post(r.endpoint + d["path"], d["body"])


def test_real_capture_flattens_with_native_names(rx):
    r, tmp = rx
    replay_real(r)
    ev = lines(tmp / "otel.jsonl")
    types = [e["type"] for e in ev]
    assert "claude_code.user_prompt" in types and "claude_code.api_request" in types
    assert "claude_code.cost.usage" in types and "claude_code.token.usage" in types
    api = next(e for e in ev if e["type"] == "claude_code.api_request")["payload"]
    assert api["session.id"] == SID and api["model"] == "claude-haiku-5-5"
    assert api["cost_usd"] == "0.0063735" and api["cache_read_tokens"] == "21005"
    assert cumulative_cost(tmp / "otel.jsonl") == pytest.approx(0.0063735)
    assert cumulative_tokens(tmp / "otel.jsonl") == 4 + 4 + 21005
    types_by_attr = {e["payload"]["attributes"].get("type") for e in ev if e["type"] == "claude_code.token.usage"}
    assert {"input", "output", "cacheRead"} <= types_by_attr


def test_resent_batch_is_deduplicated_but_kept_raw(rx):
    r, tmp = rx
    replay_real(r)
    n_events, n_raw = len(lines(tmp / "otel.jsonl")), len(lines(tmp / "raw.jsonl"))
    replay_real(r)  # exporter resends the identical batches
    assert len(lines(tmp / "otel.jsonl")) == n_events
    assert len(lines(tmp / "raw.jsonl")) == 2 * n_raw
    assert r.stats["duplicates"] == n_events
    assert r.stats["records"] == n_events
    assert cumulative_cost(tmp / "otel.jsonl") == pytest.approx(0.0063735)


def test_changed_record_or_resource_is_not_a_duplicate(rx):
    r, tmp = rx
    doc = json.loads((FIX / "cli-1.0.126-haiku-ok.raw.jsonl").read_text().splitlines()[1])["body"]
    post(r.endpoint + "/v1/logs", doc)
    other = copy.deepcopy(doc)
    other["resourceLogs"][0]["resource"]["attributes"][0]["value"]["stringValue"] = "different-run"
    post(r.endpoint + "/v1/logs", other)
    third = copy.deepcopy(doc)
    third["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["timeUnixNano"] = "1792175793872000000"
    post(r.endpoint + "/v1/logs", third)
    assert len(lines(tmp / "otel.jsonl")) == 3 and r.stats["duplicates"] == 0


def test_partially_overlapping_batch_keeps_only_new_records(rx):
    r, tmp = rx
    doc = json.loads((FIX / "cli-1.0.126-haiku-ok.raw.jsonl").read_text().splitlines()[1])["body"]
    post(r.endpoint + "/v1/logs", doc)
    bigger = copy.deepcopy(doc)
    recs = bigger["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
    new = copy.deepcopy(recs[0])
    new["timeUnixNano"] = "1792175799000000000"
    recs.append(new)
    post(r.endpoint + "/v1/logs", bigger)
    assert len(lines(tmp / "otel.jsonl")) == 2 and r.stats["duplicates"] == 1


def test_dedup_memory_is_bounded(rx, monkeypatch):
    import telemetry.otlp_receiver as mod
    monkeypatch.setattr(mod, "DEDUP_CAPACITY", 3)
    r, _ = rx
    for i in range(10):
        r._is_duplicate({}, {"i": i})
    assert len(r._seen) == 3
    assert not r._is_duplicate({}, {"i": 0})  # long evicted, counts as new again


def test_lag_is_recorded_per_payload_and_in_stats(rx):
    r, tmp = rx
    now_ns = time.time_ns()
    doc = json.loads((FIX / "cli-1.0.126-haiku-ok.raw.jsonl").read_text().splitlines()[1])["body"]
    doc["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["timeUnixNano"] = str(now_ns - 2_500_000_000)
    post(r.endpoint + "/v1/logs", doc)
    p = lines(tmp / "otel.jsonl")[0]["payload"]
    assert isinstance(p["_otel_lag_ms"], int) and 2500 <= p["_otel_lag_ms"] < 6000
    assert r.stats["last_lag_ms"] == p["_otel_lag_ms"]
    assert r.stats["last_record_mono_ns"] is not None


def test_lag_null_without_timestamp_and_metrics_have_lag(rx):
    r, tmp = rx
    doc = {"resourceLogs": [{"resource": {"attributes": []}, "scopeLogs": [{"logRecords": [
        {"body": {"stringValue": "claude_code.user_prompt"}, "attributes": []}]}]}]}
    post(r.endpoint + "/v1/logs", doc)
    assert lines(tmp / "otel.jsonl")[0]["payload"]["_otel_lag_ms"] is None
    assert r.stats["last_lag_ms"] is None and r.stats["last_record_mono_ns"] is not None
    replay_real(r)
    metric = next(e for e in lines(tmp / "otel.jsonl") if e["type"] == "claude_code.cost.usage")
    assert isinstance(metric["payload"]["_otel_lag_ms"], int)


# SYNTHETIC capture: tool_result / tool_decision / api_error shapes are from the docs, not observed.
def test_synthetic_tool_and_error_events_keep_native_names(rx):
    r, tmp = rx
    doc = json.loads((FIX / "synthetic-tools-errors.json").read_text())
    post(r.endpoint + "/v1/logs", doc)
    ev = lines(tmp / "otel.jsonl")
    assert [e["type"] for e in ev] == ["claude_code.tool_result", "claude_code.tool_decision",
                                       "claude_code.api_error"]
    assert ev[2]["payload"]["status_code"] == "529" and ev[2]["payload"]["session.id"] == "syn-sess-1"
