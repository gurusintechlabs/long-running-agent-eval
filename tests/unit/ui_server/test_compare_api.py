"""U7 compare + survival API: overlay of runs, KM curves that equal analysis.survival."""
from __future__ import annotations

import pytest

from analysis import survival as sv
from analysis.ingest import ingest
from tests.unit.analysis.synth import hazard, make_run
from tests.unit.ui_server.conftest import BASE, TOKEN


@pytest.fixture
def surv_runs(runs_dir):
    """Experiment exp-s: config A has 3 events and 2 censored runs, config B 1 event and 2 censored."""
    ids = []
    for rep, t in enumerate((300.0, 700.0, 900.0), start=1):
        ids.append(make_run(runs_dir, experiment="exp-s", config="A", repeat=rep, n_cp=3, dt=600.0,
                            hazards=[hazard(t=t)]))
    for rep in (4, 5):
        ids.append(make_run(runs_dir, experiment="exp-s", config="A", repeat=rep, n_cp=3, state="COMPLETED"))
    ids.append(make_run(runs_dir, experiment="exp-s", config="B", repeat=1, n_cp=2, hazards=[hazard(t=500.0)]))
    for rep in (2, 3):
        ids.append(make_run(runs_dir, experiment="exp-s", config="B", repeat=rep, n_cp=2,
                            state="BUDGET_EXHAUSTED"))
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    return ids


@pytest.fixture
def two_ingested(runs_dir):
    a = make_run(runs_dir, experiment="exp-c", config="A", repeat=1, n_cp=3, hazards=[hazard(t=700.0)])
    b = make_run(runs_dir, experiment="exp-c", config="B", repeat=1, n_cp=4,
                 hazards=[hazard(dim="cost", t=1500.0, rule="S")])
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    return a, b


def test_compare_overlays_two_runs(client, two_ingested):
    a, b = two_ingested
    r = client.get("/api/compare", params={"runs": f"{a},{b}"})
    assert r.status_code == 200
    j = r.json()
    assert j["run_ids"] == [a, b] and j["base"] == a and j["not_ingested"] == []
    ra, rb = j["runs"]
    assert [c["k"] for c in ra["checkpoints"]] == [1, 2, 3] and [c["k"] for c in rb["checkpoints"]] == [1, 2, 3, 4]
    p = ra["series"]["P"]
    assert p["k"] == [1, 2, 3] and p["t_s"] == [600.0, 1200.0, 1800.0]
    assert p["value"] == pytest.approx([0.51, 0.52, 0.53])
    assert [h["dimension"] for h in ra["hazards"]] == ["quality"]
    assert [h["dimension"] for h in rb["hazards"]] == ["cost"]
    assert set(ra["counters"]) >= {"cum_cost_usd", "compactions"}
    # aligned by k: union of checkpoints, None where a run has no checkpoint
    al = j["aligned_by_k"]["P"]
    assert al["k"] == [1, 2, 3, 4]
    assert al["values"][a][3] is None and al["values"][b][3] == pytest.approx(0.54)
    # deltas vs the first run
    md = {m["metric"]: m for m in j["metric_deltas"]}
    assert md["P"]["final"][a] == pytest.approx(0.53) and md["P"]["final"][b] == pytest.approx(0.54)
    assert md["P"]["delta_vs_base"][b] == pytest.approx(0.01) and md["P"]["delta_vs_base"][a] is None
    sd = {d["field"]: d for d in j["summary_deltas"]}
    assert sd["checkpoints"]["delta_vs_base"][b] == 1
    assert j["metrics"][:7] == ["P", "R", "D", "C", "W", "X", "S"]
    assert "API-equivalent" in j["cost_note"]


def test_compare_says_so_for_non_ingested_runs(client, two_runs):
    a, b = two_runs
    j = client.get("/api/compare", params={"runs": f"{a},{b}"}).json()
    assert j["not_ingested"] == [b]
    rb = j["runs"][1]
    assert rb["ingested"] is False and rb["series"] == {} and rb["hazards"] == []
    assert len(rb["checkpoints"]) == 2  # times still come from the orchestrator log
    assert any(b in n and "not ingested" in n for n in j["notes"])


