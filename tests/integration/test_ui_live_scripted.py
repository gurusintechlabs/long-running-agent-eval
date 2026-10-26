"""U4 exit check: a real orchestrator run (scripted runtime, no API spend) is followed live by the UI server.

The run happens in this process on a thread; the UI server is a real uvicorn on loopback; the client reads the
SSE response as the frontend will. Asserts: events reach the client within 2 s of being written, the live
snapshot tracks checkpoints and cost, the end is announced, and the server never writes into the run directory.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

import httpx
import pytest

from runner.orchestrator import Run, RunState
from spec.loader import load_spec
from tests.unit.ui_server.live_helpers import snapshot_tree
from tests.unit.ui_server.test_stream import Live, Reader, parse_sse

pytestmark = pytest.mark.local


def test_scripted_run_is_followed_live_and_untouched(env):
    loaded = load_spec(env["spec_path"], repo_root=env["repo_root"])
    rid = loaded.run_id("A", 0)
    runs_dir = env["repo_root"] / "runs"
    out: dict = {}

    def go():
        run = Run(loaded, "A", 0, repo_root=env["repo_root"], claude_home=env["claude_home"], host_home=env["home"])
        out["res"] = run.execute()

    th = threading.Thread(target=go, daemon=True)
    th.start()
    for _ in range(200):
        if (runs_dir / rid / "manifest.json").exists():
            break
        time.sleep(0.05)
    else:
        raise AssertionError("run never started")
    lv = Live(runs_dir)
    rd = Reader(lv, rid, **{"from": "start"})
    http = httpx.Client(base_url=lv.base, headers=lv.headers)
    try:
        snaps = []
        while th.is_alive():
            r = http.get(f"/api/runs/{rid}/live")
            if r.status_code == 200:
                snaps.append(r.json())
            time.sleep(0.3)
        th.join(10)
        assert out["res"].state == RunState.COMPLETED, out["res"].error
        rd.wait_for(lambda f: f["event"] == "run.ended", 15.0)

        evs = [f for _, f in rd.frames if f["event"] == "ev"]
        types = [f["json"]["type"] for f in evs]
        assert types.count("checkpoint") == 4 and "state" in types and "claude_code.api_request" not in types
        # every event reached the client within 2 s of the moment it was logged
        lags = []
        for f in evs:
            ts = f["json"]["ts"]
            if ts:
                lags.append(f["_wall"] - datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
        assert lags and max(lags) < 2.0, max(lags)
        # live snapshots saw the run in progress and the cost grow
        assert any(s["live"] and s["state"] in ("RUNNING", "CHECKPOINTING") for s in snaps)
        assert max(s["checkpoints"]["taken"] for s in snaps) >= 2
        final = http.get(f"/api/runs/{rid}/live").json()
        assert final["state"] == "COMPLETED" and final["ended"] and final["checkpoints"]["taken"] == 4
        assert final["cost"]["usd"] == pytest.approx(0.04) and final["safety"]["status"] == "clear"
        assert final["checkpoints"]["next"] is None
        # reading a finished run changes nothing in it
        before = snapshot_tree(runs_dir / rid)
        http.get(f"/api/runs/{rid}/safety")
        http.get(f"/api/runs/{rid}/feed", params={"from": "start", "limit": 1000})
        again = parse_sse(http.get(f"/api/runs/{rid}/stream", params={"from": "start"}, timeout=30).text)
        assert again[-1]["event"] == "run.ended"
        assert snapshot_tree(runs_dir / rid) == before
    finally:
        rd.close()
        http.close()
        lv.stop()
