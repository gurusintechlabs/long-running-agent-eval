from __future__ import annotations

from fastapi.testclient import TestClient

from tests.unit.ui_server.conftest import AUTH, BASE
from ui_server.app import create_app


def test_route_modules_are_discovered(settings, monkeypatch, tmp_path):
    import ui_server.routes as routes
    pkg = tmp_path / "extra"
    pkg.mkdir()
    (pkg / "zz_probe.py").write_text(
        "def register(app, settings):\n"
        "    @app.get('/api/zz-probe')\n"
        "    def probe():\n"
        "        return {'ok': True}\n")
    monkeypatch.setattr(routes, "__path__", [*routes.__path__, str(pkg)])
    with TestClient(create_app(settings), base_url=BASE) as c:
        assert c.get("/api/zz-probe", headers=AUTH).json() == {"ok": True}
        assert c.get("/api/zz-probe").status_code == 401  # guarded like every /api route