def test_compare_rejects_bad_input(client, two_runs):
    a, _ = two_runs
    assert client.get("/api/compare").status_code == 400
    assert client.get("/api/compare", params={"runs": ""}).status_code == 400
    assert client.get("/api/compare", params={"runs": "../etc"}).status_code == 400
    assert client.get("/api/compare", params={"runs": f"{a},..%2f"}).status_code == 400
    assert client.get("/api/compare", params={"runs": f"{a},nope-nope"}).status_code == 404
    many = ",".join(f"r{i}" for i in range(9))
    assert client.get("/api/compare", params={"runs": many}).status_code == 400
    assert client.get("/api/compare", params={"runs": f"{a},{a}"}).json()["run_ids"] == [a]


def test_compare_requires_token(settings, two_runs):
    from fastapi.testclient import TestClient

    from ui_server.app import create_app
    with TestClient(create_app(settings), base_url=BASE) as c:
        assert c.get("/api/compare", params={"runs": two_runs[0]}).status_code == 401
        assert c.get("/api/survival", params={"experiment": "exp-one"}).status_code == 401
        assert c.get("/api/compare", params={"runs": two_runs[0]},
                     headers={"X-LRAE-Token": TOKEN}).status_code == 200


def test_compare_does_not_follow_symlinked_run(client, runs_dir, tmp_path, two_runs):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "manifest.json").write_text("{}")
    (runs_dir / "evil").symlink_to(outside)
    assert client.get("/api/compare", params={"runs": "evil"}).status_code == 404


def test_survival_matches_analysis_survival(client, settings, surv_runs):
    j = client.get("/api/survival", params={"experiment": "exp-s"}).json()
    inputs = sv.survival_inputs(settings.db_path, "exp-s")
    assert [(g["task_class"], g["config"]) for g in j["groups"]] == sorted(inputs)
    for g in j["groups"]:
        ts, es = inputs[(g["task_class"], g["config"])]
        km = sv.kaplan_meier(ts, es)
        s = sv.summarize(ts, es)
        assert g["km"]["times"] == km.times.tolist() and g["km"]["surv"] == km.surv.tolist()
        assert g["km"]["lower"] == km.lower.tolist() and g["km"]["upper"] == km.upper.tolist()
        assert g["median_s"] == s["median"] and g["headline_s"] == s["headline"]
        assert g["median_ci_boot_s"] == list(s["median_ci_boot"])
        assert g["headline_text"] == sv.headline_text(s["headline"]) and g["headline_available"] is True
        assert g["n"] == len(ts) and g["events"] == sum(es) and g["censored"] == len(ts) - sum(es)
    a = next(g for g in j["groups"] if g["config"] == "A")
    assert (a["n"], a["events"], a["censored"]) == (5, 3, 2)
    assert sorted(a["km"]["censor_times"]) == a["km"]["censor_times"] and len(a["km"]["censor_times"]) == 2
    assert a["censored_by_reason"] == {"deadline": 2}
    b = next(g for g in j["groups"] if g["config"] == "B")
    assert b["censored_by_reason"] == {"budget": 2}


def test_survival_config_filter_and_dimension(client, surv_runs):
    j = client.get("/api/survival", params={"experiment": "exp-s", "config": "B"}).json()
    assert [g["config"] for g in j["groups"]] == ["B"]
    j = client.get("/api/survival", params={"experiment": "exp-s", "dimension": "cost"}).json()
    assert all(g["events"] == 0 for g in j["groups"])  # no cost hazards: everything is censored
    assert all(g["headline_available"] for g in j["groups"])


def test_survival_errors(client, runs_dir, surv_runs):
    assert client.get("/api/survival").status_code == 400
    assert client.get("/api/survival", params={"experiment": "../x"}).status_code == 400
    assert client.get("/api/survival", params={"experiment": "exp-s", "config": "a b"}).status_code == 400
    assert client.get("/api/survival", params={"experiment": "missing"}).status_code == 404


def test_survival_without_store(client):
    r = client.get("/api/survival", params={"experiment": "exp-s"})
    assert r.status_code == 404 and "ingest" in r.json()["detail"]


def test_survival_json_is_finite(client, surv_runs):
    r = client.get("/api/survival", params={"experiment": "exp-s"})
    assert "NaN" not in r.text and "Infinity" not in r.text
