"""Bulk import of points from a URL (stage 8).

* Sources: ``http://<host>:<port>/<path>`` only, with ``host:port`` written exactly as an entry of
  ``MINIDB_IMPORT_ALLOW`` (comma-separated; empty or unset allows nothing). The check is textual and
  happens before any connection; the connection goes to the allow-list entry itself, so no other
  spelling of an address, no userinfo and no redirect can reach anything else.
* Download: one ``GET``, no redirects (a ``3xx`` is a failed download), at most ``MAX_BYTES``, and
  ``TIMEOUT_S`` for the whole transfer.
* Data: NDJSON, one point object per line (as in an upsert request); blank lines are ignored. The
  file is validated as a whole (at most ``MAX_POINTS``, no duplicate ids) before anything is written.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

import numpy as np

from minidb.collection import points as pv

ALLOW_ENV = "MINIDB_IMPORT_ALLOW"
MAX_POINTS = 100_000
MAX_BYTES = 64 << 20
TIMEOUT_S = 60.0
_NETLOC = re.compile(r"[A-Za-z0-9.-]+:[0-9]{1,5}")


class NotAllowed(Exception):
    """The URL may not be fetched (403)."""


class InvalidData(ValueError):
    """The request or the downloaded file is invalid (400)."""


class DownloadFailed(Exception):
    """The source could not be read completely (502)."""


def allow_list(raw: str | None = None) -> set[str]:
    raw = os.environ.get(ALLOW_ENV, "") if raw is None else raw
    return {e.strip() for e in raw.split(",") if e.strip()}


def check_url(url: Any, allowed: set[str]) -> tuple[str, int, str]:
    """``(host, port, path)`` of an allowed URL; NotAllowed or InvalidData otherwise."""
    if not isinstance(url, str):
        raise InvalidData("'url' must be a string")
    if any(ord(ch) < 33 or ord(ch) == 127 for ch in url):
        raise NotAllowed("this URL is not allowed")
    try:
        parts = urlsplit(url)
    except ValueError:
        raise NotAllowed("this URL is not allowed") from None
    netloc = parts.netloc
    if parts.scheme != "http" or not _NETLOC.fullmatch(netloc) or netloc not in allowed:
        raise NotAllowed("this URL is not on the import allow-list")
    host, port = netloc.rsplit(":", 1)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return host, int(port), path


def download(host: str, port: int, path: str, *, timeout: float = TIMEOUT_S, limit: int = MAX_BYTES) -> bytes:
    deadline = time.monotonic() + timeout
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path, headers={"Accept": "application/x-ndjson, */*"})
        r = conn.getresponse()
        if r.status != 200:
            raise DownloadFailed(f"the source answered {r.status}")
        expected = r.length                      # None without Content-Length (read until close)
        if expected is not None and expected > limit:
            raise InvalidData(f"the file is larger than {limit} bytes")
        chunks, got = [], 0
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise DownloadFailed("the download timed out")
            if conn.sock is not None:
                conn.sock.settimeout(left)
            chunk = r.read1(1 << 16)
            if not chunk:
                break
            got += len(chunk)
            if got > limit:
                raise InvalidData(f"the file is larger than {limit} bytes")
            chunks.append(chunk)
        if expected is not None and got != expected:
            raise DownloadFailed("the source closed the connection before the end of the file")
        return b"".join(chunks)
    except (OSError, http.client.HTTPException) as e:
        raise DownloadFailed("the download failed") from e
    finally:
        conn.close()


def parse_ndjson(data: bytes, dim: int, metric: str) -> tuple[list, np.ndarray, list]:
    """``(ids, vectors, payloads)`` of every point in the file; InvalidData names the first bad line."""
    ids, vecs, payloads, seen = [], [], [], set()
    for no, line in enumerate(data.split(b"\n"), 1):
        line = line.strip()
        if not line:
            continue
        if len(ids) >= MAX_POINTS:
            raise InvalidData(f"more than {MAX_POINTS} points")
        try:
            p = json.loads(line.decode("utf-8"), parse_constant=_no_constant)
            if not isinstance(p, dict) or "id" not in p or "vector" not in p:
                raise pv.Invalid("each line must be a point object with 'id' and 'vector'")
            pid = pv.parse_id(p["id"])
            vec = pv.parse_vector(p["vector"], dim, metric)
            payload = pv.parse_payload(p.get("payload"))
        except (ValueError, UnicodeDecodeError, RecursionError, pv.Invalid) as e:
            raise InvalidData(f"line {no}: {e}") from None
        if pid in seen:
            raise InvalidData(f"line {no}: duplicate id")
        seen.add(pid)
        ids.append(pid)
        vecs.append(vec)
        payloads.append(payload)
    arr = np.stack(vecs) if vecs else np.zeros((0, dim), np.float32)
    return ids, arr, payloads


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")
