"""UH: HTTP-level hardening, headers on refusals, body size, ingest output, stream slots, draft writes."""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.unit.ui_server.conftest import AUTH, BASE
from ui_server import spec_store as ss

WANT = {"x-content-type-options": "nosniff", "referrer-policy": "no-referrer"}


def check_headers(r, api=True):
    h = {k.lower(): v for k, v in r.headers.items()}
    assert "default-src 'self'" in h.get("content-security-policy", "")
    for k, v in WANT.items():
        assert h.get(k) == v, (k, r.status_code)
    if api:
        assert h.get("cache-control") == "no-store"


def test_security_headers_on_every_refusal(client, settings):
    with TestClient(client.app, base_url=BASE) as anon:
        check_headers(anon.get("/api/runs"))                                           # 401
        check_headers(anon.get("/api/runs", headers={"X-LRAE-Token": "nope"}))         # 401
        check_headers(client.get("/api/runs", headers={"Host": "evil.example"}))       # 403 bad host
        check_headers(client.get("/api/runs", headers={"Origin": "http://evil.example"}))  # 403 bad origin
    check_headers(client.get("/api/health"))
    check_headers(client.get("/api/nothing-here"), api=True)                           # 404
    check_headers(client.get("/"), api=False)


# -- body limit -----------------------------------------------------------------------------------------

def test_large_json_body_is_refused_with_413(client):
    big = b'{"data": {"x": "' + b"a" * (1024 * 1024 + 10) + b'"}}'
    r = client.post("/api/specs/validate", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    check_headers(r)
    for path in ("/api/launch/preview", "/api/launch", "/api/review/decision", "/api/specs/save", "/api/clean"):
        assert client.post(path, content=big, headers={"Content-Type": "application/json"}).status_code == 413, path


def test_chunked_upload_without_content_length_is_bounded(client):
    def chunks():
        for _ in range(40):
            yield b"a" * 65536

    r = client.post("/api/specs/validate", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_normal_bodies_and_gets_are_unaffected(client):
    assert client.post("/api/specs/validate", json={"data": {}}).status_code == 200
    assert client.get("/api/runs").status_code == 200
    ok = b'{"data": {"x": "' + b"a" * 200_000 + b'"}}'
    assert client.post("/api/specs/validate", content=ok, headers={"Content-Type": "application/json"}).status_code == 200


# -- ingest output --------------------------------------------------------------------------------------

def test_ingest_output_is_scrubbed(client, settings, monkeypatch):
    home = str(Path.home())
    out = f"error in {settings.repo_root}/runner/x.py and {home}/secret/stuff"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout=out, stderr=""))
    r = client.post("/api/ingest")
    body = r.json()
    assert str(settings.repo_root) not in body["output"] and home not in body["output"]
    assert "<repo>" in body["output"] and "~" in body["output"]


# -- stream slots ---------------------------------------------------------------------------------------

def test_stream_slots_are_taken_before_the_slow_start(client, runs_dir, monkeypatch):
    from tests.unit.analysis.synth import make_run
    from ui_server import feed_reader
    from ui_server.routes import live
    rid = make_run(runs_dir, experiment="exp-s", repeat=0, n_cp=1)
    monkeypatch.setattr(live, "MAX_STREAMS", 2)
    real = feed_reader.start_offsets

    def slow(*a, **k):
        time.sleep(0.6)
        return real(*a, **k)

    monkeypatch.setattr(feed_reader, "start_offsets", slow)
    codes = []

    def go():
        with TestClient(client.app, base_url=BASE) as c:
            codes.append(c.get(f"/api/runs/{rid}/stream", params={"follow": "false", "from": "start"},
                               headers=AUTH).status_code)

    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert sorted(codes).count(200) <= 2 + 0 and codes.count(429) >= 3, codes


def test_stream_slot_is_released_after_each_stream(client, runs_dir, monkeypatch):
    from tests.unit.analysis.synth import make_run
    from ui_server.routes import live
    rid = make_run(runs_dir, experiment="exp-s", repeat=0, n_cp=1)
    monkeypatch.setattr(live, "MAX_STREAMS", 1)
    for _ in range(4):
        assert client.get(f"/api/runs/{rid}/stream", params={"follow": "false", "from": "start"}).status_code == 200
    assert client.get(f"/api/runs/{rid}/stream", params={"from": "bogus"}).status_code == 400
    assert client.get(f"/api/runs/{rid}/stream", params={"follow": "false"}).status_code == 200


# -- draft writes ---------------------------------------------------------------------------------------

def test_atomic_write_never_replaces_a_file_created_in_the_race_window(tmp_path, monkeypatch):
    d = tmp_path / "drafts"
    d.mkdir()
    real = ss.secrets.token_hex

    def racing(n):
        (d / "mine.yaml").write_text("someone else's draft\n")   # appears after the exists() check
        return real(n)

    monkeypatch.setattr(ss.secrets, "token_hex", racing)
    with pytest.raises(ss.StoreError) as ei:
        ss._atomic_write(d, "mine", "new text\n", overwrite=False)
    assert ei.value.status == 409
    assert (d / "mine.yaml").read_text() == "someone else's draft\n"
    assert [p.name for p in d.iterdir()] == ["mine.yaml"]          # no temp file left behind


def test_atomic_write_overwrite_true_still_replaces(tmp_path):
    d = tmp_path / "drafts"
    d.mkdir()
    (d / "mine.yaml").write_text("old\n")
    ss._atomic_write(d, "mine", "new\n", overwrite=True)
    assert (d / "mine.yaml").read_text() == "new\n"
    ss._atomic_write(d, "fresh", "x\n", overwrite=False)
    assert (d / "fresh.yaml").read_text() == "x\n"
