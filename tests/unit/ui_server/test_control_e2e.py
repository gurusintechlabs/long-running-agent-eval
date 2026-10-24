"""U5 exit check with the REAL ``lrae`` CLI as subprocess and the scripted runtime (no spend):
validate -> preview -> launch -> stop -> resume from t2 -> completes; hard kill -> clean."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from runner import memory
from runner.procs import find_in_dir
from tests.unit.ui_server import control_support as cs
from tests.unit.ui_server.conftest import PORT, TOKEN
from ui_server.settings import Settings

pytestmark = pytest.mark.local


def wait_for(cond, timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def live(tmp_path):
    r = cs.make_repo(tmp_path)
    settings = Settings(repo_root=r["repo"], runs_dir=r["runs"], token=TOKEN, port=PORT, web_dist=tmp_path / "x")

    def edit(ctl):
        c = ctl.cfg
        c.code_root = cs.CODE_ROOT
        c.global_argv = ["--claude-home", str(r["claude"]), "--home", str(r["home"])]
        c.run_argv = ["--no-score", "--no-caffeinate"]
        c.resume_argv = ["--no-caffeinate"]
        c.extra_env = {"HOME": str(r["home"])}
        c.launch_wait_s = 60.0

    app, client = cs.make_client(settings, edit)
    yield SimpleNamespace(r=r, c=client, ctl=app.state.control)
    j = app.state.control.job
    if j and j["proc"].poll() is None:
        j["proc"].kill()
        j["proc"].wait(timeout=10)


def manifest(live, rid):
    return json.loads((live.r["runs"] / rid / "manifest.json").read_text())


def ended(live, rid):
    def f():
        try:
            return "end" in manifest(live, rid)
        except (OSError, ValueError):
            return False
    return f


def test_launch_stop_resume_end_to_end(live):
    c, r = live.c, live.r
    pv = c.post("/api/launch/preview", json={"spec_path": r["rel"], "config": "A", "repeat": 0}).json()
    assert pv["estimate"]["real_spend"] is False
    rid = pv["estimate"]["run_ids"][0]

    res = c.post("/api/launch", json={"nonce": pv["confirmation_nonce"]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["manifest_seen"] and body["run_id"] == rid
    st = c.get("/api/control/state").json()
    assert st["active"] and st["run"]["pid"] == body["pid"] and st["launch_allowed"] is False

    # the UI refuses a second launch while the first drives
    pv2 = c.post("/api/launch/preview", json={"spec_path": r["rel"], "config": "A", "repeat": 1}).json()
    assert c.post("/api/launch", json={"nonce": pv2["confirmation_nonce"]}).status_code == 409

    art = r["runs"] / rid
    assert wait_for(lambda: (art / "snapshots" / "t2" / "meta.json").exists()), "t2 never appeared"
    stop = c.post(f"/api/runs/{rid}/stop")
    assert stop.status_code == 200 and stop.json()["signalled"] == "SIGINT"
    assert wait_for(ended(live, rid), 60), "run did not finalize after SIGINT"
    m = manifest(live, rid)
    # documented behaviour: KeyboardInterrupt goes through Run.execute's finally -> FAILED, cleaned up
    assert m["end"]["state"] == "FAILED", m["end"]
    work = r["home"] / "lrae-work" / rid
    assert not work.exists() and not find_in_dir(work.parent), "agent and work dir cleaned by finalize"
    assert not memory.state_dir(work / "workspace", r["claude"]).exists()
    assert wait_for(lambda: live.ctl.state()["launch_allowed"], 20)

    # resume from t2 (scripted, no spend: no nonce confirmation fields needed)
    rp = c.post(f"/api/runs/{rid}/resume/preview", json={"from": "t2"})
    assert rp.status_code == 200, rp.text
    rr = c.post(f"/api/runs/{rid}/resume", json={"from": "t2", "nonce": rp.json()["confirmation_nonce"]})
    assert rr.status_code in (200, 202), rr.text
    assert wait_for(lambda: manifest(live, rid).get("resumed") is True and "end" in manifest(live, rid), 90)
    m = manifest(live, rid)
    assert m["end"]["state"] == "COMPLETED", (m["end"], live.ctl.state()["log_tail"])
    for k in range(1, 5):
        assert (art / "snapshots" / f"t{k}" / "meta.json").exists()
    assert wait_for(lambda: live.ctl.state()["launch_allowed"], 30)


def test_hard_kill_then_clean(live):
    c, r = live.c, live.r
    pv = c.post("/api/launch/preview", json={"spec_path": r["rel"], "config": "A", "repeat": 0}).json()
    rid = pv["estimate"]["run_ids"][0]
    assert c.post("/api/launch", json={"nonce": pv["confirmation_nonce"]}).status_code == 200
    art = r["runs"] / rid
    assert wait_for(lambda: (art / "snapshots" / "t1" / "meta.json").exists())
    assert c.post(f"/api/runs/{rid}/kill", json={"confirm": rid}).json()["signalled"] == "SIGKILL"
    # kill runs `lrae clean`, which finishes what the dead harness left
    m = manifest(live, rid)
    assert m["end"]["state"] == "INTERRUPTED" and m["end"].get("recovered") is True
    work = r["home"] / "lrae-work" / rid
    assert not work.exists() and not find_in_dir(work.parent)
    assert c.post("/api/clean").json()["finished"] is True
