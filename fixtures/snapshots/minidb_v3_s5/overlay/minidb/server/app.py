"""HTTP server for minidb.

    python -m minidb serve --data-dir DIR --port N [--host 127.0.0.1] [--read-only]

Exit status: 0 after a clean shutdown (SIGTERM/SIGINT), 2 for a bad configuration (no admin key, an
unusable data dir), 3 when another process holds the data dir's writer lock. The admin key comes from
``MINIDB_ADMIN_KEY``; ``MINIDB_RATE_LIMIT`` sets requests per second per key (default 50). Requests are served by a thread each (``ThreadingHTTPServer``); on shutdown the
server stops accepting, lets the requests in flight finish (up to ``DRAIN_S``), then exits.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from http.server import ThreadingHTTPServer

from minidb.datadir import DataDir, DataDirError, LockBusy
from minidb.server import api
from minidb.server.handler import Handler, configure_logging
from minidb.server.ratelimit import RateLimiter
from minidb.service import Service

log = logging.getLogger("minidb.server")
DRAIN_S = 4.0
DEFAULT_RATE_LIMIT = 50


class Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 128

    def __init__(self, addr, service: Service, rate_limit: int) -> None:
        super().__init__(addr, Handler)
        self.service = service
        self.limiter = RateLimiter(rate_limit)
        self.router = api.router()
        self.stopping = False
        self._inflight = 0
        self._cond = threading.Condition()

    def request_started(self) -> None:
        with self._cond:
            self._inflight += 1

    def request_finished(self) -> None:
        with self._cond:
            self._inflight -= 1
            self._cond.notify_all()

    def drain(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._inflight:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._cond.wait(left)
        return True


def _fail(msg: str, status: int) -> int:
    print(f"minidb serve: {msg}", file=sys.stderr, flush=True)
    return status


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m minidb serve")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--read-only", action="store_true")
    a = ap.parse_args(argv)
    admin_key = os.environ.get("MINIDB_ADMIN_KEY", "")
    if not admin_key.strip():
        return _fail("MINIDB_ADMIN_KEY is not set; refusing to start", 2)
    raw_rate = os.environ.get("MINIDB_RATE_LIMIT", "").strip() or str(DEFAULT_RATE_LIMIT)
    if not raw_rate.isdigit() or int(raw_rate) < 1:
        return _fail("MINIDB_RATE_LIMIT must be a positive integer (requests per second per key)", 2)
    configure_logging()
    dd = DataDir(a.data_dir, read_only=a.read_only)
    try:
        dd.open()
    except LockBusy as e:
        return _fail(str(e), 3)
    except (DataDirError, OSError) as e:
        return _fail(f"cannot use the data dir: {e}", 2)
    try:
        try:
            service = Service(dd, admin_key)
        except (OSError, ValueError) as e:
            return _fail(f"cannot open the data in the data dir: {e}", 2)
        try:
            httpd = Server((a.host, a.port), service, int(raw_rate))
        except OSError as e:
            service.close()
            return _fail(f"cannot listen on {a.host}:{a.port}: {e.strerror or e}", 1)
        return _serve(httpd, service)
    finally:
        dd.close()


def _serve(httpd: Server, service: Service) -> int:
    def stop(signum, frame) -> None:
        if not httpd.stopping:
            httpd.stopping = True
            threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("minidb server listening on %s:%d", *httpd.server_address[:2])
    try:
        httpd.serve_forever(poll_interval=0.1)
    finally:
        httpd.server_close()
        if not httpd.drain(DRAIN_S):
            log.warning("requests still running at shutdown")
        service.close()
    log.info("minidb server stopped")
    return 0
