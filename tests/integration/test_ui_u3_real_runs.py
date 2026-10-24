"""U3 data endpoints against the real haiku pilot run (read-only; skipped when the runs dir is absent).

The runs directory comes from ``LRAE_REAL_RUNS`` (default: the main checkout's ``runs/``). Nothing is written
there: the test-matrix check ingests a symlinked copy into a temporary store."""
from __future__ import annotations

import os
import time
import tracemalloc
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from analysis import degradation as dg
from analysis.ingest import ingest
from spec.loader import REPO_ROOT
from ui_server.app import create_app
from ui_server.settings import Settings

RUNS = Path(os.environ.get("LRAE_REAL_RUNS", "/Users/tonylee/Documents/coding/longhorizon_testing/runs"))
RID = "minidb-v3-pilot-haiku-A-r00-f47fe80e"
TOKEN = "t" * 32
BASE = "http://127.0.0.1:8765"

pytestmark = [pytest.mark.local,
              pytest.mark.skipif(not (RUNS / RID / "manifest.json").exists(), reason="real runs/ not present")]


def _snapshot(d: Path) -> dict:
    return {str(p.relative_to(d)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in d.rglob("*") if p.is_file() and "mirror.git" not in p.parts and "snapshots" not in p.parts}


@pytest.fixture(scope="module")
def client():
    s = Settings(repo_root=REPO_ROOT, runs_dir=RUNS, token=TOKEN, port=8765, web_dist=REPO_ROOT / "nope")
    with TestClient(create_app(s), base_url=BASE) as c:
        c.headers.update({"X-LRAE-Token": TOKEN})
        yield c


def test_paging_the_whole_agent_stream_is_fast_and_memory_bounded(client):
    size = (RUNS / RID / "events" / "agent_stream.jsonl").stat().st_size
    assert size > 5_000_000
    client.get(f"/api/runs/{RID}/events/summary")           # builds the index
    tracemalloc.start()
    t0, after, n, worst = time.perf_counter(), None, 0, 0.0
    while True:
        t1 = time.perf_counter()
        r = client.get(f"/api/runs/{RID}/events", params={"source": "agent_stream", "limit": 200,
                                                          **({"after": after} if after else {})})
        worst = max(worst, time.perf_counter() - t1)
        assert r.status_code == 200
        body = r.json()
        n += len(body["events"])
        after = body["next"]
        if body["eof"]:
            break
    total = time.perf_counter() - t0
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    summary = client.get(f"/api/runs/{RID}/events/summary").json()["sources"]["agent_stream"]
    assert n == summary["lines"] and summary["bad_lines"] == 0
    assert worst < 1.0, f"slowest page {worst:.3f}s"
    assert total < 15, f"whole stream in {total:.1f}s"
    assert peak < size, f"peak {peak} bytes while paging a {size}-byte file"


def test_search_and_merged_feed(client):
    t0 = time.perf_counter()
    r = client.get(f"/api/runs/{RID}/events", params={"source": "agent_stream", "q": "pytest", "limit": 20}).json()
    assert r["events"] and time.perf_counter() - t0 < 3
    m = client.get(f"/api/runs/{RID}/events", params={"limit": 500}).json()
    # per-file order is kept; otel lines are written in batches with timestamps up to ~1 s older
    from ui_server.eventlog import ts_epoch
    top = 0.0
    for e in m["events"]:
        t = ts_epoch(e["ts"])
        assert t >= top - 2.0, "merged feed went back in time by more than the otel batch skew"
        top = max(top, t)
    assert len({e["source"] for e in m["events"]}) >= 3 and m["mode"] == "merged"


def test_every_guardrail_violation_links_to_a_transcript_line(client):
    g = client.get(f"/api/runs/{RID}/timeline").json()["guardrail"]
    assert g["violations_total"] == 31 and g["kill"]["rule_id"] == "budget" and g["status"] == "killed"
    assert g["telemetry_stalls"]["count"] == 106 and g["telemetry_stalls"]["resumed"] == 106
    linked = [v for v in g["violations"] if v.get("stream_cursor")]
    assert linked, "no violation resolved to a stream line"
    v = linked[0]
    t = client.get(f"/api/runs/{RID}/transcript", params={"around": v["stream_cursor"], "before": 20,
                                                          "after_n": 5}).json()
    assert t["items"], "no transcript context around the violation"
    assert client.get(f"/api/runs/{RID}/events/at", params={"cursor": v["stream_cursor"]}).json()["event"][
        "seq"] == v["stream_seq"]


def test_timeline_lanes(client):
    b = client.get(f"/api/runs/{RID}/timeline").json()
    assert [c["k"] for c in b["checkpoints"]] == list(range(1, 15))
    assert len(b["stages"]) == 13 and len(b["turns"]) == 13
    assert b["hazards"] and b["compactions"]
    assert b["guardrail"]["kill"]["detect_to_freeze_ms"] is not None
    for c in b["checkpoints"][:2] + b["compactions"][:1]:
        assert client.get(f"/api/runs/{RID}/events/at", params={"cursor": c["cursor"]}).status_code == 200


def test_transcript_filters(client):
    b = client.get(f"/api/runs/{RID}/transcript", params={"tool": "Bash", "limit": 50}).json()
    assert b["items"] and all(i["tool"] == "Bash" for i in b["items"]) and b["total_items"] > 1000
    assert {t["tool"] for t in b["tools"]} >= {"Bash", "Write", "Edit"}
    s = client.get(f"/api/runs/{RID}/transcript", params={"q": "pytest", "limit": 5}).json()
    assert s["items"]
    d = client.get(f"/api/runs/{RID}/transcript/item", params={"cursor": b["items"][0]["cursor"]}).json()
    assert d["event"]["payload"]["tool"] == "Bash" and d["result_text"] is not None


def test_checkpoint_diff_and_scorer_log(client):
    d = client.get(f"/api/runs/{RID}/checkpoints/2/diff").json()
    if not (RUNS / RID / "mirror.git").is_dir():
        pytest.skip("no mirror.git")
    assert d["available"] and d["base_kind"] == "previous_checkpoint" and d["commits"] and d["files"]
    assert d["diff"].startswith("diff --git")
    log = client.get(f"/api/runs/{RID}/checkpoints/1/scorer-log").json()
    assert log["size"] > 0 and log["text"]


def test_tests_matrix_flips_match_degradation(tmp_path):
    """The heatmap's flips equal ``analysis.degradation`` on the same data (ingested into a temp store)."""
    runs = tmp_path / "runs"
    runs.mkdir()
    os.symlink(RUNS / RID, runs / RID)
    db = tmp_path / "m.sqlite"
    ingest(runs, db)

    class S(Settings):
        @property
        def db_path(self) -> Path:
            return db

    s = S(repo_root=REPO_ROOT, runs_dir=RUNS, token=TOKEN, port=8765, web_dist=REPO_ROOT / "nope")
    with TestClient(create_app(s), base_url=BASE) as c:
        c.headers.update({"X-LRAE-Token": TOKEN})
        b = c.get(f"/api/runs/{RID}/tests").json()
    assert b["ingested"] and b["has_outcomes"] and len(b["tests"]) > 20
    assert [(f["t_s"], f["test_id"], f["kind"]) for f in b["flips"]] == [
        (f.t_s, f.test_id, f.kind) for f in dg.flip_events(db, RID)]
    assert b["summary"] == dg.run_summary(db, RID)


def test_nothing_in_the_run_dir_changed(client):
    before = _snapshot(RUNS / RID)
    for path, params in [("events", {"limit": 50}), ("events/summary", {}), ("transcript", {"limit": 20}),
                         ("timeline", {}), ("checkpoints/3/diff", {}), ("checkpoints/3/scorer-log", {})]:
        client.get(f"/api/runs/{RID}/{path}", params=params)
    assert _snapshot(RUNS / RID) == before
