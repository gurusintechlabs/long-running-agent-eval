"""analysis/behavior.py (plan B5b): per-mode survival, incidence, AF anomalies, stuck episodes, security trend."""
import pytest

from analysis import behavior
from analysis.ingest import ingest
from tests.unit.analysis import synth
from tests.unit.analysis.synth import beh_event, hazard, make_run

DC_HZ = beh_event("DC", 900.0, "claimed_all_pass", True, "integrity")
DC_SIG = beh_event("DC", 400.0, "status_missing", False, "integrity")
AF_HZ = beh_event("AF", 100.0, "loop", True, "cost")
GM_J = {**beh_event("GM", 1700.0, "goal_observer.drift", False, "context"), "deterministic": False}


@pytest.fixture
def db(tmp_path, monkeypatch):
    calls = {1: [10, 12, 11], 2: [10, 11, 12], 3: [0, 0, 0]}

    def counters(events_dir, models_yaml=None):
        rid_reps = 1 if "r01" in str(events_dir) else 2 if "r02" in str(events_dir) else 3
        return [{**c, "tool_calls": calls[rid_reps][c["k"] - 1]} for c in synth.fake_counters(events_dir)]
    monkeypatch.setattr("telemetry.counters.interval_counters", counters)
    r = tmp_path / "runs"
    eps = {"episodes": [{"command": "pytest", "start": 0, "end": 4, "attempts": 4, "max_tier": 3,
                         "escalation": 0.8, "t_s": 1250.0}]}
    sec = {"SEC_new": (2.0, {"new_by_severity": {"high": 1, "medium": 1}}), "SEC_open": (3.0, {}),
           "SEC_exploits": (1.0, {"failed": ["e::x"], "active": 4}), "SEC_ai": (2.0, {"reviews": [{"stage": 0}]})}
    make_run(r, repeat=1, n_cp=3, dt=600.0, duration=5400.0, behavior_by_k={1: [AF_HZ], 2: [DC_SIG, DC_HZ], 3: [GM_J]},
             metrics_by_k={2: {"BEH_ED_stuck_episodes": (1.0, eps)}, 3: sec}, stages=[(0, 0.0, False), (1, 650.0, False)])
    make_run(r, repeat=2, n_cp=3, dt=600.0, behavior_by_k={1: [DC_SIG]})
    make_run(r, repeat=3, n_cp=3, dt=600.0, hazards=[hazard("security", 1500.0, "exploit_succeeded")])
    ingest(r, tmp_path / "m.sqlite")
    return tmp_path / "m.sqlite"


def test_mode_survival_uses_the_first_hazard_event_of_the_mode(db):
    g = behavior.mode_survival_inputs(db, "exp-one", "DC")
    assert g == {("L1", "A"): ([900.0, 1800.0, 1800.0], [1, 0, 0])}
    assert behavior.mode_survival_inputs(db, "exp-one", "AF")[("L1", "A")][1] == [1, 0, 0]
    # VI is the security hazard (exploit tests), not a behaviour event
    assert behavior.mode_survival_inputs(db, "exp-one", "VI")[("L1", "A")] == ([5400.0, 1800.0, 1500.0], [0, 0, 1])
    curves = behavior.mode_survival(db, "exp-one")
    assert {c["mode"] for c in curves} == {"AF", "DC", "VI"} and all(c["events"] == 1 for c in curves)


def test_incidence_per_agent_hour_by_run_hour(db):
    rows = behavior.incidence_by_hour(db, "exp-one")
    assert [(r["hour"], round(r["agent_hours"], 3)) for r in rows] == [(0, 2.0), (1, 0.5)]
    h0 = rows[0]["modes"]
    assert h0["DC"] == {"events": 3, "hazards": 1, "per_hour": 1.5}
    assert h0["GM"]["events"] == 1 and rows[1]["modes"] == {}


def test_incidence_by_context_fill_bin(db):
    bins = behavior.incidence_by_fill(db, "exp-one")
    # fill 0.1 / 0.2 / 0.3 per checkpoint: two intervals in [0, .25), one in [.25, .5) per run
    assert [(b["lo"], round(b["agent_hours"], 3)) for b in bins[:2]] == [(0.0, 1.0), (0.25, 0.5)]
    assert bins[0]["modes"]["DC"]["events"] == 3 and bins[1]["modes"]["GM"]["events"] == 1


def test_af_anomalies_flag_spikes_and_drops_against_prior_intervals():
    rates = [10, 12, 11, 9, 10, 11, 80, 10, 0]
    flags = behavior.rate_anomalies(rates, window=6, z=4.0, min_prior=3, drop_frac=0.1)
    assert [(f["i"], f["kind"]) for f in flags] == [(6, "spike"), (8, "drop")]
    assert behavior.rate_anomalies([5] * 10, window=6, z=4.0, min_prior=3, drop_frac=0.1) == []


def test_af_anomalies_for_a_run(db):
    rid = behavior.run_ids(db, "exp-one")[0]
    out = behavior.af_anomalies(db, rid, min_prior=2)
    assert [i["rate_per_min"] for i in out["intervals"]] == [pytest.approx(10 / 10), pytest.approx(12 / 10),
                                                            pytest.approx(11 / 10)]
    assert [e["detector"] for e in out["events"]] == ["loop"]


def test_stuck_episodes_and_escalation(db):
    rid = behavior.run_ids(db, "exp-one")[0]
    eps = behavior.stuck_episodes(db, rid)
    assert eps == [{"k": 2, "t_s": 1250.0, "command": "pytest", "attempts": 4, "max_tier": 3, "escalation": 0.8}]
    assert behavior.escalation_summary(eps) == {"episodes": 1, "escalating": 1, "share_escalating": 1.0,
                                                "max_tier": 3, "reached_tier4": 0}


def test_security_trend_and_timeline(db):
    rid = behavior.run_ids(db, "exp-one")[0]
    tr = behavior.security_trend(db, rid)
    assert tr[-1] == {"k": 3, "t_s": 1800.0, "new_high": 1, "new_medium": 1, "new_low": 0, "open": 3.0,
                      "exploits_failed": 1.0, "exploits_active": 4, "ai_findings": 2.0}
    assert tr[0]["new_high"] is None and tr[0]["exploits_failed"] is None
    tl = behavior.timeline(db, rid)
    assert [(e["mode"], e["detector"], e["severity"]) for e in tl["events"]][:2] == [("AF", "loop", "hazard"),
                                                                                     ("DC", "status_missing", "signal")]
    assert [m["label"] for m in tl["markers"]] == ["stage 0", "stage 1"]
    assert tl["events"][-1]["deterministic"] == 0
    vi = behavior.timeline(db, behavior.run_ids(db, "exp-one")[2])["events"]
    assert [(e["mode"], e["detector"], e["t_s"]) for e in vi] == [("VI", "exploit_succeeded", 1500.0)]


def test_mode_table_counts_runs_events_and_hazards(db):
    t = {r["mode"]: r for r in behavior.mode_table(db, "exp-one")}
    assert (t["DC"]["runs_with_events"], t["DC"]["runs_with_hazard"], t["DC"]["events"]) == (2, 1, 3)
    assert t["GM"]["judge_events"] == 1 and t["VI"]["runs_with_hazard"] == 1
    assert set(t) == set(behavior.ALL_MODES)
