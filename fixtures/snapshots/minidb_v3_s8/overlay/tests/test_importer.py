"""Stage 8: URL checks against the allow-list, bounded downloads, and NDJSON parsing."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from minidb import importer
from minidb.server import import_api

ALLOW = {"127.0.0.1:8601"}


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:8601/x", "http://127.0.0.1:8602/x", "http://localhost:8601/x", "http://2130706433:8601/x",
    "http://127.1:8601/x", "http://[::1]:8601/x", "http://u@127.0.0.1:8601/x", "http://127.0.0.1/x",
    "http://127.0.0.1:8601\r\nHost: x/", "file:///etc/passwd", ""])
def test_only_exact_allow_list_entries_pass(url):
    with pytest.raises(importer.NotAllowed):
        importer.check_url(url, ALLOW)


def test_allowed_urls_and_bad_types():
    assert importer.check_url("http://127.0.0.1:8601/a/b.ndjson?v=1", ALLOW) == ("127.0.0.1", 8601, "/a/b.ndjson?v=1")
    assert importer.allow_list(" 127.0.0.1:1 ,, 127.0.0.1:2") == {"127.0.0.1:1", "127.0.0.1:2"}
    assert importer.allow_list("") == set()
    with pytest.raises(importer.InvalidData):
        importer.check_url(5, ALLOW)


def test_parse_ndjson_is_all_or_nothing():
    ids, vecs, payloads = importer.parse_ndjson(b'{"id": 1, "vector": [1, 2]}\n\n{"id": 2, "vector": [3, 4], '
                                                b'"payload": {"a": 1}}\n', 2, "l2")
    assert ids == [1, 2] and vecs.shape == (2, 2) and payloads == [None, {"a": 1}]
    for bad in (b'{"id": 1, "vector": [1]}', b'{"id": 1, "vector": [1, 2]}\n{"id": 1, "vector": [1, 2]}',
                b"[1, 2]", b'{"id": 1, "vector": [NaN, 1]}', b"{"):
        with pytest.raises(importer.InvalidData):
            importer.parse_ndjson(bad, 2, "l2")


@pytest.fixture
def source():
    routes = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            status, headers, body = routes[self.path]
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], routes
    srv.shutdown()
    srv.server_close()


def test_download_refuses_redirects_short_bodies_and_large_files(source):
    port, routes = source
    routes["/ok"] = (200, {"Content-Length": "3"}, b"abc")
    routes["/moved"] = (302, {"Location": "http://127.0.0.1:1/", "Content-Length": "0"}, b"")
    routes["/short"] = (200, {"Content-Length": "10", "Connection": "close"}, b"abc")
    routes["/big"] = (200, {"Content-Length": "100"}, b"x" * 100)
    assert importer.download("127.0.0.1", port, "/ok") == b"abc"
    for path in ("/moved", "/short"):
        with pytest.raises(importer.DownloadFailed):
            importer.download("127.0.0.1", port, path, timeout=5)
    with pytest.raises(importer.InvalidData):
        importer.download("127.0.0.1", port, "/big", limit=50)


def test_the_route_is_registered():
    seen = []

    class R:
        def add(self, template, method, fn, **kw):
            seen.append((method, template, kw["policy"]))
    import_api.register(R())
    assert seen == [("POST", "/v1/collections/{name}/import", ("collection", "write"))]
