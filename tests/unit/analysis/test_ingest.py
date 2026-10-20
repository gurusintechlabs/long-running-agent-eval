import sqlite3

import pytest

from analysis.ingest import TABLES, ingest
from tests.unit.analysis import synth
from tests.unit.analysis.synth import hazard, make_run, score_pass


@pytest.fixture(autouse=True)
def counters(monkeypatch):
    monkeypatch.setattr("telemetry.counters.interval_counters", synth.fake_counters)


def dump(db):
    con = sqlite3.connect(db)
    out = {t: con.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in TABLES}
    con.close()
    return out


def rows(db, sql):
    con = sqlite3.connect(db)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


@pytest.fixture
def runs(tmp_path):
    r = tmp_path / "runs"
    make_run(r, repeat=1, hazards=[hazard("quality", 700.0)])
    make_run(r, repeat=2)
    make_run(r, repeat=3, state="BUDGET_EXHAUSTED", n_cp=2)
    make_run(r, repeat=4, state="INTERRUPTED", n_cp=2, censored_reason="usage_limit")
    make_run(r, repeat=5, state="KILLED", n_cp=1, hazards=[hazard("safety", 300.0, "forbidden_command")])
    make_run(r, repeat=6, state="FAILED", n_cp=0)
    return r


def test_complete(runs, tmp_path):
    rep = ingest(runs, tmp_path / "m.sqlite")
    db = tmp_path / "m.sqlite"
    assert rep.runs == 6 and rep.in_survival == 5
    assert rows(db, "SELECT COUNT(*) FROM runs")[0][0] == 6
    assert rows(db, "SELECT COUNT(*) FROM metrics WHERE run_id LIKE '%r01%'")[0][0] == 3 * 7
    assert rows(db, "SELECT COUNT(*) FROM checkpoints")[0][0] == 3 + 3 + 2 + 2 + 1
    assert rows(db, "SELECT COUNT(*) FROM counters WHERE run_id LIKE '%r01%'")[0][0] == 3 * 8
    assert rows(db, "SELECT dimension, k, t_attributed_s FROM hazards WHERE run_id LIKE '%r01%'") == [
        ("quality", 2, 700.0)]
    assert rows(db, "SELECT count FROM events_index WHERE run_id LIKE '%r01%' AND type='scorer.metric'") == [(21,)]
    assert rows(db, "SELECT experiment_id, task_class FROM runs LIMIT 1") == [("exp-one", "L1")]
    assert rows(db, "SELECT COUNT(*) FROM experiments")[0][0] == 1
    assert rows(db, "SELECT cost_usd, tokens FROM runs WHERE run_id LIKE '%r01%'") == [(0.75, 3 * 165)]


def test_survival_columns(runs, tmp_path):
    ingest(runs, tmp_path / "m.sqlite")
    got = {r[0][-12:-9]: r[1:] for r in rows(tmp_path / "m.sqlite",
           "SELECT run_id, state, ttfh_s, event, censored_reason, duration_s FROM runs")}
    assert got["r01"] == ("COMPLETED", 700.0, 1, None, 1800.0)
    assert got["r02"] == ("COMPLETED", None, 0, "deadline", 1800.0)
    assert got["r03"] == ("BUDGET_EXHAUSTED", None, 0, "budget", 1200.0)
    assert got["r04"] == ("INTERRUPTED", None, 0, "usage_limit", 1200.0)
    assert got["r05"] == ("KILLED", 300.0, 1, None, 600.0)
    assert got["r06"] == ("FAILED", None, None, "failed", 0.0)


def test_failed_run_kept_but_excluded_from_survival_inputs(runs, tmp_path):
    from analysis.survival import survival_inputs
    ingest(runs, tmp_path / "m.sqlite")
    (times, events), = survival_inputs(tmp_path / "m.sqlite", "exp-one").values()
    assert len(times) == 5 and sorted(events) == [0, 0, 0, 1, 1]
    assert rows(tmp_path / "m.sqlite", "SELECT COUNT(*) FROM runs WHERE state='FAILED'")[0][0] == 1


def test_idempotent_and_rebuild_identical(runs, tmp_path):
    db = tmp_path / "m.sqlite"
    ingest(runs, db)
    first = dump(db)
    ingest(runs, db)
    assert dump(db) == first
    db.unlink()
    ingest(runs, db)
    assert dump(db) == first
    assert not list(tmp_path.glob("*.tmp*"))


def test_byte_identical_file(runs, tmp_path):
    ingest(runs, tmp_path / "a.sqlite")
    ingest(runs, tmp_path / "b.sqlite")
    assert (tmp_path / "a.sqlite").read_bytes() == (tmp_path / "b.sqlite").read_bytes()


