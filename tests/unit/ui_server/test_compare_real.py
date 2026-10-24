"""Compare, survival and reports against the real runs dir (read-only). Marked local; skipped when absent.

Report rebuilds never touch the real dir: they run on a temp copy of one small run.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from analysis import survival as sv
from analysis.ingest import ingest
from tests.unit.ui_server.conftest import AUTH, BASE
from tests.unit.ui_server.live_helpers import REAL_RUNS
from ui_server.app import create_app
from ui_server.settings import Settings

EARLY = "minidb-v2-early-A-r00-338286d0"
BLIND = "minidb-v3-blind-A-r00-013c5f62"
SCRIPTED = ["pilot-export-csv-scripted-A-r00-8a533d8c", "pilot-export-csv-scripted-A-r01-8a533d8c"]
REPO = Path(__file__).resolve().parents[3]

pytestmark = [pytest.mark.local,
              pytest.mark.skipif(not (REAL_RUNS / EARLY).is_dir() or not (REAL_RUNS / "metrics.sqlite").is_file(),
                                 reason="real runs not available")]


def mk_settings(runs_dir: Path, tmp: Path) -> Settings:
    return Settings(repo_root=REPO, runs_dir=runs_dir, token="t" * 24, port=8765, web_dist=tmp / "nodist")


@pytest.fixture(scope="module")
def real_client(tmp_path_factory):
    s = mk_settings(REAL_RUNS, tmp_path_factory.mktemp("nd"))
    with TestClient(create_app(s), base_url=BASE) as c:
        c.headers.update({**AUTH, "X-LRAE-Token": s.token})
        yield c, s


def test_real_compare_two_experiments(real_client):
    c, _ = real_client
    t0 = time.monotonic()
    j = c.get("/api/compare", params={"runs": f"{EARLY},{BLIND}"}).json()
    assert time.monotonic() - t0 < 3
    assert j["not_ingested"] == [] and j["run_ids"] == [EARLY, BLIND]
    for r in j["runs"]:
        assert r["series"]["P"]["k"] and r["counters"]["cum_cost_usd"]["value"]
        assert len(r["series"]["P"]["t_s"]) == len(r["series"]["P"]["value"])
    assert j["runs"][0]["hazards"], "the early run has hazards"
    assert {d["field"] for d in j["summary_deltas"]} >= {"cost_usd", "ttfh_s"}


def test_real_compare_scripted_repeats(real_client):
    c, _ = real_client
    j = c.get("/api/compare", params={"runs": ",".join(SCRIPTED)}).json()
    assert j["not_ingested"] == [] and len(j["runs"]) == 2
    assert j["aligned_by_k"]["P"]["k"]


def test_real_survival_equals_analysis(real_client):
    c, s = real_client
    j = c.get("/api/survival", params={"experiment": "pilot-export-csv-scripted"}).json()
    inputs = sv.survival_inputs(s.db_path, "pilot-export-csv-scripted")
    (g,) = j["groups"]
    ts, es = inputs[(g["task_class"], g["config"])]
    km = sv.kaplan_meier(ts, es)
    assert g["km"]["surv"] == km.surv.tolist() and g["km"]["times"] == km.times.tolist()
    assert g["median_s"] == sv.summarize(ts, es)["median"] and g["n"] == 2


def test_real_reports_listing_and_serving(real_client):
    c, s = real_client
    j = c.get("/api/reports").json()
    ids = {e["experiment_id"]: e for e in j["experiments"]}
    assert ids["minidb-v2-early"]["has_reports"]
    e = ids["minidb-v2-early"]
    if e["dashboard"]:
        r = c.get("/api/reports/minidb-v2-early/file", params={"name": "dashboard.html"})
        assert r.status_code == 200 and r.headers["content-security-policy"].startswith("sandbox")
    assert c.get("/api/reports/minidb-v2-early/file", params={"name": "../metrics.sqlite"}).status_code == 404


def test_rebuild_on_a_temp_copy_of_one_small_run(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    shutil.copytree(REAL_RUNS / SCRIPTED[0], runs / SCRIPTED[0])
    ingest(runs, runs / "metrics.sqlite")
    s = mk_settings(runs, tmp_path)
    before = (REAL_RUNS / "reports").stat().st_mtime_ns
    with TestClient(create_app(s), base_url=BASE) as c:
        c.headers.update({**AUTH, "X-LRAE-Token": s.token})
        r = c.post("/api/reports/pilot-export-csv-scripted/rebuild", json={"kind": "dashboard"})
        assert r.status_code == 200, r.text
        assert (runs / "reports" / "pilot-export-csv-scripted" / "dashboard.html").is_file()
    assert (REAL_RUNS / "reports").stat().st_mtime_ns == before
