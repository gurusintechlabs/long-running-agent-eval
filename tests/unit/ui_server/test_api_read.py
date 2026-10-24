"""U1 read API: runs are listed from manifests on disk and enriched from the store when ingested."""
from __future__ import annotations

import os


def by_id(rows):
    return {r["run_id"]: r for r in rows}


def test_runs_lists_ingested_and_not_ingested(client, two_runs):
    a, b = two_runs
    rows = by_id(client.get("/api/runs").json()["runs"])
    assert set(rows) == {a, b}
    ra, rb = rows[a], rows[b]
    assert ra["ingested"] is True and rb["ingested"] is False
    assert ra["experiment_id"] == "exp-one" and rb["experiment_id"] == "exp-two"
    assert ra["state"] == "BUDGET_EXHAUSTED" and rb["state"] == "COMPLETED"
    assert ra["model"] == "claude-opus-5-5" and ra["claude_code_version"] == "2.1.301"
    assert ra["cost_usd"] == 4.5 and ra["tokens"] == 1234
    assert ra["checkpoints"] == 3 and rb["checkpoints"] == 2
    assert ra["hazard_count"] == 1 and rb["hazard_count"] is None
    assert ra["duration_s"] is not None and rb["duration_s"] is None
    assert ra["live"] is False and rb["live"] is False


def test_runs_empty_dir(client):
    assert client.get("/api/runs").json()["runs"] == []


def test_non_run_entries_are_ignored(client, two_runs, settings):
    (settings.runs_dir / "_failed").mkdir()
    (settings.runs_dir / "reports").mkdir()
    (settings.runs_dir / "broken").mkdir()
    (settings.runs_dir / "broken" / "manifest.json").write_text("{not json")
    ids = {r["run_id"] for r in client.get("/api/runs").json()["runs"]}
    assert ids == set(two_runs)


def test_runs_sorted_newest_first(client, two_runs, settings):
    from tests.unit.ui_server.conftest import _set_manifest
    a, b = two_runs
    _set_manifest(settings.runs_dir, a, start_epoch=1_800_000_000.0)
    _set_manifest(settings.runs_dir, b, start_epoch=1_800_100_000.0)
    ids = [r["run_id"] for r in client.get("/api/runs").json()["runs"]]
    assert ids == [b, a]


def test_live_run_is_detected(client, live_run):
    r = by_id(client.get("/api/runs").json()["runs"])[live_run]
    assert r["live"] is True and r["state"] == "RUNNING"
    assert r["checkpoints"] == 2


def test_dead_unfinished_run_is_not_live(client, live_run, settings):
    from tests.unit.ui_server.conftest import _set_manifest
    _set_manifest(settings.runs_dir, live_run, harness_pid=2_147_483_000)
    r = by_id(client.get("/api/runs").json()["runs"])[live_run]
    assert r["live"] is False and r["state"] == "UNFINISHED"


def test_pid_of_other_process_without_end_is_live_only_if_alive(client, live_run, settings):
    assert os.getpid() > 0
    assert by_id(client.get("/api/runs").json()["runs"])[live_run]["live"] is True


def test_run_detail(client, two_runs):
    a, _ = two_runs
    d = client.get(f"/api/runs/{a}").json()
    assert d["run"]["run_id"] == a and d["run"]["ingested"] is True
    assert d["manifest"]["spec_hash"] == "abcd1234" * 8
    assert d["manifest"]["seed_commit"] == "s" * 40
    assert d["manifest"]["isolation_mode"] == "local"
    assert d["manifest"]["spec"]["experiment_id"] == "exp-one"
    assert [h["dimension"] for h in d["hazards"]] == ["quality"]
    assert d["hazards"][0]["rule"] == "R>0"


def test_run_detail_not_ingested_has_no_hazards(client, two_runs):
    _, b = two_runs
    d = client.get(f"/api/runs/{b}").json()
    assert d["run"]["ingested"] is False and d["hazards"] == []


def test_run_detail_hides_host_paths(client, two_runs, settings):
    from tests.unit.ui_server.conftest import _set_manifest
    a, _ = two_runs
    _set_manifest(settings.runs_dir, a, claude_home="/Users/x/.claude", paths={"work": "/Users/x/w"},
                  session_id="sess", user_settings_sha256="ff")
    body = client.get(f"/api/runs/{a}").text
    assert "/Users/x" not in body and "sess" not in body


def test_checkpoints_with_metrics(client, two_runs):
    a, _ = two_runs
    d = client.get(f"/api/runs/{a}/checkpoints").json()
    assert d["ingested"] is True
    cps = d["checkpoints"]
    assert [c["k"] for c in cps] == [1, 2, 3]
    assert cps[0]["t_s"] == 600.0 and cps[0]["head_sha"] == "sha1"
    assert set(cps[0]["metrics"]) >= {"P", "R", "D", "C", "W", "X", "S"}
    assert cps[0]["metrics"]["P"] == 0.51 or abs(cps[0]["metrics"]["P"] - 0.51) < 1e-9


def test_checkpoints_not_ingested_fall_back_to_orchestrator_log(client, two_runs):
    _, b = two_runs
    d = client.get(f"/api/runs/{b}/checkpoints").json()
    assert d["ingested"] is False
    assert [c["k"] for c in d["checkpoints"]] == [1, 2]
    assert d["checkpoints"][1]["t_s"] == 1200.0 and d["checkpoints"][1]["metrics"] == {}


def test_experiments_group_runs(client, two_runs):
    exps = by_id_exp(client.get("/api/experiments").json()["experiments"])
    assert set(exps) == {"exp-one", "exp-two"}
    assert exps["exp-one"]["runs"] == 1 and exps["exp-one"]["cost_usd"] == 4.5
    assert exps["exp-one"]["states"] == {"BUDGET_EXHAUSTED": 1}


def by_id_exp(rows):
    return {r["experiment_id"]: r for r in rows}


def test_unknown_and_malicious_run_ids_are_404(client, two_runs):
    for rid in ("nope", "%2e%2e", "a%2fb", "..%2f..%2fetc", "x" * 300):
        assert client.get(f"/api/runs/{rid}").status_code == 404, rid
        assert client.get(f"/api/runs/{rid}/checkpoints").status_code == 404, rid


def test_symlinked_run_dir_outside_runs_is_404(client, settings, tmp_path):
    from tests.unit.analysis.synth import make_run
    other = tmp_path / "other"
    other.mkdir()
    rid = make_run(other, experiment="ext")
    os.symlink(other / rid, settings.runs_dir / "evil")
    assert client.get("/api/runs/evil").status_code == 404
    assert "evil" not in {r["run_id"] for r in client.get("/api/runs").json()["runs"]}


def test_health(client):
    d = client.get("/api/health").json()
    assert d["ok"] is True and "version" in d