def test_last_ok_pass_wins(tmp_path):
    r = tmp_path / "runs"
    extra = [score_pass(2, "late-bad", ok=False, value=0.99),          # failed pass is ignored
             score_pass(2, "rescore", value=0.2, hazards=[hazard("context", 650.0, "W>0.3")]),
             score_pass(2, "late-partial", ok=False, value=0.77)]
    make_run(r, extra_passes=extra)
    ingest(r, tmp_path / "m.sqlite")
    vals = rows(tmp_path / "m.sqlite", "SELECT k, value FROM metrics WHERE name='R' ORDER BY k")
    assert vals == [(1, 0.5), (2, 0.2), (3, 0.5)]
    assert rows(tmp_path / "m.sqlite", "SELECT dimension FROM hazards") == [("context",)]
    # the rescore's hazard also determines TTFH
    assert rows(tmp_path / "m.sqlite", "SELECT ttfh_s, event FROM runs") == [(650.0, 1)]


def test_null_metric_stored_as_null(tmp_path):
    r = tmp_path / "runs"
    make_run(r, n_cp=1)
    p = next(r.glob("*/events/scorer.jsonl"))
    p.write_text(p.read_text().replace('"value": 0.51, "detail": {}', '"value": null, "detail": {"reason": "x"}', 1))
    ingest(r, tmp_path / "m.sqlite")
    assert rows(tmp_path / "m.sqlite", "SELECT value, detail_json FROM metrics WHERE name='P'") == [
        (None, '{"reason": "x"}')]


def test_counters_missing_records_zeros_and_warning(tmp_path, monkeypatch):
    def boom(events_dir, models_yaml=None):
        raise ImportError("not written yet")
    monkeypatch.setattr("telemetry.counters.interval_counters", boom)
    r = tmp_path / "runs"
    make_run(r, n_cp=2)
    rep = ingest(r, tmp_path / "m.sqlite")
    assert any("counters unavailable" in w for w in rep.warnings)
    assert rows(tmp_path / "m.sqlite", "SELECT COUNT(*), SUM(value) FROM counters") == [(26, 0.0)]


def test_unfinished_run_and_torn_lines(tmp_path):
    r = tmp_path / "runs"
    rid = make_run(r, with_end=False, state="RUNNING")
    (r / rid / "events" / "scorer.jsonl").open("a").write('{"torn": ')
    (r / "no-manifest").mkdir()
    ingest(r, tmp_path / "m.sqlite")
    assert rows(tmp_path / "m.sqlite", "SELECT state, event FROM runs") == [("RUNNING", None)]


def test_duration_is_agent_time_not_preparation_or_finalizing(tmp_path):
    """duration_s runs from the run.clock origin to entering FINALIZING, like checkpoint t_s.
    Preparation (venv build, probe) and finalizing (shutdown, scorer drain) are excluded."""
    import json
    from datetime import UTC, datetime
    runs = tmp_path / "runs"
    rid = make_run(runs, n_cp=2, dt=600.0)
    d = runs / rid
    mf = json.loads((d / "manifest.json").read_text())
    mf["start_epoch"] = synth.START - 90         # PREPARING began 90 s before RUNNING
    mf["end"]["end_epoch"] = synth.START + 1500  # finalizing (scorer drain) took 300 s
    (d / "manifest.json").write_text(json.dumps(mf))
    fin_ts = datetime.fromtimestamp(synth.START + 1200, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    with open(d / "events" / "orchestrator.jsonl", "a") as fh:
        fh.write(json.dumps({"ts": fin_ts, "mono_ns": 999, "run_id": rid, "source": "orchestrator",
                             "type": "state", "seq": 99,
                             "payload": {"from": "RUNNING", "to": "FINALIZING"}}) + "\n")
    ingest(runs, tmp_path / "m.sqlite")
    assert rows(tmp_path / "m.sqlite", "SELECT duration_s FROM runs") == [(1200.0,)]


def test_behavior_events_from_the_selected_pass_and_rebuild_identical(tmp_path):
    r = tmp_path / "runs"
    dc = synth.beh_event("DC", 900.0, "claimed_all_pass", True, "integrity", "stage 1: 0 failing claimed")
    stale = score_pass(2, "old", behavior=[synth.beh_event("AF", 650.0)])
    rescore = score_pass(2, "rescore", behavior=[dc])
    make_run(r, behavior_by_k={1: [synth.beh_event()], 2: [synth.beh_event("AF", 700.0)]},
             extra_passes=[stale, rescore])
    db = tmp_path / "m.sqlite"
    ingest(r, db)
    got = rows(db, "SELECT k, mode, dimension, t_s, detector, severity, hazard, deterministic, evidence "
                   "FROM behavior_events ORDER BY rowid")
    assert got == [(1, "AF", "cost", 100.0, "loop", "signal", 0, 1, "12 cycles"),
                   (2, "DC", "integrity", 900.0, "claimed_all_pass", "hazard", 1, 1, "stage 1: 0 failing claimed")]
    first = dump(db)
    ingest(r, db)
    assert dump(db) == first
