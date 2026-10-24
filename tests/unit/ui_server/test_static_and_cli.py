"""Static SPA serving and the ``lrae ui`` entry point."""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.unit.ui_server.conftest import BASE
from ui_server.app import create_app


def test_placeholder_when_not_built(client):
    r = client.get("/")
    assert r.status_code == 200 and "not been built" in r.text


def test_serves_built_bundle_and_spa_fallback(settings, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>lrae</title>")
    (dist / "assets" / "a.js").write_text("console.log(1)")
    s = settings.__class__(**{**settings.__dict__, "web_dist": dist})
    with TestClient(create_app(s), base_url=BASE) as c:
        assert "<title>lrae</title>" in c.get("/").text
        assert c.get("/assets/a.js").status_code == 200
        assert "<title>lrae</title>" in c.get("/runs/some-run").text  # client-side route
        assert c.get("/api/nope", headers={"X-LRAE-Token": s.token}).status_code == 404


def test_static_cannot_escape_dist(settings, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("ok")
    (tmp_path / "secret.txt").write_text("secret")
    s = settings.__class__(**{**settings.__dict__, "web_dist": dist})
    with TestClient(create_app(s), base_url=BASE) as c:
        for p in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
            assert "secret" not in c.get(p).text


def test_cli_registers_ui_subcommand():
    from runner.cli import build_parser
    a = build_parser().parse_args(["ui", "--port", "9001", "--no-open"])
    assert a.cmd == "ui" and a.port == 9001


def test_cli_module_imports_without_server_deps():
    import importlib
    import sys
    sys.modules.pop("ui_server.cli", None)
    m = importlib.import_module("ui_server.cli")
    src = open(m.__file__).read()
    assert "import fastapi" not in src.split("def ", 1)[0] and "import uvicorn" not in src.split("def ", 1)[0]


def test_token_is_random_and_urlsafe():
    from ui_server.cli import new_token
    a, b = new_token(), new_token()
    assert a != b and len(a) >= 32 and all(c.isalnum() or c in "-_" for c in a)


def test_launch_url_uses_fragment():
    from ui_server.cli import launch_url
    u = launch_url(8765, "tok")
    assert u == "http://127.0.0.1:8765/#token=tok"
