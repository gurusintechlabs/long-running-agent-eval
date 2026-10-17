import sqlite3

import pytest

from analysis import degradation as dg
from analysis.ingest import ingest
from tests.unit.analysis import synth
from tests.unit.analysis.synth import make_degrading_run, make_run

A, B, C, D, E, OLD = synth.DEG_TESTS


@pytest.fixture(autouse=True)
def counters(monkeypatch):
    monkeypatch.setattr("telemetry.counters.interval_counters", synth.fake_counters)


@pytest.fixture
def db(tmp_path):
    r = tmp_path / "runs"
    rid = make_degrading_run(r)
    make_run(r, repeat=2)                      # an old-style run without per-commit data
    ingest(r, tmp_path / "m.sqlite")
    return tmp_path / "m.sqlite", rid


def test_ingest_tables(db):
    path, rid = db
    con = sqlite3.connect(path)
    n_commit = con.execute("SELECT COUNT(*) FROM test_outcomes WHERE point='commit' AND suite='hidden'").fetchone()[0]
    n_cp = con.execute("SELECT COUNT(*) FROM test_outcomes WHERE point='checkpoint' AND suite='hidden'").fetchone()[0]
    assert (n_commit, n_cp) == (6 * 6, 3 * 6)
    assert con.execute("SELECT DISTINCT tier FROM test_outcomes WHERE test_id=?", (OLD,)).fetchall() == [("1",)]
    assert {r[0] for r in con.execute("SELECT tier FROM test_outcomes")} == {"1", "2", "3"}
    st = con.execute("SELECT stage FROM test_outcomes WHERE point='checkpoint' AND k=2 LIMIT 1").fetchone()
    assert st == (1,)                                         # derived from stage.delivered at 650
    assert con.execute("SELECT stage, t_s, interrupted FROM stages ORDER BY stage").fetchall() == [
        (0, 0.0, 0), (1, 650.0, 0)]
    assert con.execute("SELECT t_s, passed, failed, errors, skipped FROM agent_test_runs ORDER BY t_s").fetchall() \
        == [(750.0, 10, 0, 0, 0), (1000.0, 9, 1, 0, 0), (1500.0, 8, 0, 0, 0)]


def test_ingest_tier_falls_back_to_file_name(tmp_path):
    r = tmp_path / "runs"
    make_degrading_run(r, tiers=False)
    ingest(r, tmp_path / "m.sqlite")
    con = sqlite3.connect(tmp_path / "m.sqlite")
    assert dict(con.execute("SELECT DISTINCT test_id, tier FROM test_outcomes"))[OLD] == "1"


def test_ingest_is_deterministic_and_old_runs_work(tmp_path):
    r = tmp_path / "runs"
    make_degrading_run(r)
    make_run(r, repeat=2)
    ingest(r, tmp_path / "a.sqlite")
    ingest(r, tmp_path / "b.sqlite")
    q = "SELECT * FROM {} ORDER BY rowid"
    for t in ("test_outcomes", "stages", "agent_test_runs"):
        a, b = (sqlite3.connect(tmp_path / f"{x}.sqlite").execute(q.format(t)).fetchall() for x in "ab")
        assert a == b and a
    old = "exp-one-A-r02-abcd1234"
    assert dg.load_matrix(tmp_path / "a.sqlite", old).points == []
    assert dg.timelines(tmp_path / "a.sqlite", old) == [] and dg.run_summary(tmp_path / "a.sqlite", old) is None
    assert dg.runs_with_data(tmp_path / "a.sqlite", "exp-one") == ["exp-one-A-r01-abcd1234"]


def test_missing_tables_do_not_raise(tmp_path):
    p = tmp_path / "old.sqlite"
    sqlite3.connect(p).execute("CREATE TABLE runs(run_id TEXT, experiment_id TEXT, config TEXT, repeat INT)").connection.close()
    assert dg.runs_with_data(p, "x") == [] and dg.pass_rates(p, "r") == [] and dg.belief_gap(p, "r") == []
    assert dg.stage_effects(p, "r") == [] and dg.window_rates(p, "r") == []


