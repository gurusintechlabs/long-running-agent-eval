"""HTTP server for minidb (started by the previous team; only ``/healthz`` exists so far).

    python -m minidb serve --data-dir DIR --port N [--host 127.0.0.1] [--read-only]

Uses the standard library ``ThreadingHTTPServer``. Every request is logged at DEBUG level to stdout
(method, path, headers and body) to make debugging the first clients easier.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger("minidb.server")


class Handler(BaseHTTPRequestHandler):
    server_version = "minidb/0.1"

    def log_message(self, fmt, *args):  # route http.server's access log through logging
        log.info("%s %s", self.address_string(), fmt % args)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _send(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self) -> None:
        body = self._body()
        log.debug("request %s %s headers=%s body=%s", self.command, self.path, dict(self.headers),
                  body.decode("utf-8", "replace"))
        if self.command == "GET" and self.path == "/healthz":
            return self._send(200, {"status": "ok"})
        return self._send(404, {"error": "not found"})

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _handle


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m minidb serve")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--read-only", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s")
    Path(a.data_dir).mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((a.host, a.port), Handler)
    log.info("minidb server listening on %s:%d (data dir %s)", a.host, a.port, a.data_dir)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
