"""Store freshness and the re-ingest action."""
from __future__ import annotations

import os
import time


def test_no_store_is_stale(client, runs_dir):
    from tests.unit.analysis.synth import make_run
    make_run(runs_dir, experiment="e")
    s = client.get("/api/ingest/status").json()
    assert s["store_exists"] is False and s["stale"] is True
    assert s["runs_on_disk"] == 1 and s["runs_in_store"] == 0 and len(s["missing_from_store"]) == 1


def test_fresh_store(client, two_runs, runs_dir):
    from analysis.ingest import ingest
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    future = time.time() + 5
    os.utime(runs_dir / "metrics.sqlite", (future, future))
    s = client.get("/api/ingest/status").json()
    assert s["stale"] is False and s["missing_from_store"] == [] and s["reason"] is None


def test_run_missing_from_store_is_stale(client, two_runs):
    _, b = two_runs
    s = client.get("/api/ingest/status").json()
    assert s["stale"] is True and s["missing_from_store"] == [b]
    assert "not in the store" in s["reason"]


def test_newer_logs_than_store_are_stale(client, two_runs, runs_dir):
    from analysis.ingest import ingest
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    old = time.time() - 100
    os.utime(runs_dir / "metrics.sqlite", (old, old))
    s = client.get("/api/ingest/status").json()
    assert s["stale"] is True and "newer" in s["reason"]
    assert s["newest_log_epoch"] > s["store_epoch"]


def test_post_ingest_rebuilds_and_clears_stale(client, two_runs):
    _, b = two_runs
    r = client.post("/api/ingest")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    s = client.get("/api/ingest/status").json()
    assert s["missing_from_store"] == [] and s["runs_in_store"] == 2
    rows = {x["run_id"]: x for x in client.get("/api/runs").json()["runs"]}
    assert rows[b]["ingested"] is True


def test_ingest_failure_is_reported(client, settings, monkeypatch):
    from ui_server import app as app_mod
    monkeypatch.setattr(app_mod, "INGEST_CMD", ["python3", "-c", "import sys; print('boom'); sys.exit(3)"])
    r = client.post("/api/ingest")
    assert r.status_code == 500 and r.json()["ok"] is False and "boom" in r.json()["output"]


def test_ingest_is_single_flight(client, settings, monkeypatch):
    import threading

    from ui_server import app as app_mod
    monkeypatch.setattr(app_mod, "INGEST_CMD", ["python3", "-c", "import time; time.sleep(1.5)"])
    out = {}
    t = threading.Thread(target=lambda: out.update(first=client.post("/api/ingest").status_code))
    t.start()
    time.sleep(0.5)
    second = client.post("/api/ingest").status_code
    t.join()
    assert second == 409 and out["first"] == 200


def test_ingest_subprocess_env_is_scrubbed(settings):
    from ui_server.app import ingest_env
    env = ingest_env({"PATH": "/bin", "HOME": "/h", "ANTHROPIC_API_KEY": "k", "AWS_SECRET_ACCESS_KEY": "s",
                      "LRAE_CONFIRM_SPEND": "1"})
    assert env["PATH"] == "/bin"
    assert not {"ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "LRAE_CONFIRM_SPEND", "HOME"} & set(env)
