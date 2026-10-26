"""Stage 6: the embedding client (batching, retries, cache) and text collections over HTTP."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

from minidb import embed as embed_mod
from minidb.collection import points as pv
from minidb.embed import EmbedClient, EmbedError
from minidb.server import text_api
from tests.server_util import Proc


class Fake:
    """``plan``: statuses to answer before succeeding (e.g. [503, 429])."""

    def __init__(self, plan=()):
        self.plan, self.calls = list(plan), []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                texts = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["texts"]
                outer.calls.append(texts)
                code = outer.plan.pop(0) if outer.plan else 200
                body = json.dumps({"embeddings": [[float(len(t))] * 96 for t in texts]} if code == 200 else {}).encode()
                self.send_response(code)
                if code == 429:
                    self.send_header("Retry-After", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake():
    f = Fake()
    yield f
    f.close()


def test_batches_cache_and_order(fake):
    c = EmbedClient(fake.url, "k")
    texts = [f"t{i}" * (i % 3 + 1) for i in range(130)]
    out = c.embed(texts + texts[:5])
    assert [v[0] for v in out] == [float(len(t)) for t in texts + texts[:5]]
    assert max(len(b) for b in fake.calls) <= 64 and sum(len(b) for b in fake.calls) == len(set(texts))
    n = len(fake.calls)
    c.embed(texts[:10])
    assert len(fake.calls) == n


def test_retries_then_gives_up(monkeypatch):
    f = Fake([503, 429, 503])
    try:
        assert EmbedClient(f.url, "k").embed(["a"])[0][0] == 1.0 and len(f.calls) == 4
    finally:
        f.close()
    monkeypatch.setattr(embed_mod, "DEADLINE_S", 0.5)
    f = Fake([503] * 100)
    try:
        with pytest.raises(EmbedError):
            EmbedClient(f.url, "k").embed(["a"])
    finally:
        f.close()
    f = Fake([401])
    try:
        with pytest.raises(EmbedError):
            EmbedClient(f.url, "k").embed(["a"])
        assert len(f.calls) == 1
    finally:
        f.close()


def test_text_validation():
    assert pv.parse_embedding({"embedding": "service"}, 96) == "service" and pv.parse_embedding({}, 3) is None
    for body, dim in (({"embedding": "service"}, 3), ({"embedding": "x"}, 96)):
        with pytest.raises(pv.Invalid):
            pv.parse_embedding(body, dim)
    with pytest.raises(pv.Invalid):
        pv.parse_text_points({"points": [{"id": 1, "text": ""}]})
    assert text_api.TEXT_MAX_BODY > 8 << 20


def test_text_collection_over_http(tmp_path, fake):
    srv = Proc(tmp_path / "data", env={"EMBED_URL": fake.url, "EMBED_API_KEY": "k"}).wait_ready()
    try:
        assert srv.request("PUT", "/v1/collections/t", {"dim": 96, "metric": "dot", "embedding": "service"})[0] == 201
        assert srv.request("PUT", "/v1/collections/t/points/text", {"points": [{"id": 1, "text": "ab"}, {"id": 2, "text": "abc"}]})[0] == 200
        status, body, _ = srv.request("POST", "/v1/collections/t/search_text", {"text": "a", "k": 2})
        assert status == 200 and [r["id"] for r in body["results"]] == [2, 1]
        assert body["results"][0]["score"] == pytest.approx(float(np.dot([3.0] * 96, [1.0] * 96)))
        assert srv.request("GET", "/v1/collections/t/points/1")[1]["text"] == "ab"
    finally:
        srv.stop()
