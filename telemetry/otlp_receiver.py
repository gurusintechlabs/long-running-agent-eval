"""Local OTLP/HTTP receiver for Claude Code's OpenTelemetry export (docs/spec.md §6.2, D-2).

A stdlib ``ThreadingHTTPServer`` bound to loopback. It writes every raw payload to a raw JSONL
file and flattens logs and metrics into envelope events, keeping the CLI's native names.
Protobuf bodies are recorded as ``otel.unparsed`` (Phase 1 verifies http/json is supported).
"""
from __future__ import annotations

import base64
import gzip
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from telemetry.events import EventWriter, redact, utc_now_iso


def _any_value(v: dict):
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "arrayValue" in v:
        return [_any_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return decode_attrs(v["kvlistValue"].get("values", []))
    return None


def decode_attrs(attrs: list[dict] | None) -> dict:
    return {a["key"]: _any_value(a.get("value", {})) for a in attrs or []}


def _ts(nano) -> str | None:
    if not nano:
        return None
    try:
        dt = datetime.fromtimestamp(int(nano) / 1e9, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class OtlpReceiver:
    host = "127.0.0.1"

    def __init__(self, raw_path: Path | str, events: EventWriter, port: int = 0):
        self.raw_path = Path(raw_path)
        self.raw_path.parent.mkdir(parents=True, exist_ok=True)
        self.events = events
        self._raw_lock = threading.Lock()
        self.stats = {"records": 0, "requests": 0, "last_receive_mono_ns": None}
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def do_POST(self):
                receiver._handle(self)

        self._server = ThreadingHTTPServer((self.host, port), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread: threading.Thread | None = None

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True,
                                        name="otlp-receiver")
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=5)

    # -- request handling -----------------------------------------------------------------

    def _reply(self, h: BaseHTTPRequestHandler, code: int, body: bytes = b"{}") -> None:
        h.send_response(code)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)

    def _write_raw(self, record: dict) -> None:
        with self._raw_lock, open(self.raw_path, "a") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")

    def _handle(self, h: BaseHTTPRequestHandler) -> None:
        path = h.path.split("?")[0]
        if path not in ("/v1/logs", "/v1/metrics", "/v1/traces"):
            return self._reply(h, 404, b'{"error":"not found"}')
        length = int(h.headers.get("Content-Length") or 0)
        body = h.rfile.read(length)
        self.stats["requests"] += 1
        self.stats["last_receive_mono_ns"] = time.monotonic_ns()
        recv_ts = utc_now_iso()
        ctype = (h.headers.get("Content-Type") or "").lower()
        try:
            if h.headers.get("Content-Encoding", "").lower() == "gzip":
                body = gzip.decompress(body)
            if "json" not in ctype:
                self._write_raw({"path": path, "recv_ts": recv_ts, "content_type": ctype,
                                 "body_b64": base64.b64encode(body).decode()})
                self.events.emit("otel.unparsed", {"path": path, "bytes": len(body),
                                                   "content_type": ctype}, ts=recv_ts)
                return self._reply(h, 200)
            doc = json.loads(body)
        except (OSError, ValueError, EOFError) as exc:
            self.events.emit("otel.parse_error", {"path": path, "error": str(exc)[:200]}, ts=recv_ts)
            return self._reply(h, 400, b'{"error":"bad request"}')
        self._write_raw({"path": path, "recv_ts": recv_ts, "body": redact(doc)})
        if path == "/v1/logs":
            self._flatten_logs(doc, recv_ts)
        elif path == "/v1/metrics":
            self._flatten_metrics(doc, recv_ts)
        self._reply(h, 200)

    def _flatten_logs(self, doc: dict, recv_ts: str) -> None:
        for rl in doc.get("resourceLogs", []):
            resource = decode_attrs(rl.get("resource", {}).get("attributes"))
            for sl in rl.get("scopeLogs", []):
                for rec in sl.get("logRecords", []):
                    attrs = decode_attrs(rec.get("attributes"))
                    body = _any_value(rec.get("body", {})) if rec.get("body") else None
                    etype = attrs.get("event.name") or (body if isinstance(body, str) else "otel.log")
                    payload = {**attrs, "_signal": "log", "_resource": resource, "_recv_ts": recv_ts}
                    if body is not None and body != etype:
                        payload["_body"] = body
                    self.events.emit(etype, payload, ts=_ts(rec.get("timeUnixNano")) or recv_ts)
                    self.stats["records"] += 1

    def _flatten_metrics(self, doc: dict, recv_ts: str) -> None:
        for rm in doc.get("resourceMetrics", []):
            resource = decode_attrs(rm.get("resource", {}).get("attributes"))
            for sm in rm.get("scopeMetrics", []):
                for m in sm.get("metrics", []):
                    kind = next((k for k in ("sum", "gauge") if k in m), None)
                    if kind is None:
                        continue
                    for dp in m[kind].get("dataPoints", []):
                        value = dp.get("asInt", dp.get("asDouble"))
                        if value is not None:
                            value = int(value) if "asInt" in dp else float(value)
                        payload = {"name": m["name"], "value": value, "unit": m.get("unit", ""),
                                   "attributes": decode_attrs(dp.get("attributes")), "_kind": kind,
                                   "_signal": "metric", "_resource": resource, "_recv_ts": recv_ts}
                        self.events.emit(m["name"], payload,
                                         ts=_ts(dp.get("timeUnixNano")) or recv_ts)
                        self.stats["records"] += 1
