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


def test_dashboard_without_per_commit_data(db, tmp_path):
    out = tmp_path / "o"
    html = build_dashboard(db, "exp-one", out).read_text()
    assert "No per-commit data" in html
    assert not list((out / "figures").glob("deg_*"))


@pytest.fixture
def deg_db(tmp_path, monkeypatch):
    monkeypatch.setattr("telemetry.counters.interval_counters", synth.fake_counters)
    r = tmp_path / "runs"
    synth.make_degrading_run(r, repeat=1)
    synth.make_degrading_run(r, repeat=2)
    make_run(r, repeat=3)
    ingest(r, tmp_path / "m.sqlite")
    return tmp_path / "m.sqlite"


def test_degradation_section(deg_db, tmp_path):
    out = tmp_path / "out"
    html = build_dashboard(deg_db, "exp-one", out).read_text()
    assert "No per-commit data" not in html and "{{" not in html
    names = {f.name for f in (out / "figures").glob("deg_*.png")}
    assert len(names) == 8                       # 4 figures x the 2 runs with data
    for n in names:
        assert f"figures/{n}" in html and (out / "figures" / n).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert (out / "figures" / n).stat().st_size > 1500
    assert "Top relapsing tests" in html and "test_t1_a.py::a" in html
    assert "2 of 2 green" in html                # belief gap summary
    assert "Staged task" in html and "Carried / retired" in html
    assert not re.search(r"https?://", html)


def test_degradation_is_deterministic(deg_db, tmp_path):
    a = build_dashboard(deg_db, "exp-one", tmp_path / "a")
    b = build_dashboard(deg_db, "exp-one", tmp_path / "b")
    assert a.read_text() == b.read_text()
    for f in sorted((tmp_path / "a/figures").glob("deg_*.png")):
        assert f.read_bytes() == (tmp_path / "b/figures" / f.name).read_bytes()


def test_behaviour_and_security_panels(tmp_path, monkeypatch):
    from tests.unit.analysis.test_behavior import AF_HZ, DC_HZ, GM_J
    monkeypatch.setattr("telemetry.counters.interval_counters", synth.fake_counters)
    r = tmp_path / "runs"
    sec = {"SEC_new": (2.0, {"new_by_severity": {"high": 1, "medium": 1}}), "SEC_open": (2.0, {}),
           "SEC_exploits": (1.0, {"active": 3}), "SEC_ai": (1.0, {}),
           "behavior_judge_cost_usd": (0.25, {}),
           "BEH_ED_stuck_episodes": (1.0, {"episodes": [{"command": "make <x>", "attempts": 3, "max_tier": 4,
                                                         "escalation": 1.5, "t_s": 1300.0}]})}
    make_run(r, repeat=1, behavior_by_k={1: [AF_HZ], 2: [DC_HZ], 3: [GM_J]}, metrics_by_k={3: sec},
             stages=[(0, 0.0, False), (1, 650.0, False)])
    make_run(r, repeat=2)
    make_run(r, repeat=3, behavior_by_k={1: [DC_HZ]})                  # behaviour but no security data
    ingest(r, tmp_path / "m.sqlite")
    out = tmp_path / "out"
    html = build_dashboard(tmp_path / "m.sqlite", "exp-one", out).read_text()
    names = {f.name for f in (out / "figures").glob("*.png")}
    assert {"beh_survival.png", "beh_exp-one-A-r01-abcd1234_timeline.png",
            "beh_exp-one-A-r01-abcd1234_security.png"} <= names
    assert "<h2>Behaviour and security</h2>" in html
    assert "claimed_all_pass" in html and "make &lt;x&gt;" in html       # evidence and commands escaped
    assert "$0.25" in html                                              # judge spend, outside S(t)
    for name in ("beh_survival.png", "beh_exp-one-A-r01-abcd1234_timeline.png"):
        assert f"figures/{name}" in html
    # a run without behaviour data gets no per-run figures
    assert not any("r02" in n for n in names)
    assert "beh_exp-one-A-r03-abcd1234_timeline.png" in names and not any("r03" in n and "security" in n for n in names)
