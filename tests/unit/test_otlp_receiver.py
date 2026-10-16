import gzip
import json
import socket
import urllib.error
import urllib.request

import pytest

from telemetry.events import EventWriter
from telemetry.otlp_receiver import OtlpReceiver, decode_attrs


def post(url, body, headers=None, raw=False):
    data = body if raw else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                           **(headers or {})}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read()


@pytest.fixture
def rx(tmp_path):
    w = EventWriter(tmp_path / "otel.jsonl", "r1", "otel")
    r = OtlpReceiver(raw_path=tmp_path / "raw.jsonl", events=w)
    r.start()
    yield r, tmp_path
    r.stop()


def lines(p):
    return [json.loads(x) for x in p.read_text().splitlines()]


LOGS = {"resourceLogs": [{"resource": {"attributes": [
    {"key": "lrae.run_id", "value": {"stringValue": "r1"}}]},
    "scopeLogs": [{"logRecords": [{
        "timeUnixNano": "1767225600000000000",
        "body": {"stringValue": "claude_code.api_request"},
        "attributes": [
            {"key": "event.name", "value": {"stringValue": "claude_code.api_request"}},
            {"key": "model", "value": {"stringValue": "claude-opus-5-5"}},
            {"key": "cost_usd", "value": {"doubleValue": 0.0123}},
            {"key": "input_tokens", "value": {"intValue": "1500"}},
            {"key": "ok", "value": {"boolValue": True}}]}]}]}]}

METRICS = {"resourceMetrics": [{"resource": {"attributes": []}, "scopeMetrics": [{"metrics": [
    {"name": "claude_code.token.usage", "unit": "tokens", "sum": {"dataPoints": [
        {"timeUnixNano": "1767225601000000000", "asInt": "42",
         "attributes": [{"key": "type", "value": {"stringValue": "input"}}]}]}},
    {"name": "claude_code.cost.usage", "unit": "USD", "gauge": {"dataPoints": [
        {"timeUnixNano": "1767225601000000000", "asDouble": 0.5, "attributes": []}]}}]}]}]}


def test_binds_loopback_only(rx):
    r, _ = rx
    assert r.host == "127.0.0.1"
    assert r.endpoint == f"http://127.0.0.1:{r.port}"
    # not reachable via a non-loopback interface address
    try:
        other = socket.gethostbyname(socket.gethostname())
    except OSError:
        pytest.skip("no resolvable hostname")
    if other.startswith("127."):
        pytest.skip("hostname resolves to loopback")
    s = socket.socket()
    s.settimeout(1)
    assert s.connect_ex((other, r.port)) != 0
    s.close()


def test_logs_are_written_raw_and_flattened(rx):
    r, tmp = rx
    status, _ = post(r.endpoint + "/v1/logs", LOGS)
    assert status == 200
    assert lines(tmp / "raw.jsonl")[0]["path"] == "/v1/logs"
    ev = lines(tmp / "otel.jsonl")
    assert len(ev) == 1
    e = ev[0]
    assert e["type"] == "claude_code.api_request" and e["source"] == "otel"
    assert e["ts"].startswith("2026-01-01T00:00:00")
    p = e["payload"]
    assert p["model"] == "claude-opus-5-5" and p["cost_usd"] == 0.0123
    assert p["input_tokens"] == 1500 and p["ok"] is True
    assert p["_resource"]["lrae.run_id"] == "r1" and p["_signal"] == "log"


def test_metrics_flattened_per_datapoint(rx):
    r, tmp = rx
    post(r.endpoint + "/v1/metrics", METRICS)
    ev = lines(tmp / "otel.jsonl")
    assert [e["type"] for e in ev] == ["claude_code.token.usage", "claude_code.cost.usage"]
    assert ev[0]["payload"]["value"] == 42 and ev[0]["payload"]["attributes"] == {"type": "input"}
    assert ev[0]["payload"]["_signal"] == "metric" and ev[0]["payload"]["unit"] == "tokens"
    assert ev[1]["payload"]["value"] == 0.5


def test_gzip_body_accepted(rx):
    r, tmp = rx
    post(r.endpoint + "/v1/logs", gzip.compress(json.dumps(LOGS).encode()),
         headers={"Content-Encoding": "gzip"}, raw=True)
    assert len(lines(tmp / "otel.jsonl")) == 1


def test_traces_stored_raw_only(rx):
    r, tmp = rx
    status, _ = post(r.endpoint + "/v1/traces", {"resourceSpans": []})
    assert status == 200
    assert not (tmp / "otel.jsonl").read_text()
    assert lines(tmp / "raw.jsonl")[0]["path"] == "/v1/traces"


def test_malformed_body_400_and_receiver_survives(rx):
    r, tmp = rx
    with pytest.raises(urllib.error.HTTPError) as ei:
        post(r.endpoint + "/v1/logs", b"{not json", raw=True)
    assert ei.value.code == 400
    ev = lines(tmp / "otel.jsonl")
    assert ev[0]["type"] == "otel.parse_error"
    post(r.endpoint + "/v1/logs", LOGS)  # still alive
    assert lines(tmp / "otel.jsonl")[-1]["type"] == "claude_code.api_request"


def test_protobuf_is_recorded_as_unparsed(rx):
    r, tmp = rx
    post(r.endpoint + "/v1/logs", b"\x0a\x02\x08\x01", headers={"Content-Type": "application/x-protobuf"},
         raw=True)
    assert lines(tmp / "otel.jsonl")[0]["type"] == "otel.unparsed"


def test_unknown_path_404(rx):
    r, _ = rx
    with pytest.raises(urllib.error.HTTPError) as ei:
        post(r.endpoint + "/nope", {})
    assert ei.value.code == 404


