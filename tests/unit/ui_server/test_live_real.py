"""The live endpoints against the real runs directory (read-only). Marked local; skipped when absent."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from tests.unit.ui_server.conftest import AUTH, BASE
from tests.unit.ui_server.live_helpers import (
    CANARY_FORBIDDEN,
    CANARY_HARNESS,
    HAIKU,
    REAL_RUNS,
)
from tests.unit.ui_server.test_stream import events_of, parse_sse
from ui_server.app import create_app
from ui_server.settings import Settings

pytestmark = [pytest.mark.local,
              pytest.mark.skipif(not (REAL_RUNS / HAIKU).is_dir(), reason="real runs not available")]


def stat_tree(root):
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


@pytest.fixture(scope="module")
def real_client(tmp_path_factory):
    from pathlib import Path
    s = Settings(repo_root=Path(__file__).resolve().parents[3], runs_dir=REAL_RUNS, token="t" * 24, port=8765,
                 web_dist=tmp_path_factory.mktemp("nodist"))
    with TestClient(create_app(s), base_url=BASE) as c:
        c.headers.update({**AUTH, "X-LRAE-Token": s.token})
        yield c


def test_real_run_stream_tail_is_fast_and_does_not_load_the_file(real_client):
    t0 = time.monotonic()
    r = real_client.get(f"/api/runs/{HAIKU}/stream", params={"follow": "false"})
    dt = time.monotonic() - t0
    evs = events_of(parse_sse(r.text))
    assert 100 <= len(evs) <= 205 and dt < 3.0, (len(evs), dt)
    assert all(e["level"] == "info" for e in evs)


def test_real_run_full_replay_and_resume(real_client):
    t0 = time.monotonic()
    r = real_client.get(f"/api/runs/{HAIKU}/stream", params={"from": "start"})
    dt = time.monotonic() - t0
    frames = parse_sse(r.text)
    evs = [f for f in frames if f["event"] == "ev"]
    assert len(evs) > 2000 and dt < 20, (len(evs), dt)
    ts = [f["json"]["ts"] for f in evs if f["json"]["ts"]]
    assert ts == sorted(ts), "merged in time order across 8 files"
    mid = evs[len(evs) // 2]
    rest = parse_sse(real_client.get(f"/api/runs/{HAIKU}/stream", headers={"Last-Event-ID": mid["id"]}).text)
    got = [f["json"]["cursor"] for f in rest if f["event"] == "ev" and f["json"]["id"] != "fold:telemetry_stall"]
    want = [f["json"]["cursor"] for f in evs[len(evs) // 2 + 1:] if f["json"]["id"] != "fold:telemetry_stall"]
    assert got == want


def test_real_runs_are_not_modified_by_any_live_endpoint(real_client):
    before = stat_tree(REAL_RUNS)
    for rid in (HAIKU, CANARY_FORBIDDEN, CANARY_HARNESS):
        for path, params in ((f"/api/runs/{rid}/live", {}), (f"/api/runs/{rid}/safety", {}),
                             (f"/api/runs/{rid}/feed", {"from": "tail"}),
                             (f"/api/runs/{rid}/stream", {"follow": "false"})):
            assert real_client.get(path, params=params).status_code == 200, path
    assert stat_tree(REAL_RUNS) == before


def test_real_live_is_cheap_to_poll(real_client):
    real_client.get(f"/api/runs/{HAIKU}/live")
    t0 = time.monotonic()
    for _ in range(10):
        j = real_client.get(f"/api/runs/{HAIKU}/live").json()
    assert (time.monotonic() - t0) / 10 < 0.15
    assert j["state"] == "BUDGET_EXHAUSTED" and j["cost"]["usd"] == pytest.approx(15.00438819)
    assert j["safety"]["status"] == "killed" and j["checkpoints"]["taken"] == 14
