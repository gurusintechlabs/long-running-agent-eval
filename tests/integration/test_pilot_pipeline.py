"""Phase 4: scripted end-to-end pilot (2 repeats x 6 checkpoints) -> ingest -> dashboard -> PDF.

docs/plan.md asks for dt = 1 min; this test uses dt = 20 s so `pytest -m local` stays practical
(scoring a checkpoint takes ~5-8 s, under dt/2). `lrae run spec/examples/pilot-scripted.yaml` runs the
1-minute version (docs/phase-4-summary.md records that run).
"""
import shutil
import sqlite3

import pytest

from analysis.ingest import ingest
from report.dashboard import build_dashboard
from runner.orchestrator import Run, RunState
from spec.loader import load_spec

from .pilot_support import CORE, make_pilot_spec, scorer_passes, scorer_venv  # noqa: F401

pytestmark = pytest.mark.local

DT_S, K, REPEATS = 20.0, 6, 2


@pytest.fixture(scope="module")
def pilot(tmp_path_factory, scorer_venv):  # noqa: F811
    tmp = tmp_path_factory.mktemp("pilot")
    repo_root = tmp / "repo"
    repo_root.mkdir()
    (tmp / "claude").mkdir()
    loaded = load_spec(make_pilot_spec(tmp, dt_s=DT_S, k=K, repeats=REPEATS), repo_root=repo_root)
    results = []
    for rep in range(REPEATS):
        run = Run(loaded, "A", rep, repo_root=repo_root, claude_home=tmp / "claude",
                  host_home=tmp / "home", caffeinate=False, score=True)
        results.append(run.execute())
    db = repo_root / "runs" / "metrics.sqlite"
    report = ingest(repo_root / "runs", db)
    return dict(tmp=tmp, repo_root=repo_root, loaded=loaded, results=results, db=db, report=report)


def test_runs_complete_and_every_checkpoint_is_scored(pilot):
    for res in pilot["results"]:
        assert res.state == RunState.COMPLETED, res.error
        passes = scorer_passes(res.paths.art)
        assert sorted(passes) == list(range(1, K + 1))


def test_store_has_7_metrics_x_6_checkpoints_x_2_runs_without_nulls(pilot):
    con = sqlite3.connect(pilot["db"])
    rows = con.execute(f"SELECT run_id, k, name, value FROM metrics WHERE name IN ({','.join('?' * 7)})",
                       CORE).fetchall()
    assert len(rows) == 7 * K * REPEATS
    assert [r for r in rows if r[3] is None] == []
    runs = con.execute("SELECT run_id, state, event, ttfh_s FROM runs ORDER BY run_id").fetchall()
    assert len(runs) == REPEATS and all(r[1] == "COMPLETED" for r in runs)
    # the scripted agent adds the route at t2 before its test at t3: a context hazard in both runs
    hz = con.execute("SELECT run_id, dimension, k FROM hazards ORDER BY run_id").fetchall()
    assert [(d, k) for _, d, k in hz] == [("context", 2)] * REPEATS
    assert all(r[2] == 1 for r in runs)
    counters = con.execute("SELECT COUNT(*) FROM counters WHERE name = 'cost_usd'").fetchone()[0]
    assert counters == K * REPEATS


def test_metrics_are_stable_across_repeats(pilot):
    """Scripted repeats are identical in behaviour, so every deterministic metric must match."""
    con = sqlite3.connect(pilot["db"])
    a, b = sorted(r[0] for r in con.execute("SELECT run_id FROM runs"))
    for name in ("P", "R", "C", "W", "S", "D"):
        va = con.execute("SELECT k, value FROM metrics WHERE run_id=? AND name=? ORDER BY k", (a, name)).fetchall()
        vb = con.execute("SELECT k, value FROM metrics WHERE run_id=? AND name=? ORDER BY k", (b, name)).fetchall()
        assert va == vb, name


def test_ingest_is_rebuild_identical(pilot, tmp_path):
    again = tmp_path / "again.sqlite"
    ingest(pilot["repo_root"] / "runs", again)
    dump = lambda p: list(sqlite3.connect(p).iterdump())  # noqa: E731
    assert dump(again) == dump(pilot["db"])


def test_dashboard_and_pdf_build_from_the_store(pilot):
    eid = pilot["loaded"].spec.experiment_id
    out = pilot["tmp"] / "dash"
    html = build_dashboard(pilot["db"], eid, out)
    text = html.read_text()
    assert "{{" not in text and "{%" not in text
    for png in (out / "figures").glob("*.png"):
        assert png.name in text
    if shutil.which("google-chrome") or shutil.which("chromium") or \
            __import__("pathlib").Path("/Applications/Google Chrome.app").exists():
        from report.build import build_pdf
        pdf = build_pdf(pilot["db"], eid, pilot["tmp"] / "pdf")
        assert pdf.read_bytes()[:4] == b"%PDF"