def test_stats_track_last_receive(rx):
    r, _ = rx
    assert r.stats["records"] == 0 and r.stats["last_receive_mono_ns"] is None
    post(r.endpoint + "/v1/logs", LOGS)
    assert r.stats["records"] == 1 and r.stats["last_receive_mono_ns"] is not None


def test_decode_attrs_types():
    attrs = [{"key": "a", "value": {"stringValue": "s"}}, {"key": "b", "value": {"intValue": "7"}},
             {"key": "c", "value": {"arrayValue": {"values": [{"intValue": "1"}, {"stringValue": "x"}]}}},
             {"key": "d", "value": {"kvlistValue": {"values": [
                 {"key": "k", "value": {"boolValue": False}}]}}}]
    assert decode_attrs(attrs) == {"a": "s", "b": 7, "c": [1, "x"], "d": {"k": False}}


# The Claude Code CLI's OTel exporter (OTel-OTLP-Exporter-JavaScript) sends bodies chunked, with no
# Content-Length (observed live against CLI 1.0.126).

def post_chunked(rx, path, payload, gz=False):
    import http.client
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if gz:
        body = gzip.compress(body)
        headers["Content-Encoding"] = "gzip"
    conn = http.client.HTTPConnection(rx.host, rx.port, timeout=5)
    pieces = [body[i:i + 50] for i in range(0, len(body), 50)]  # many small chunks
    conn.request("POST", path, body=iter(pieces), headers=headers, encode_chunked=True)
    resp = conn.getresponse()
    status = resp.status
    resp.read()
    conn.close()
    return status


def test_chunked_body_is_decoded(rx):
    r, tmp = rx
    assert post_chunked(r, "/v1/logs", LOGS) == 200
    ev = lines(tmp / "otel.jsonl")
    assert [e["type"] for e in ev] == ["claude_code.api_request"]
    assert ev[0]["payload"]["input_tokens"] == 1500


def test_chunked_metrics_and_gzip(rx):
    r, tmp = rx
    assert post_chunked(r, "/v1/metrics", METRICS) == 200
    assert post_chunked(r, "/v1/logs", LOGS, gz=True) == 200
    assert [e["type"] for e in lines(tmp / "otel.jsonl")] == [
        "claude_code.token.usage", "claude_code.cost.usage", "claude_code.api_request"]


def test_truncated_chunked_body_is_400_not_a_hang(rx):
    r, tmp = rx
    s = socket.create_connection((r.host, r.port), timeout=3)
    s.sendall(b"POST /v1/logs HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
              b"Transfer-Encoding: chunked\r\n\r\nff\r\n{\"resourceLogs\":")
    s.shutdown(socket.SHUT_WR)  # peer closes mid-chunk
    data = s.recv(4096)
    s.close()
    assert b"400" in data.split(b"\r\n")[0]
    assert lines(tmp / "otel.jsonl")[-1]["type"] == "otel.parse_error"


# --- shapes observed live from Claude Code CLI 1.0.126 ---------------------------------------

SENSITIVE = {"user.email": "someone@example.com", "user.account_uuid": "9583a392-ed68-4723-be22",
             "user.id": "2abfd159d971cc63", "organization.id": "522f75bc-1158-47d8"}


def real_log(attrs=None):
    base = [{"key": "event.name", "value": {"stringValue": "api_request"}},
            {"key": "model", "value": {"stringValue": "claude-haiku-5-5"}},
            {"key": "cost_usd", "value": {"stringValue": "0.0063735"}},
            {"key": "input_tokens", "value": {"stringValue": "4"}}]
    base += [{"key": k, "value": {"stringValue": v}} for k, v in {**SENSITIVE, **(attrs or {})}.items()]
    return {"resourceLogs": [{"resource": {"attributes": [
        {"key": "service.name", "value": {"stringValue": "claude-code"}}]},
        "scopeLogs": [{"logRecords": [{"timeUnixNano": "1767225600000000000",
                                       "body": {"stringValue": "claude_code.api_request"},
                                       "attributes": base}]}]}]}


def test_type_uses_prefixed_body_name_not_bare_event_name(rx):
    r, tmp = rx
    post(r.endpoint + "/v1/logs", real_log())
    e = lines(tmp / "otel.jsonl")[0]
    assert e["type"] == "claude_code.api_request"
    assert e["payload"]["event.name"] == "api_request" and e["payload"]["cost_usd"] == "0.0063735"


def test_account_identifiers_never_reach_disk(rx):
    r, tmp = rx
    post(r.endpoint + "/v1/logs", real_log())
    post(r.endpoint + "/v1/metrics", {"resourceMetrics": [{"resource": {"attributes": []}, "scopeMetrics": [
        {"metrics": [{"name": "claude_code.cost.usage", "unit": "USD", "sum": {"dataPoints": [
            {"asDouble": 0.5, "attributes": [{"key": k, "value": {"stringValue": v}}
                                             for k, v in SENSITIVE.items()]}]}}]}]}]})
    for f in ("raw.jsonl", "otel.jsonl"):
        text = (tmp / f).read_text()
        for value in SENSITIVE.values():
            assert value not in text, (f, value)
    assert "[REDACTED]" in (tmp / "otel.jsonl").read_text()
    assert lines(tmp / "otel.jsonl")[0]["payload"]["model"] == "claude-haiku-5-5"  # non-sensitive intact


def test_unparseable_body_is_kept_raw_for_debugging(rx):
    r, tmp = rx
    with pytest.raises(urllib.error.HTTPError):
        post(r.endpoint + "/v1/logs", b"{not json", raw=True)
    raw = lines(tmp / "raw.jsonl")
    assert raw[0]["path"] == "/v1/logs" and raw[0]["body_b64"]
