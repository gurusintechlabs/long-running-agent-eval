"""Client of the shared embedding service (stage 6; ENVIRONMENT.md).

API v2 (stage 8; v1 is retired and answers 410): ``POST {EMBED_URL}/v2/embeddings`` with
``X-Api-Version: 2``, ``Authorization: Bearer {EMBED_API_KEY}`` and ``{"input": [...]}`` answers
``{"model", "data": [{"index", "embedding"}, ...]}``, in any order (matched by ``index``). At most
``BATCH`` texts go in one request. ``503`` and ``429`` are
retried with exponential backoff (``Retry-After`` honoured) until ``DEADLINE_S`` after the client's
request started; any other failure, or the deadline, raises ``EmbedError`` (the API answers 502).

Vectors are used exactly as returned: the service does not normalise them, and nothing here does.
Every text embedded while the server runs is cached, so an identical text is never sent again.
The service key is never logged or put into an error.
"""
from __future__ import annotations

import http.client
import json
import logging
import math
import random
import threading
import time
from collections import OrderedDict
from urllib.parse import urlsplit

log = logging.getLogger("minidb.embed")

BATCH = 64
DEADLINE_S = 30.0
CALL_TIMEOUT_S = 10.0
BACKOFF_S, BACKOFF_MAX_S = 0.2, 4.0
CACHE_MAX = 200_000
PATH = "/v2/embeddings"


class EmbedError(Exception):
    """The service could not embed the texts (the client gets 502)."""


class EmbedClient:
    def __init__(self, url: str, key: str, dim: int = 96) -> None:
        parts = urlsplit(url.rstrip("/"))
        if parts.scheme != "http" or not parts.hostname:
            raise ValueError("EMBED_URL must be an http:// URL")
        self.host, self.port, self.base = parts.hostname, parts.port or 80, parts.path
        self.key, self.dim = key, dim
        self.cache: OrderedDict[str, list[float]] = OrderedDict()
        self.lock = threading.Lock()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """One vector per text, in order."""
        deadline = time.monotonic() + DEADLINE_S
        with self.lock:
            missing = [t for t in dict.fromkeys(texts) if t not in self.cache]
        for i in range(0, len(missing), BATCH):
            batch = missing[i:i + BATCH]
            vecs = self._call(batch, deadline)
            with self.lock:
                for t, v in zip(batch, vecs, strict=True):
                    self.cache[t] = v
                while len(self.cache) > CACHE_MAX:
                    self.cache.popitem(last=False)
        with self.lock:
            out = []
            for t in texts:
                v = self.cache.get(t)
                if v is None:                       # evicted meanwhile (only with a huge request)
                    v = self._call([t], deadline)[0]
                out.append(v)
            return out

    # ------------------------------------------------------------ one batch, with retries

    def _call(self, batch: list[str], deadline: float) -> list[list[float]]:
        attempt = 0
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise EmbedError("the embedding service did not answer in time")
            status, headers, body = self._post({"input": batch}, min(CALL_TIMEOUT_S, left))
            if status == 200:
                return self._parse(body, len(batch))
            if status not in (429, 503) and status is not None:
                log.warning("embedding service answered %s", status)
                raise EmbedError(f"the embedding service answered {status}")
            wait = min(BACKOFF_MAX_S, BACKOFF_S * 2 ** attempt) * (0.5 + random.random() / 2)
            retry_after = (headers or {}).get("retry-after", "")
            if retry_after.strip().isdigit():
                wait = max(wait, float(retry_after))
            if time.monotonic() + wait >= deadline:
                raise EmbedError("the embedding service stayed busy")
            time.sleep(wait)
            attempt += 1

    def _post(self, obj: dict, timeout: float):
        data = json.dumps(obj).encode()
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            conn.request("POST", self.base + PATH, body=data, headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {self.key}", "X-Api-Version": "2"})
            r = conn.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read(64 << 20)
        except (OSError, http.client.HTTPException):
            return None, None, b""                   # connection trouble: retried like a 503
        finally:
            conn.close()

    def _parse(self, body: bytes, n: int) -> list[list[float]]:
        try:
            data = json.loads(body)["data"]
            by_index = {item["index"]: item["embedding"] for item in data}
        except (ValueError, KeyError, TypeError):
            raise EmbedError("the embedding service sent an invalid response") from None
        if len(data) != n or set(by_index) != set(range(n)) or any(isinstance(i, bool) for i in by_index):
            raise EmbedError("the embedding service sent the wrong number of vectors")
        out = []
        for v in (by_index[i] for i in range(n)):
            if (not isinstance(v, list) or len(v) != self.dim
                    or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v)):
                raise EmbedError("the embedding service sent an invalid vector")
            out.append([float(x) for x in v])
        return out
