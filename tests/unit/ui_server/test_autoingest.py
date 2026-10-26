"""Auto-ingest: the UI server keeps metrics.sqlite current by itself (no stale banner, no manual refresh)."""
from __future__ import annotations

import os
import threading
import time

from ui_server.autoingest import AutoIngest


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _auto(status, *, ok=True, lock=None, **kw):
    clock = Clock()
    calls = []

    def run():
        calls.append(clock.t)
        return ok, "" if ok else "boom: bad scorer.jsonl"
    a = AutoIngest(status_fn=lambda: dict(status), run_fn=run, lock=lock or threading.Lock(), clock=clock,
                   settle_s=3, min_interval_s=20, tail_interval_s=120, retry_s=300, **kw)
    return a, clock, calls


def st(stale=False, key=1.0, runs=1, tail=False):
    return {"stale": stale, "key_mark": [key, runs], "tail_newer": tail}


def test_waits_for_writes_to_settle_then_ingests_once():
    status = st(stale=True, key=5.0)
    a, clock, calls = _auto(status)
    assert a.tick() is None                    # the scorer may still be writing: wait
    clock.t += 2
    assert a.tick() is None
    clock.t += 1.5
    assert a.tick() == "stale" and len(calls) == 1
    status.update(st(stale=False, key=5.0))
    clock.t += 30
    assert a.tick() is None and len(calls) == 1
    s = a.state()
    assert s["enabled"] and s["last_ok"] is True and s["ingests"] == 1 and s["last_error"] is None


def test_a_new_change_restarts_the_settle_window_and_min_interval_holds():
    status = st(stale=True, key=5.0)
    a, clock, calls = _auto(status)
    a.tick()
    clock.t += 4
    assert a.tick() == "stale"
    status.update(st(stale=True, key=6.0))     # next checkpoint scored right away
    clock.t += 4
    assert a.tick() is None                    # changed: settle again
    clock.t += 4
    assert a.tick() is None                    # settled, but only 8 s since the last ingest (< 20)
    clock.t += 13
    assert a.tick() == "stale" and len(calls) == 2


def test_live_log_growth_refreshes_at_the_tail_interval_only():
    status = st(stale=False, tail=True)
    a, clock, calls = _auto(status)
    assert a.tick() == "tail"                  # nothing ingested yet in this server: refresh once
    clock.t += 60
    assert a.tick() is None
    clock.t += 61
    assert a.tick() == "tail" and len(calls) == 2


def test_failure_is_reported_and_not_retried_in_a_loop():
    status = st(stale=True, key=5.0)
    a, clock, calls = _auto(status, ok=False)
    a.tick()
    clock.t += 4
    assert a.tick() == "stale"
    s = a.state()
    assert s["last_ok"] is False and "boom" in s["last_error"]
    for _ in range(5):
        clock.t += 25
        assert a.tick() is None                # same inputs: wait for retry_s or a new change
    status.update(st(stale=True, key=7.0))     # inputs changed: try again after settling
    clock.t += 4
    a.tick()
    clock.t += 4
    assert a.tick() == "stale" and len(calls) == 2


def test_skips_while_a_manual_ingest_holds_the_lock():
    lock = threading.Lock()
    status = st(stale=True, key=5.0)
    a, clock, calls = _auto(status, lock=lock)
    a.tick()
    clock.t += 4
    lock.acquire()
    try:
        assert a.tick() is None and calls == []
    finally:
        lock.release()
    clock.t += 1
    assert a.tick() == "stale"


def test_growing_live_logs_are_not_stale(client, two_runs, runs_dir):
    from analysis.ingest import ingest
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    a, _ = two_runs
    store = runs_dir / "metrics.sqlite"
    past = time.time() - 50
    os.utime(store, (past, past))
    for f in (runs_dir / a / "manifest.json", *(runs_dir / a / "events").glob("*.jsonl"),
              *(runs_dir / two_runs[1] / "manifest.json",), *(runs_dir / two_runs[1] / "events").glob("*.jsonl")):
        os.utime(f, (past - 10, past - 10))
    (runs_dir / a / "events" / "agent_stream.jsonl").write_text("{}\n")   # the agent is still working
    s = client.get("/api/ingest/status").json()
    assert s["stale"] is False and s["tail_newer"] is True and s["reason"] is None
    assert s["auto"]["enabled"] is False


def test_server_auto_ingests_a_new_run(tmp_path, runs_dir, two_runs, monkeypatch):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from tests.unit.ui_server.conftest import AUTH, BASE
    from ui_server import autoingest
    from ui_server.app import create_app
    from ui_server.settings import Settings
    monkeypatch.setattr(autoingest, "POLL_S", 0.05)
    monkeypatch.setattr(autoingest, "SETTLE_S", 0.0)
    s = Settings(repo_root=__import__("pathlib").Path(__file__).resolve().parents[3], runs_dir=runs_dir,
                 token=AUTH["X-LRAE-Token"], port=8765, web_dist=tmp_path / "no-dist")
    with TestClient(create_app(replace(s, auto_ingest=True)), base_url=BASE) as c:
        c.headers.update(AUTH)
        deadline = time.time() + 20
        while time.time() < deadline:
            j = c.get("/api/ingest/status").json()
            if j["runs_in_store"] == 2 and j["auto"]["ingests"] >= 1:
                break
            time.sleep(0.1)
        assert j["runs_in_store"] == 2 and j["stale"] is False, j
        assert j["auto"]["enabled"] and j["auto"]["last_ok"] is True
