import re
import socket

import pytest

from analysis.ingest import ingest
from report import build
from report.dashboard import build_dashboard
from tests.unit.analysis import synth
from tests.unit.analysis.synth import hazard, make_run


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("telemetry.counters.interval_counters", synth.fake_counters)
    r = tmp_path / "runs"
    make_run(r, repeat=1, hazards=[hazard("quality", 700.0, "R>0", "test <b>x</b> regressed")])
    make_run(r, repeat=2)
    make_run(r, repeat=3, state="KILLED", n_cp=1, hazards=[hazard("safety", 300.0, "forbidden_command")])
    make_run(r, repeat=4, state="INTERRUPTED", censored_reason="usage_limit")
    ingest(r, tmp_path / "m.sqlite")
    return tmp_path / "m.sqlite"


def test_dashboard_builds_offline(db, tmp_path, monkeypatch):
    def no_net(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket, "socket", no_net)
    monkeypatch.setattr(socket, "create_connection", no_net)
    out = tmp_path / "out"
    path = build_dashboard(db, "exp-one", out)
    html = path.read_text()
    assert "{{" not in html and "{%" not in html
    figs = sorted((out / "figures").glob("*.png"))
    assert {f.name for f in figs} == {"survival.png", "metric_strips.png", "cost.png", "context_fill.png"}
    for f in figs:
        assert f.stat().st_size > 1000 and f.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert f"figures/{f.name}" in html
    assert not re.search(r"https?://", html)
    assert "estimated (API-equivalent)" in html
    assert "not OS-isolated" in html
    assert "guardrail kill" in html and "hazard: quality" in html and "interruption" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html            # evidence is escaped
    assert "exp-one-A-r04-abcd1234" in html


def test_dashboard_is_deterministic(db, tmp_path):
    a = build_dashboard(db, "exp-one", tmp_path / "a")
    b = build_dashboard(db, "exp-one", tmp_path / "b")
    assert a.read_text() == b.read_text()
    for name in ("survival.png", "metric_strips.png"):
        assert (tmp_path / "a/figures" / name).read_bytes() == (tmp_path / "b/figures" / name).read_bytes()


def test_unknown_experiment(db, tmp_path):
    with pytest.raises(LookupError):
        build_dashboard(db, "nope", tmp_path / "o")


def test_empty_survival_set(tmp_path, monkeypatch):
    monkeypatch.setattr("telemetry.counters.interval_counters", synth.fake_counters)
    r = tmp_path / "runs"
    make_run(r, state="FAILED", n_cp=0)
    ingest(r, tmp_path / "m.sqlite")
    html = build_dashboard(tmp_path / "m.sqlite", "exp-one", tmp_path / "o").read_text()
    assert "No runs in the survival set" in html


def test_chrome_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(build, "CHROME_CANDIDATES", ("definitely-not-chrome",))
    monkeypatch.delenv("LRAE_CHROME", raising=False)
    with pytest.raises(build.ChromeNotFound):
        build.find_chrome()


@pytest.mark.local
def test_build_pdf(db, tmp_path):
    try:
        build.find_chrome()
    except build.ChromeNotFound:
        pytest.skip("Chrome not installed")
    pdf = build.build_pdf(db, "exp-one", tmp_path / "rep")
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 5000
    assert len(re.findall(rb"/Type\s*/Page[^s]", data)) == 1   # one page
