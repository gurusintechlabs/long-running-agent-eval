"""U7 reports API: list, allowlisted serving (UI-4), sandbox CSP, rebuild via the real CLI (UI-7)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from analysis.ingest import ingest
from tests.unit.analysis.synth import hazard, make_run
from tests.unit.ui_server.conftest import AUTH, BASE
from ui_server.app import create_app
from ui_server.routes import reports

HTML = "<!doctype html><title>d</title><h1>dash</h1><img src=\"figures/survival.png\">"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
PDF = b"%PDF-1.4\n%fake\n"


@pytest.fixture
def exp(runs_dir):
    """An ingested experiment, with a report folder holding a dashboard, a PDF and two figures."""
    make_run(runs_dir, experiment="exp-r", config="A", repeat=1, n_cp=3, hazards=[hazard()])
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    d = runs_dir / "reports" / "exp-r"
    (d / "figures").mkdir(parents=True)
    (d / "dashboard.html").write_text(HTML)
    (d / "report.pdf").write_bytes(PDF)
    (d / "report.html").write_text("<p>intermediate</p>")
    (d / "figures" / "survival.png").write_bytes(PNG)
    (d / "figures" / "cost.png").write_bytes(PNG)
    (d / "figures" / "notes.txt").write_text("not served")
    return "exp-r"


def test_list_reports(client, exp):
    j = client.get("/api/reports").json()
    e = next(x for x in j["experiments"] if x["experiment_id"] == exp)
    assert e["has_reports"] and e["in_store"]
    assert e["dashboard"]["bytes"] == len(HTML) and e["pdf"]["bytes"] == len(PDF)
    assert [f["name"] for f in e["figures"]] == ["figures/cost.png", "figures/survival.png"]
    assert j["ingest"]["stale"] is False and "available" in j["chrome"]
    assert "API-equivalent" in j["cost_note"]


def test_list_includes_buildable_experiments_without_reports(client, runs_dir):
    make_run(runs_dir, experiment="exp-new", config="A", repeat=1)
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    e = next(x for x in client.get("/api/reports").json()["experiments"] if x["experiment_id"] == "exp-new")
    assert e["in_store"] and not e["has_reports"] and e["dashboard"] is None


def test_list_empty_without_anything(client):
    j = client.get("/api/reports").json()
    assert j["experiments"] == [] and j["ingest"]["store_exists"] is False


def test_serve_types_and_pdf_inline(client, exp):
    r = client.get(f"/api/reports/{exp}/file", params={"name": "report.pdf"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content == PDF
    assert r.headers["content-disposition"].startswith("inline")
    r = client.get(f"/api/reports/{exp}/file", params={"name": "figures/cost.png"})
    assert r.headers["content-type"] == "image/png" and r.content == PNG
    r = client.get(f"/api/reports/{exp}/file", params={"name": "dashboard.html"})
    assert r.headers["content-type"].startswith("text/html") and r.text == HTML
    assert r.headers["x-content-type-options"] == "nosniff"


def test_dashboard_is_served_sandboxed(client, exp):
    r = client.get(f"/api/reports/{exp}/file", params={"name": "dashboard.html"})
    csp = r.headers["content-security-policy"]
    assert csp.startswith("sandbox;") and "default-src 'self'" in csp
    assert "allow-scripts" not in csp and "allow-same-origin" not in csp and "script-src" not in csp
    assert "frame-ancestors 'self'" in csp  # the UI shows it in an iframe
    # other responses keep the app-wide CSP
    app_csp = client.get("/api/health").headers["content-security-policy"]
    assert "frame-ancestors 'none'" in app_csp and "sandbox" not in app_csp
    assert "sandbox" not in client.get(f"/api/reports/{exp}/file", params={"name": "report.pdf"}
                                       ).headers["content-security-policy"]


@pytest.mark.parametrize("name", [
    "", "../../manifest.json", "..", "../exp-r/dashboard.html", "figures/../../x.png", "/etc/passwd",
    "figures/notes.txt", "report.html", "figures/", "figures/.png", "dashboard.html/", "dashboard.html\x00.png",
    "figures\\cost.png", "FIGURES/cost.png", "figures/sub/cost.png", "metrics.sqlite", ".env"])
def test_file_name_allowlist(client, exp, name):
    assert client.get(f"/api/reports/{exp}/file", params={"name": name}).status_code == 404


@pytest.mark.parametrize("bad", ["..", ".", "..%2f..", "a%2fb", "exp-r%00", ".hidden", "-x"])
def test_experiment_id_allowlist(client, exp, bad):
    r = client.get(f"/api/reports/{bad}/file", params={"name": "dashboard.html"})
    assert r.status_code == 404
    assert client.post(f"/api/reports/{bad}/rebuild", json={"kind": "dashboard"}).status_code in (404, 405)


def test_symlinked_file_does_not_escape(client, exp, runs_dir, tmp_path):
    secret = tmp_path / "secret.pdf"
    secret.write_bytes(b"%PDF-SECRET")
    (runs_dir / "reports" / exp / "report.pdf").unlink()
    (runs_dir / "reports" / exp / "report.pdf").symlink_to(secret)
    assert client.get(f"/api/reports/{exp}/file", params={"name": "report.pdf"}).status_code == 404
    png = tmp_path / "x.png"
    png.write_bytes(PNG)
    (runs_dir / "reports" / exp / "figures" / "evil.png").symlink_to(png)
    assert client.get(f"/api/reports/{exp}/file", params={"name": "figures/evil.png"}).status_code == 404
    listed = next(x for x in client.get("/api/reports").json()["experiments"] if x["experiment_id"] == exp)
    assert listed["pdf"] is None and "figures/evil.png" not in [f["name"] for f in listed["figures"]]


def test_symlinked_figures_dir_and_experiment_dir(client, exp, runs_dir, tmp_path):
    out = tmp_path / "elsewhere"
    out.mkdir()
    (out / "dashboard.html").write_text("outside")
    (out / "cost.png").write_bytes(PNG)
    (runs_dir / "reports" / "linked").symlink_to(out)
    assert client.get("/api/reports/linked/file", params={"name": "dashboard.html"}).status_code == 404
    d = runs_dir / "reports" / exp
    for p in (d / "figures").iterdir():
        p.unlink()
    (d / "figures").rmdir()
    (d / "figures").symlink_to(out)
    assert client.get(f"/api/reports/{exp}/file", params={"name": "figures/cost.png"}).status_code == 404
    assert "linked" not in [x["experiment_id"] for x in client.get("/api/reports").json()["experiments"]]


def test_reports_need_a_token_and_post_checks_origin(settings, exp):
    with TestClient(create_app(settings), base_url=BASE) as c:
        assert c.get("/api/reports").status_code == 401
        assert c.get(f"/api/reports/{exp}/file", params={"name": "report.pdf"}).status_code == 401
        assert c.post(f"/api/reports/{exp}/rebuild", json={"kind": "dashboard"}).status_code == 401
        r = c.post(f"/api/reports/{exp}/rebuild", json={"kind": "dashboard"},
                   headers={**AUTH, "Origin": "https://evil.example"})
        assert r.status_code == 403


# ---------------------------------------------------------------- rebuild (CLI mocked)
class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        out = Path(argv[argv.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / ("report.pdf" if "--pdf" in argv else "dashboard.html")).write_text("built")
        return subprocess.CompletedProcess(argv, 0, stdout="built it\n", stderr="")


@pytest.fixture
def fake(monkeypatch):
    f = FakeRun()
    monkeypatch.setattr(reports.subprocess, "run", f)
    monkeypatch.setattr(reports, "chrome_status", lambda: {"available": True, "error": None})
    return f


def test_rebuild_dashboard_runs_the_cli(client, exp, fake, settings):
    r = client.post(f"/api/reports/{exp}/rebuild", json={"kind": "dashboard"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] and j["output"].startswith("built it") and j["artifact"]["name"] == "dashboard.html"
    (argv, kw), = fake.calls
    assert argv[:5] == [sys.executable, "-m", "runner.cli", "dashboard", exp]
    assert argv[argv.index("--db") + 1] == str(settings.db_path)
    assert argv[argv.index("--out") + 1] == str(settings.runs_dir / "reports" / exp)
    assert kw["cwd"] == settings.repo_root and kw["timeout"] > 0


def test_rebuild_pdf_runs_report_pdf(client, exp, fake):
    j = client.post(f"/api/reports/{exp}/rebuild", json={"kind": "pdf"}).json()
    assert j["ok"] and j["artifact"]["name"] == "report.pdf"
    argv = fake.calls[0][0]
    assert argv[3:6] == ["report", exp, "--pdf"]


def test_rebuild_env_is_scrubbed(client, exp, fake, monkeypatch):
    for k, v in {"ANTHROPIC_API_KEY": "sk-secret", "AWS_SECRET_ACCESS_KEY": "x", "HOME": "/home/x",
                 "LRAE_CHROME": "/opt/chrome", "LRAE_UI_TOKEN": "tok"}.items():
        monkeypatch.setenv(k, v)
    client.post(f"/api/reports/{exp}/rebuild", json={"kind": "dashboard"})
    env = fake.calls[0][1]["env"]
    assert set(env) <= {"PATH", "LANG", "LC_ALL", "TMPDIR", "LRAE_CHROME", "MPLCONFIGDIR"}
    assert env["LRAE_CHROME"] == "/opt/chrome" and "PATH" in env
    assert "HOME" not in env and not any("SECRET" in k or "KEY" in k or "TOKEN" in k for k in env)


def test_rebuild_validates_kind_and_experiment(client, exp, fake):
    assert client.post(f"/api/reports/{exp}/rebuild", json={"kind": "rm -rf"}).status_code == 422
    assert client.post(f"/api/reports/{exp}/rebuild", json={}).status_code == 422
    r = client.post("/api/reports/not-ingested/rebuild", json={"kind": "dashboard"})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_in_store"
    assert fake.calls == []


def test_rebuild_refuses_stale_store_unless_acknowledged(client, exp, fake, runs_dir):
    make_run(runs_dir, experiment="exp-r", config="A", repeat=2, n_cp=2)  # a run the store has not seen
    r = client.post(f"/api/reports/{exp}/rebuild", json={"kind": "dashboard"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "store_stale" and fake.calls == []
    assert client.get("/api/reports").json()["ingest"]["stale"] is True
    r = client.post(f"/api/reports/{exp}/rebuild", json={"kind": "dashboard", "allow_stale": True})
    assert r.status_code == 200 and r.json()["stale_store"] is True and len(fake.calls) == 1


def test_rebuild_pdf_without_chrome_is_a_clear_error(client, exp, monkeypatch):
    called = []
    monkeypatch.setattr(reports.subprocess, "run", lambda *a, **k: called.append(a))
    monkeypatch.setattr(reports, "chrome_status", lambda: {"available": False,
                                                           "error": "headless Chrome not found; install it"})
    r = client.post(f"/api/reports/{exp}/rebuild", json={"kind": "pdf"})
    assert r.status_code == 424 and r.json()["detail"]["code"] == "chrome_not_found"
    assert "Chrome not found" in r.json()["detail"]["message"] and called == []
    # the dashboard does not need Chrome
    monkeypatch.setattr(reports.subprocess, "run", FakeRun())
    assert client.post(f"/api/reports/{exp}/rebuild", json={"kind": "dashboard"}).status_code == 200


def test_chrome_status_reports_missing(monkeypatch):
    import report.build as rb
    monkeypatch.setenv("LRAE_CHROME", "/nonexistent/chrome")
    monkeypatch.setattr(rb, "CHROME_CANDIDATES", ())
    s = reports.chrome_status()
    assert s["available"] is False and "Chrome not found" in s["error"]


def test_rebuild_failure_returns_output_tail(client, exp, monkeypatch):
    monkeypatch.setattr(reports.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(
        argv, 1, stdout="", stderr="x" * 6000 + "Traceback boom"))
    r = client.post(f"/api/reports/{exp}/rebuild", json={"kind": "dashboard"})
    j = r.json()
    assert r.status_code == 500 and j["ok"] is False and j["exit_code"] == 1
    assert j["output"].endswith("Traceback boom") and len(j["output"]) <= reports.TAIL


def test_rebuild_timeout(client, exp, monkeypatch):
    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1)
    monkeypatch.setattr(reports.subprocess, "run", boom)
    r = client.post(f"/api/reports/{exp}/rebuild", json={"kind": "dashboard"})
    assert r.status_code == 500 and "timed out" in r.json()["output"]
    # the lock was released
    monkeypatch.setattr(reports.subprocess, "run", FakeRun())
    assert client.post(f"/api/reports/{exp}/rebuild", json={"kind": "dashboard"}).status_code == 200


def test_rebuild_is_single_flight(client, exp, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow(argv, **kw):
        started.set()
        release.wait(10)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(reports.subprocess, "run", slow)
    first = {}
    t = threading.Thread(target=lambda: first.setdefault(
        "r", client.post(f"/api/reports/{exp}/rebuild", json={"kind": "dashboard"})))
    t.start()
    assert started.wait(10)
    r2 = client.post(f"/api/reports/{exp}/rebuild", json={"kind": "dashboard"})
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "busy"
    release.set()
    t.join(10)
    assert first["r"].status_code == 200


# ---------------------------------------------------------------- end to end (real CLI, no mocks)
def test_rebuild_dashboard_end_to_end(client, runs_dir, settings):
    make_run(runs_dir, experiment="exp-e2e", config="A", repeat=1, n_cp=3, hazards=[hazard()])
    make_run(runs_dir, experiment="exp-e2e", config="A", repeat=2, n_cp=3)
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    r = client.post("/api/reports/exp-e2e/rebuild", json={"kind": "dashboard"})
    assert r.status_code == 200, r.text
    d = runs_dir / "reports" / "exp-e2e"
    assert (d / "dashboard.html").is_file() and (d / "figures" / "survival.png").is_file()
    served = client.get("/api/reports/exp-e2e/file", params={"name": "dashboard.html"})
    assert "estimated (API-equivalent)" in served.text
    listed = next(x for x in client.get("/api/reports").json()["experiments"] if x["experiment_id"] == "exp-e2e")
    assert listed["dashboard"] and "figures/survival.png" in [f["name"] for f in listed["figures"]]
    # same file as the plain CLI produces
    out2 = runs_dir.parent / "cli-out"
    subprocess.run([sys.executable, "-m", "runner.cli", "dashboard", "exp-e2e", "--db", str(settings.db_path),
                    "--out", str(out2)], cwd=settings.repo_root, check=True, capture_output=True,
                   env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "")})
    assert (out2 / "dashboard.html").read_text() == (d / "dashboard.html").read_text()


@pytest.mark.local
def test_rebuild_pdf_matches_cli(client, runs_dir, settings):
    from report.build import ChromeNotFound, find_chrome
    try:
        find_chrome()
    except ChromeNotFound:
        pytest.skip("headless Chrome not installed")
    make_run(runs_dir, experiment="exp-pdf", config="A", repeat=1, n_cp=3, hazards=[hazard()])
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    r = client.post("/api/reports/exp-pdf/rebuild", json={"kind": "pdf"})
    assert r.status_code == 200, r.text
    pdf = (runs_dir / "reports" / "exp-pdf" / "report.pdf").read_bytes()
    assert pdf.startswith(b"%PDF")
    out2 = runs_dir.parent / "cli-pdf"
    subprocess.run([sys.executable, "-m", "runner.cli", "report", "exp-pdf", "--pdf", "--db",
                    str(settings.db_path), "--out", str(out2)], cwd=settings.repo_root, check=True,
                   capture_output=True, env=os.environ.copy())
    other = (out2 / "report.pdf").read_bytes()

    def pages(b: bytes) -> int:
        return b.count(b"/Type /Page\n") + b.count(b"/Type /Page ") + b.count(b"/Type/Page/")

    assert pages(pdf) == pages(other) and abs(len(pdf) - len(other)) < 0.02 * len(other)
    served = client.get("/api/reports/exp-pdf/file", params={"name": "report.pdf"})
    assert served.content == pdf