def test_points_and_timelines(db):
    path, rid = db
    m = dg.load_matrix(path, rid)
    assert [(p.t_s, p.point) for p in m.points] == [
        (100, "commit"), (300, "commit"), (500, "commit"), (600, "checkpoint"), (700, "commit"),
        (900, "commit"), (1100, "commit"), (1200, "checkpoint"), (1800, "checkpoint")]
    assert m.tests == [A, B, OLD, C, D, E]                                         # tier, then id
    tl = {t.test_id: t for t in dg.timelines(path, rid)}
    assert tl[A].regressions == [700, 1100] and tl[A].recoveries == [900] and tl[A].relapsed
    assert tl[A].first_pass_t == 100 and tl[A].ttfr_s == 600 and tl[A].final_outcome == "failed"
    assert tl[B].regressions == [300, 700] and tl[B].recoveries == [500, 900] and tl[B].ttfr_s == 200
    assert tl[C].regressions == [900] and tl[C].first_pass_t == 300 and not tl[C].relapsed
    assert tl[D].regressions == [] and tl[D].first_pass_t == 500 and tl[D].ttfr_s is None
    assert tl[E].first_pass_t is None and tl[E].regressions == []
    assert tl[OLD].regressions == [] and tl[OLD].final_outcome == "passed"      # skipped is never a regression
    flips = dg.flip_events(path, rid)
    assert [(f.t_s, f.kind) for f in flips if f.kind == "regression"] == [
        (300, "regression"), (700, "regression"), (700, "regression"), (900, "regression"), (1100, "regression")]
    s = dg.run_summary(path, rid)
    assert (s["regressions"], s["regressed_tests"], s["relapsing_tests"], s["ever_passed"]) == (5, 3, 2, 5)
    assert s["mean_ttfr_s"] == pytest.approx((600 + 200 + 600) / 3)
    top = dg.top_relapsers(path, [rid], n=2)
    assert [(r["test_id"], r["regressions"]) for r in top] == sorted([(A, 2), (B, 2)], key=lambda x: x[0])


def test_pass_rates_and_established(db):
    path, rid = db
    rp = dg.pass_rates(path, rid)
    est = [r.established for r in rp]
    assert est[0] is None
    assert est[1:] == pytest.approx([2 / 3, 1.0, 1.0, 0.5, 0.75, 0.5, 0.5, 0.5])
    # overall, c1: a b old pass of 5 active (e skipped)
    assert (rp[0].passed, rp[0].active) == (3, 5)
    assert rp[0].tiers == {"1": (3, 3), "2": (0, 2)}
    assert (rp[4].passed, rp[4].active) == (2, 5) and rp[4].tiers["3"] == (0, 1)   # old is skipped from stage 1
    assert rp[4].stage == 1 and rp[3].stage == 0


def test_regression_rates(db):
    path, rid = db
    w = dg.window_rates(path, rid, window_s=600)
    assert [x["regressions"] for x in w] == [1, 4, 0]
    assert [x["per_hour"] for x in w] == pytest.approx([6, 24, 0])
    iv = dg.fill_intervals(path, rid)
    assert [(i["k"], i["fill"], i["regressions"], i["class"]) for i in iv] == [
        (1, pytest.approx(0.1), 1, "other"), (2, pytest.approx(0.2), 4, "compaction"),
        (3, pytest.approx(0.3), 0, "after_compaction")]
    bins = dg.fill_bins(iv)
    assert [b["regressions"] for b in bins] == [5, 0, 0, 0] and bins[0]["per_hour"] == pytest.approx(15) \
        and [b["intervals"] for b in bins] == [2, 1, 0, 0]
    eff = {e["class"]: e["per_hour"] for e in dg.compaction_effect(iv)}
    assert eff == pytest.approx({"compaction": 24, "after_compaction": 0, "other": 6})


def test_belief_gap(db):
    path, rid = db
    rows = dg.belief_gap(path, rid)
    assert [(r["t_s"], r["state_t_s"], r["agent_failed"], r["established_failing"], r["gap"]) for r in rows] == [
        (750, 700, 0, 2, True), (1000, 900, 1, 1, False), (1500, 1100, 0, 2, True)]
    assert dg.belief_summary(rows) == {"test_runs": 3, "green": 2, "gaps": 2, "gap_frac": 1.0}


def test_staged(db):
    path, rid = db
    sc = {r["t_s"]: r for r in dg.status_counts(path, rid)}
    assert sc[700] == {"t_s": 700, "point": "commit", "k": 2, "stage": 1, "passing": 2, "regressed": 2,
                       "not_yet_implemented": 1, "inactive": 1}
    assert sc[100]["not_yet_implemented"] == 2 and sc[100]["inactive"] == 1       # c, d never passed yet
    (eff,) = dg.stage_effects(path, rid)
    assert (eff["stage"], eff["t_s"], eff["carried"], eff["retired"], eff["introduced"]) == (1, 650, 4, 1, 1)
    assert eff["carried_before"] == 1.0 and eff["carried_after"] == 0.5 and eff["carried_end"] == 0.5
    assert eff["retired_before"] == 1.0 and eff["introduced_end"] == 0.0 and eff["carried_regressions"] == 4


def test_unstaged_run_has_no_stage_effects(tmp_path):
    r = tmp_path / "runs"
    rid = make_degrading_run(r)
    f = r / rid / "events" / "orchestrator.jsonl"
    f.write_text("\n".join(x for x in f.read_text().splitlines() if "stage.delivered" not in x) + "\n")
    ingest(r, tmp_path / "m.sqlite")
    assert dg.stage_effects(tmp_path / "m.sqlite", rid) == []
