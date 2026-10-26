"""U1 exit check against the real ``runs/`` directory (read-only; skipped when absent)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from spec.loader import REPO_ROOT
from ui_server.app import create_app
from ui_server.settings import Settings

RUNS = REPO_ROOT / "runs"
TOKEN = "t" * 32
BASE = "http://127.0.0.1:8765"

pytestmark = [pytest.mark.local,
              pytest.mark.skipif(not (RUNS / "minidb-v3-pilot-haiku-A-r00-f47fe80e").exists(),
                                 reason="real runs/ not present")]


@pytest.fixture(scope="module")
def client():
    s = Settings(repo_root=REPO_ROOT, runs_dir=RUNS, token=TOKEN, port=8765, web_dist=REPO_ROOT / "nope")
    with TestClient(create_app(s), base_url=BASE) as c:
        c.headers.update({"X-LRAE-Token": TOKEN})
        yield c


def test_every_manifest_run_is_listed(client):
    on_disk = {p.parent.name for p in RUNS.glob("*/manifest.json")}
    listed = {r["run_id"] for r in client.get("/api/runs").json()["runs"]}
    assert on_disk and on_disk <= listed
    assert {"minidb-v3-pilot-haiku-A-r00-f47fe80e", "minidb-v3-blind-A-r00-013c5f62"} <= listed


def test_haiku_pilot_summary_and_checkpoints(client):
    rid = "minidb-v3-pilot-haiku-A-r00-f47fe80e"
    row = next(r for r in client.get("/api/runs").json()["runs"] if r["run_id"] == rid)
    assert row["state"] == "BUDGET_EXHAUSTED" and row["model"] == "claude-haiku-5-5"
    assert row["checkpoints"] == 14 and abs(row["cost_usd"] - 15.0) < 0.1 and row["live"] is False
    cps = client.get(f"/api/runs/{rid}/checkpoints").json()["checkpoints"]
    assert [c["k"] for c in cps] == list(range(1, 15))


def test_status_reports_staleness_consistently(client):
    s = client.get("/api/ingest/status").json()
    listed = client.get("/api/runs").json()["runs"]
    assert s["runs_on_disk"] == len(listed)
    assert sorted(s["missing_from_store"]) == sorted(r["run_id"] for r in listed if not r["ingested"])
    if s["missing_from_store"]:
        assert s["stale"] is True


def test_detail_of_every_run_works_and_leaks_no_home_paths(client):
    for r in client.get("/api/runs").json()["runs"]:
        resp = client.get(f"/api/runs/{r['run_id']}")
        assert resp.status_code == 200, r["run_id"]
        assert "/Users/" not in resp.text.replace(str(REPO_ROOT), "")
