"""U5 control backend: spend gate (UI-3), one run at a time, path allowlist, env (UI-7), signals.

The spawner is always a fake: no ``lrae`` process is ever started here, and no claude_code run can be.
"""
from __future__ import annotations

import os
import signal
import threading
import time
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.unit.ui_server import control_support as cs
from tests.unit.ui_server.conftest import AUTH, BASE, PORT, TOKEN
from ui_server import control_core as cc
from ui_server.app import create_app
from ui_server.settings import Settings


def build_rig(tmp_path, **kw):
    r = cs.make_repo(tmp_path, **kw)
    settings = Settings(repo_root=r["repo"], runs_dir=r["runs"], token=TOKEN, port=PORT,
                        web_dist=tmp_path / "nodist")
    spawner = cs.FakeSpawner()
    clock = [1000.0]

    def edit(ctl):
        ctl.cfg.spawner = spawner
        ctl.cfg.launch_wait_s = 0.2
        ctl.cfg.code_root = cs.CODE_ROOT
        ctl.cfg.clock = lambda: clock[0]
        ctl.nonces.clock = lambda: clock[0]

    app, client = cs.make_client(settings, edit)
    return SimpleNamespace(r=r, settings=settings, spawner=spawner, app=app, c=client, clock=clock,
                           ctl=app.state.control, spec=r["spec"], rel=r["rel"])


@pytest.fixture
def rig(tmp_path):
    return build_rig(tmp_path)


@pytest.fixture
def rig_real(tmp_path):
    """A claude_code spec. It is only ever loaded and previewed; the spawner is the fake."""
    (tmp_path / "real").mkdir()
    return build_rig(tmp_path / "real", runtime="claude_code", name="ctl-real")


def preview(rig, **kw):
    body = {"spec_path": rig.rel, **kw}
    return rig.c.post("/api/launch/preview", json=body)


def launch(rig, nonce, **kw):
    return rig.c.post("/api/launch", json={"nonce": nonce, **kw})


def good_nonce(rig, **kw):
    r = preview(rig, **kw)
    assert r.status_code == 200, r.text
    return r.json()["confirmation_nonce"]


# -- auth / origin on every POST -----------------------------------------------------------------

POSTS = [
    ("/api/launch/preview", {"spec_path": "spec/examples/ctl-test.yaml"}),
    ("/api/launch", {"nonce": "x"}),
    ("/api/runs/r1/stop", None),
    ("/api/runs/r1/kill", {"confirm": "r1"}),
    ("/api/runs/r1/resume/preview", {"from": "t1"}),
    ("/api/runs/r1/resume", {"from": "t1", "nonce": "x"}),
    ("/api/runs/r1/score", None),
    ("/api/clean", None),
]


@pytest.mark.parametrize("path,body", POSTS)
def test_every_post_needs_the_token(rig, path, body):
    with TestClient(create_app(rig.settings), base_url=BASE) as c:
        assert c.post(path, json=body).status_code == 401
        assert c.post(path, json=body, headers={"X-LRAE-Token": "wrong"}).status_code == 401
        assert c.get("/api/control/state").status_code == 401


@pytest.mark.parametrize("path,body", POSTS)
def test_every_post_rejects_a_foreign_origin(rig, path, body):
    for origin in ("http://evil.example", "http://127.0.0.1:9999", "null"):
        r = rig.c.post(path, json=body, headers={"Origin": origin})
        assert r.status_code == 403, (path, origin)
    assert rig.spawner.calls == []


def test_foreign_host_rejected(rig):
    assert rig.c.post("/api/launch/preview", json={}, headers={"Host": "evil.example"}).status_code in (400, 403)


# -- path allowlist ------------------------------------------------------------------------------

def test_spec_path_allowlist(rig, tmp_path):
    outside = tmp_path / "outside.yaml"
    outside.write_text(rig.spec.read_text())
    (rig.r["repo"] / "spec" / "link.yaml").symlink_to(outside)
    (rig.r["repo"] / "other.yaml").write_text(rig.spec.read_text())
    (rig.r["repo"] / "spec" / "examples" / "notes.txt").write_text("x")
    bad = ["../outside.yaml", "../../outside.yaml", "/etc/passwd", str(outside), "spec/../other.yaml",
           "spec/examples/../../other.yaml", "spec/link.yaml", "spec/examples/notes.txt", "spec",
           "other.yaml", "", "spec/examples/ctl-test.yaml\0.txt", "~/x.yaml", "spec/examples/" + "a" * 600 + ".yaml"]
    for p in bad:
        r = rig.c.post("/api/launch/preview", json={"spec_path": p})
        assert r.status_code in (403, 404, 422), (p, r.status_code, r.text)
        assert "confirmation_nonce" not in r.text, p
    assert rig.ctl.nonces.pending() == 0


def test_draft_names_are_strict(rig):
    drafts = rig.r["repo"] / "spec" / "drafts"
    drafts.mkdir()
    (drafts / "mine.yaml").write_text(rig.spec.read_text().replace("../assets", "../assets"))
    for d in ["../examples/ctl-test.yaml", "a/b.yaml", "..", "mine", "x.txt", "/etc/passwd", ".hidden.yaml"]:
        assert rig.c.post("/api/launch/preview", json={"draft": d}).status_code in (403, 404, 422), d
    ok = rig.c.post("/api/launch/preview", json={"draft": "mine.yaml"})
    assert ok.status_code == 200 and ok.json()["estimate"]["spec_path"] == "spec/drafts/mine.yaml"


def test_exactly_one_spec_ref(rig):
    assert rig.c.post("/api/launch/preview", json={}).status_code == 422
    assert rig.c.post("/api/launch/preview", json={"spec_path": rig.rel, "draft": "a.yaml"}).status_code == 422


def test_invalid_spec_is_422(rig):
    rig.spec.write_text("spec_version: 2\n")
    r = preview(rig)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "spec_invalid"


# -- preview: server-computed estimate -----------------------------------------------------------

def test_preview_estimate_comes_from_the_spec(rig):
    body = preview(rig).json()
    e = body["estimate"]
    assert e["runtime"] == "scripted" and e["real_spend"] is False
    assert e["run_count"] == 2 and len(e["run_ids"]) == 2 and e["run_ids"][0].startswith("ctl-test-A-r00-")
    assert e["per_run_usd"] == 3.0 and e["experiment_usd"] == 5.0 and e["max_spend_usd"] == 6.0 and e["nominal_cap_usd"] == 5.0
    assert e["checkpoint_count"] == 4 and abs(e["duration_min"] - 0.1) < 1e-9
    assert e["spec_hash"] and body["confirmation"] == {"required": False}
    assert body["confirmation_nonce"] and body["expires_in_s"] == cc.NONCE_TTL_S
    assert body["launch_allowed_now"] is True


def test_client_cannot_inject_numbers(rig):
    for extra in ({"per_run_usd": 0.01}, {"estimate": {"max_spend_usd": 0}}, {"real_spend": False}):
        assert rig.c.post("/api/launch/preview", json={"spec_path": rig.rel, **extra}).status_code == 422


def test_selection_and_bad_selection(rig):
    e = preview(rig, config="A", repeat=1).json()["estimate"]
    assert e["run_count"] == 1 and e["repeats"] == [1] and e["max_spend_usd"] == 3.0
    for bad in ({"config": "B"}, {"repeat": 2}, {"repeat": -1}, {"repeat": [0, 0]}, {"repeat": []}):
        assert preview(rig, **bad).status_code == 422, bad


def test_existing_run_folder_blocks_the_nonce(rig):
    rid = preview(rig).json()["estimate"]["run_ids"][0]
    (rig.r["runs"] / rid).mkdir()
    b = preview(rig).json()
    assert b["conflicts"] == [rid] and b["confirmation_nonce"] is None and b["blockers"]


def test_claude_code_preview_flags_real_spend(rig_real):
    b = preview(rig_real).json()
    e = b["estimate"]
    assert e["real_spend"] is True and e["runtime"] == "claude_code"
    assert b["confirmation"]["required"] is True
    assert b["confirmation"]["fields"] == {"confirm_usd": 6.0, "confirm_runs": 2}
    assert rig_real.spawner.calls == []


def test_real_judge_with_scripted_agent_is_real_spend(tmp_path):
    rig = build_rig(tmp_path, judge="claude_code")
    e = preview(rig).json()["estimate"]
    assert e["runtime"] == "scripted" and e["real_spend"] is True
    assert any("judge" in r for r in e["spend_reasons"])


# -- spend gate ----------------------------------------------------------------------------------

def test_no_nonce_never_launches(rig, rig_real):
    for rg in (rig, rig_real):
        assert rg.c.post("/api/launch", json={}).status_code == 422
        for n in ("", "nope", "x" * 5000):
            assert launch(rg, n).status_code == 400
        assert launch(rg, None).status_code == 422
        assert launch(rg, "n", confirm_usd=5.0, confirm_runs=2).status_code == 400
        assert rg.spawner.calls == []


def test_scripted_launch_uses_no_confirm_spend(rig):
    n = good_nonce(rig, config="A", repeat=0)
    r = launch(rig, n, confirm_usd=5.0, confirm_runs=1)    # extra confirmation is ignored, never forwarded
    assert r.status_code == 202, r.text    # the fake never writes a manifest
    (call,) = rig.spawner.calls
    a = call["argv"]
    assert "--confirm-spend" not in a and a[a.index("run") + 1].endswith("ctl-test.yaml")
    assert a[a.index("--config") + 1] == "A" and a[a.index("--repeat") + 1] == "0"
    assert call["cwd"] == cs.CODE_ROOT and "LRAE_CONFIRM_SPEND" not in call["env"]
    assert r.json()["run_ids"] == preview_ids(rig, config="A", repeat=0)


def preview_ids(rig, **kw):
    return rig.c.post("/api/launch/preview", json={"spec_path": rig.rel, **kw}).json()["estimate"]["run_ids"]


def test_nonce_is_single_use(rig):
    n = good_nonce(rig)
    assert launch(rig, n).status_code == 202
    rig.spawner.calls[0]["proc"].finish(0)
    r = launch(rig, n)
    assert r.status_code == 400 and "already used" in r.json()["detail"]["message"]
    assert len(rig.spawner.calls) == 1


def test_expired_nonce(rig):
    n = good_nonce(rig)
    rig.clock[0] += cc.NONCE_TTL_S + 1
    r = launch(rig, n)
    assert r.status_code == 400 and "expired" in r.json()["detail"]["message"]
    assert rig.spawner.calls == [] and rig.ctl.nonces.pending() == 0


def test_nonce_of_another_kind_is_refused(rig):
    n = good_nonce(rig)
    assert rig.c.post("/api/runs/x1/resume", json={"from": "t1", "nonce": n}).status_code in (400, 404)
    assert rig.spawner.calls == []


def test_editing_the_spec_after_preview_invalidates_the_nonce(rig):
    n = good_nonce(rig)
    spec = yaml.safe_load(rig.spec.read_text())
    spec["budget"]["per_run_usd"] = 300.0
    rig.spec.write_text(yaml.safe_dump(spec))
    r = launch(rig, n)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "spec_changed"
    assert rig.spawner.calls == []
    assert launch(rig, n).status_code == 400          # burned, not retryable


def test_editing_a_referenced_file_invalidates_the_nonce(rig):
    n = good_nonce(rig)
    (rig.r["assets"] / "prompt.md").write_text("Do something else, expensively.\n")
    assert launch(rig, n).status_code == 409 and rig.spawner.calls == []


def test_spec_deleted_after_preview(rig):
    n = good_nonce(rig)
    rig.spec.unlink()
    assert launch(rig, n).status_code == 409 and rig.spawner.calls == []


def test_real_spend_needs_the_typed_confirmation(rig_real):
    n = good_nonce(rig_real)
    bad = [{}, {"confirm_usd": 5.0}, {"confirm_runs": 2}, {"confirm_usd": 3.0, "confirm_runs": 2},
           {"confirm_usd": 5.0, "confirm_runs": 1}, {"confirm_usd": "abc", "confirm_runs": 2},
           {"confirm_usd": 500.0, "confirm_runs": 2}, {"confirm_usd": True, "confirm_runs": 2}]
    for b in bad[:2]:
        r = launch(rig_real, n, **b)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "confirmation_mismatch", b
    assert rig_real.spawner.calls == []
    # the nonce is burned after three wrong confirmations: the right one then fails too
    launch(rig_real, n, **bad[2])
    assert launch(rig_real, n, confirm_usd=5.0, confirm_runs=2).status_code == 400
    assert rig_real.spawner.calls == []
    # each wrong shape on its own nonce
    for b in bad:
        n2 = good_nonce(rig_real)
        assert launch(rig_real, n2, **b).status_code == 422, b
    assert rig_real.spawner.calls == []


def test_real_spend_confirmed_passes_the_flag_only_here(rig_real):
    n = good_nonce(rig_real)
    r = launch(rig_real, n, confirm_usd="6.00", confirm_runs=2)
    assert r.status_code == 202, r.text
    (call,) = rig_real.spawner.calls
    assert call["argv"].count("--confirm-spend") == 1 and "run" in call["argv"]
    # the flag is the only channel: no spend variable in the environment
    assert not any(k.startswith("LRAE_") for k in call["env"])


def test_real_spend_client_cannot_lower_the_cap_it_confirms(rig_real):
    n = good_nonce(rig_real, config="A", repeat=0)       # one run: max spend 3.00
    assert launch(rig_real, n, confirm_usd=5.0, confirm_runs=1).status_code == 422
    assert launch(rig_real, n, confirm_usd=3.0, confirm_runs=1).status_code == 202


def test_launch_body_rejects_unknown_fields(rig):
    n = good_nonce(rig)
    r = rig.c.post("/api/launch", json={"nonce": n, "extra_args": ["--confirm-spend"]})
    assert r.status_code == 422 and rig.spawner.calls == []


# -- one run at a time ---------------------------------------------------------------------------

def test_second_launch_while_active_is_409_and_keeps_the_nonce(rig):
    n1 = good_nonce(rig)
    assert launch(rig, n1).status_code == 202
    n2 = preview(rig).json()["confirmation_nonce"]
    r = launch(rig, n2)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "run_active"
    assert len(rig.spawner.calls) == 1
    assert rig.ctl.nonces.pending() == 1                 # not burned by a busy refusal
    rig.spawner.calls[0]["proc"].finish(0)               # the run ends: the same nonce now works
    assert launch(rig, n2).status_code == 202 and len(rig.spawner.calls) == 2


def test_concurrent_launches_start_exactly_one(rig):
    nonces = [good_nonce(rig) for _ in range(6)]
    clients = [TestClient(rig.app, base_url=BASE) for _ in nonces]
    for c in clients:
        c.headers.update(AUTH)
    gate = threading.Barrier(len(nonces))
    out = []

    def go(c, n):
        gate.wait()
        out.append(c.post("/api/launch", json={"nonce": n}).status_code)

    ts = [threading.Thread(target=go, args=(c, n)) for c, n in zip(clients, nonces, strict=True)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(out) == [202] + [409] * 5, out
    assert len(rig.spawner.calls) == 1


def test_concurrent_launches_with_the_same_nonce(rig):
    n = good_nonce(rig)
    clients = [TestClient(rig.app, base_url=BASE) for _ in range(4)]
    for c in clients:
        c.headers.update(AUTH)
    gate = threading.Barrier(4)
    out = []

    def go(c):
        gate.wait()
        out.append(c.post("/api/launch", json={"nonce": n}).status_code)

    ts = [threading.Thread(target=go, args=(c,)) for c in clients]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out.count(202) == 1 and len(rig.spawner.calls) == 1, out


def test_launch_refused_while_a_verified_harness_is_alive(rig):
    p = cs.spawn_lookalike(rig.r["tmp"], str(rig.spec), repo=rig.r["repo"])
    try:
        time.sleep(0.3)
        cs.write_manifest(rig.r["runs"], "other-run", harness_pid=p.pid, spec_path=str(rig.spec), start_epoch=time.time() - 1)
        n = good_nonce(rig)
        r = launch(rig, n)
        assert r.status_code == 409 and r.json()["detail"]["run"]["run_id"] == "other-run"
        assert rig.spawner.calls == []
        st = rig.c.get("/api/control/state").json()
        assert st["active"] and st["run"]["run_id"] == "other-run" and st["launch_allowed"] is False
    finally:
        p.kill()
        p.wait()


def test_a_dead_or_foreign_pid_in_a_manifest_does_not_block(rig):
    import subprocess
    import sys
    decoy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        cs.write_manifest(rig.r["runs"], "stale-1", harness_pid=cs.FAKE_PID)
        cs.write_manifest(rig.r["runs"], "stale-2", harness_pid=decoy.pid)     # pid reused by a stranger
        cs.write_manifest(rig.r["runs"], "done", harness_pid=os.getpid(), end={"state": "COMPLETED"})
        assert rig.c.get("/api/control/state").json()["launch_allowed"] is True
        assert launch(rig, good_nonce(rig)).status_code == 202
    finally:
        decoy.kill()
        decoy.wait()


def test_two_servers_cannot_both_start(rig, tmp_path):
    """The flock in ui_state/ also serialises a second UI process."""
    import fcntl
    rig.ctl.cfg.state_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(rig.ctl.cfg.state_dir / "control.lock", os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert launch(rig, good_nonce(rig)).status_code == 409 and rig.spawner.calls == []
    finally:
        os.close(fd)


# -- subprocess env (UI-7) and log placement (UI-6) ----------------------------------------------

def test_subprocess_env_is_minimal(rig, monkeypatch):
    secrets = {"ANTHROPIC_API_KEY": "sk-secret", "AWS_SECRET_ACCESS_KEY": "aws", "GITHUB_TOKEN": "gh",
               "OPENAI_API_KEY": "oa", "LRAE_CONFIRM_SPEND": "1", "SSH_AUTH_SOCK": "/s", "MY_TOKEN": "t",
               "CLAUDE_CODE_OAUTH_TOKEN": "c", "PYTHONPATH": "/evil", "LD_PRELOAD": "/evil.so"}
    for k, v in secrets.items():
        monkeypatch.setenv(k, v)
    assert launch(rig, good_nonce(rig)).status_code == 202
    env = rig.spawner.calls[0]["env"]
    assert set(env) <= set(cc.ENV_ALLOW) | set(cc.ENV_FORCE), set(env)
    assert env["HOME"] == os.environ["HOME"] and "PATH" in env
    assert not (set(secrets) & set(env))
    assert "sk-secret" not in repr(rig.spawner.calls)


def test_build_env_refuses_secret_names_in_extra():
    for k in ("ANTHROPIC_API_KEY", "AWS_PROFILE", "LRAE_CONFIRM_SPEND", "GITHUB_TOKEN"):
        with pytest.raises(ValueError):
            cc.build_env({"PATH": "/bin"}, {k: "x"})


def test_log_lives_in_ui_state_not_in_the_work_dir(rig):
    assert launch(rig, good_nonce(rig)).status_code == 202
    log = rig.spawner.calls[0]["log"]
    work = rig.r["home"] / "lrae-work"
    assert log.parent == rig.ctl.cfg.state_dir and not log.is_relative_to(work)
    assert rig.ctl.cfg.state_dir.name == "ui_state"
    assert not work.exists()


def test_default_state_dir_is_ui_state_in_the_repo(rig):
    cfg = cc.ControlConfig.from_settings(rig.settings)
    assert cfg.state_dir == rig.r["repo"].resolve() / "ui_state" and cfg.spec_roots == [rig.r["repo"].resolve() / "spec"]


# -- state ---------------------------------------------------------------------------------------

def test_state_idle_then_active_with_capped_log(rig):
    s = rig.c.get("/api/control/state").json()
    assert s["active"] is False and s["launch_allowed"] is True and s["job"] is None and s["log_tail"] == ""
    n = good_nonce(rig)
    assert rig.c.get("/api/control/state").json()["pending_nonces"] == 1
    launch(rig, n)
    rig.spawner.calls[0]["log"].write_text("x" * 100_000 + "TAIL-MARK")
    s = rig.c.get("/api/control/state").json()
    assert s["active"] and s["job"]["alive"] and s["pending_nonces"] == 0
    assert len(s["log_tail"]) <= cc.LOG_TAIL_BYTES and s["log_tail"].endswith("TAIL-MARK")


def test_launch_returns_pid_and_run_id_when_the_manifest_appears(rig):
    import json
    n = good_nonce(rig, config="A", repeat=0)
    est = rig.c.post("/api/launch/preview", json={"spec_path": rig.rel, "config": "A", "repeat": 0}).json()["estimate"]
    rid = est["run_ids"][0]
    orig = rig.ctl.cfg.spawner

    def spawn_and_write(argv, env, cwd, log):
        proc = orig(argv, env, cwd, log)
        (rig.r["runs"] / rid).mkdir()
        (rig.r["runs"] / rid / "manifest.json").write_text(json.dumps(
            {"run_id": rid, "harness_pid": proc.pid, "spec_hash": est["spec_hash"]}))
        return proc

    rig.ctl.cfg.spawner = spawn_and_write
    r = launch(rig, n)
    assert r.status_code == 200 and r.json()["manifest_seen"] and r.json()["run_id"] == rid
    assert r.json()["pid"] == cs.FAKE_PID


def test_a_process_that_dies_at_once_reports_the_log(rig):
    rig.spawner.auto_finish = True
    r = launch(rig, good_nonce(rig))
    assert r.status_code == 500 and r.json()["detail"]["code"] == "launch_failed"
    assert "fake launch log" in r.json()["detail"]["log_tail"]


# -- decoy pids are never signalled --------------------------------------------------------------

@pytest.fixture
def kills(monkeypatch):
    calls = []
    real = os.kill

    def spy(pid, sig):
        calls.append((pid, sig))
        return real(pid, sig)

    monkeypatch.setattr(cc.os, "kill", spy)
    return calls


def test_decoy_pid_in_a_manifest_is_never_signalled(rig, kills):
    import subprocess
    import sys
    decoys = [subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]),
              # the words lrae / runner.cli / run in a -c program must not pass for a harness
              subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "-m", "runner.cli", "run"]),
              subprocess.Popen(["bash", "-c", "sleep 60", "lrae", "run"])]
    try:
        time.sleep(0.2)
        for i, p in enumerate(decoys):
            cs.write_manifest(rig.r["runs"], f"d{i}", harness_pid=p.pid)
        for pid in (os.getpid(), 1, "123", None, True, -5):
            cs.write_manifest(rig.r["runs"], "weird", harness_pid=pid)
            for verb in ("stop", "kill"):
                body = {"confirm": "weird"} if verb == "kill" else None
                assert rig.c.post(f"/api/runs/weird/{verb}", json=body).status_code == 409
        for i, p in enumerate(decoys):
            for verb in ("stop", "kill"):
                body = {"confirm": f"d{i}"} if verb == "kill" else None
                r = rig.c.post(f"/api/runs/d{i}/{verb}", json=body)
                assert r.status_code == 409 and r.json()["detail"]["code"] == "not_a_live_harness", (i, verb)
            assert cs.alive(p.pid)
        assert kills == [] and rig.spawner.calls == []
    finally:
        for p in decoys:
            p.kill()
            p.wait()


def test_lookalike_started_after_the_run_is_not_its_harness(rig, kills):
    p = cs.spawn_lookalike(rig.r["tmp"], str(rig.spec), repo=rig.r["repo"])
    try:
        time.sleep(0.3)
        cs.write_manifest(rig.r["runs"], "old", harness_pid=p.pid, spec_path=str(rig.spec), start_epoch=time.time() - 3600)
        assert rig.c.post("/api/runs/old/stop").status_code == 409
        cs.write_manifest(rig.r["runs"], "ended", harness_pid=p.pid, spec_path=str(rig.spec), end={"state": "COMPLETED"})
        assert rig.c.post("/api/runs/ended/stop").status_code == 409
        assert kills == [] and cs.alive(p.pid)
    finally:
        p.kill()
        p.wait()


def test_stop_signals_a_verified_harness_with_sigint_once(rig, kills):
    p = cs.spawn_lookalike(rig.r["tmp"], str(rig.spec), repo=rig.r["repo"])
    try:
        time.sleep(0.3)
        cs.write_manifest(rig.r["runs"], "live", harness_pid=p.pid, spec_path=str(rig.spec), start_epoch=time.time())
        r = rig.c.post("/api/runs/live/stop")
        assert r.status_code == 200 and r.json() == {"signalled": "SIGINT", "pid": p.pid, "run_id": "live"}
        assert kills == [(p.pid, signal.SIGINT)]
        assert rig.c.post("/api/runs/live/stop").status_code in (409,)      # a second SIGINT could abort finalizing
        p.wait(timeout=10)
    finally:
        p.kill()
        p.wait()


def test_kill_needs_confirmation_then_sigkill_and_clean(rig, kills):
    p = cs.spawn_lookalike(rig.r["tmp"], str(rig.spec), repo=rig.r["repo"])
    try:
        time.sleep(0.3)
        cs.write_manifest(rig.r["runs"], "live", harness_pid=p.pid, spec_path=str(rig.spec), start_epoch=time.time())
        for body in ({"confirm": "yes"}, {"confirm": ""}, {}):
            assert rig.c.post("/api/runs/live/kill", json=body).status_code == 422
        assert kills == [] and cs.alive(p.pid)
        rig.spawner.auto_finish = True
        r = rig.c.post("/api/runs/live/kill", json={"confirm": "live"})
        assert r.status_code == 200 and r.json()["signalled"] == "SIGKILL", r.text
        assert kills == [(p.pid, signal.SIGKILL)]
        p.wait(timeout=10)
        assert rig.spawner.verbs() == ["clean"], "orphans are cleaned through the lrae CLI"
    finally:
        p.kill()
        p.wait()


def test_unknown_or_bad_run_ids(rig, kills):
    for rid in ("nope", "..", "a%2Fb"):
        assert rig.c.post(f"/api/runs/{rid}/stop").status_code in (404, 405)
    assert kills == []


# -- score / clean -------------------------------------------------------------------------------

def finished_run(rig, rid="done-run", **kw):
    return cs.write_manifest(rig.r["runs"], rid, spec_path=str(rig.spec), spec_hash=kw.pop("spec_hash", "h"),
                             end={"state": "COMPLETED", "cost_usd": 1.25}, **kw)


def test_score_runs_lrae_score_for_a_scripted_judge(rig):
    finished_run(rig)
    rig.spawner.auto_finish = True
    r = rig.c.post("/api/runs/done-run/score", json={"checkpoint": 2})
    assert r.status_code == 202 and r.json()["finished"] is True
    a = rig.spawner.calls[0]["argv"]
    assert a[-4:] == ["score", "done-run", "--checkpoint", "2"] and "--confirm-spend" not in a
    assert rig.c.post("/api/runs/done-run/score", json={"checkpoint": 0}).status_code == 422


def test_score_with_a_spending_judge_is_refused(tmp_path):
    rig = build_rig(tmp_path, judge="claude_code")
    finished_run(rig)
    r = rig.c.post("/api/runs/done-run/score")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "judge_spends" and rig.spawner.calls == []


def test_score_and_clean_refused_while_a_run_is_active(rig):
    finished_run(rig)
    launch(rig, good_nonce(rig))
    assert rig.c.post("/api/runs/done-run/score").status_code == 409
    assert rig.c.post("/api/clean").status_code == 409
    assert rig.spawner.verbs() == ["run"]


def test_clean_runs_lrae_clean(rig):
    rig.spawner.auto_finish = True
    r = rig.c.post("/api/clean")
    assert r.status_code == 200 and r.json()["finished"] and rig.spawner.verbs() == ["clean"]
    a = rig.spawner.calls[0]["argv"]
    assert a[a.index("runner.cli"):][:3] == ["runner.cli", "--repo-root", str(rig.ctl.cfg.repo_root)]


# -- resume --------------------------------------------------------------------------------------

def ended_run_with_snapshots(rig, h=None):
    from spec.loader import load_spec
    loaded = load_spec(rig.spec, repo_root=rig.r["repo"])
    rid = loaded.run_id("A", 0)
    cs.write_manifest(rig.r["runs"], rid, spec_path=str(rig.spec), spec_hash=h or loaded.spec_hash,
                      end={"state": "INTERRUPTED", "cost_usd": 0.5})
    for k in (1, 2):
        (rig.r["runs"] / rid / "snapshots" / f"t{k}").mkdir(parents=True)
        (rig.r["runs"] / rid / "snapshots" / f"t{k}" / "meta.json").write_text("{}")
    return rid


def rpreview(rig, rid, frm="t2"):
    return rig.c.post(f"/api/runs/{rid}/resume/preview", json={"from": frm})


def test_resume_scripted_flow(rig):
    rid = ended_run_with_snapshots(rig)
    b = rpreview(rig, rid).json()
    e = b["estimate"]
    assert e["kind"] == "resume" and e["from"] == "t2" and e["remaining_checkpoints"] == 2
    assert e["spent_so_far_usd"] == 0.5 and e["real_spend"] is False
    r = rig.c.post(f"/api/runs/{rid}/resume", json={"from": "t2", "nonce": b["confirmation_nonce"]})
    assert r.status_code == 202, r.text
    a = rig.spawner.calls[0]["argv"]
    assert a[a.index("resume"):] == ["resume", rid, "--from", "t2"]


def test_resume_input_checks(rig):
    rid = ended_run_with_snapshots(rig)
    for frm in ("t9", "x", "t0", "", "../t1"):
        assert rpreview(rig, rid, frm).status_code in (422,), frm
    assert rpreview(rig, "no-such-run").status_code == 404
    n = rpreview(rig, rid).json()["confirmation_nonce"]
    # a nonce for t2 cannot start t1, nor another run
    assert rig.c.post(f"/api/runs/{rid}/resume", json={"from": "t1", "nonce": n}).status_code == 400
    assert launch(rig, n).status_code == 400
    assert rig.spawner.calls == []


def test_resume_spec_edit_invalidates(rig):
    rid = ended_run_with_snapshots(rig)
    n = rpreview(rig, rid).json()["confirmation_nonce"]
    (rig.r["assets"] / "prompt.md").write_text("changed\n")
    assert rig.c.post(f"/api/runs/{rid}/resume", json={"from": "t2", "nonce": n}).status_code == 409
    assert rig.spawner.calls == []
    assert rpreview(rig, rid).status_code == 409        # the CLI would refuse as well


def test_resume_spec_outside_the_allowlist(rig, tmp_path):
    rid = ended_run_with_snapshots(rig)
    outside = tmp_path / "elsewhere.yaml"
    outside.write_text(rig.spec.read_text())
    cs.write_manifest(rig.r["runs"], rid, spec_path=str(outside), spec_hash="h")
    assert rpreview(rig, rid).status_code == 403


def test_resume_real_spend_needs_confirmation(rig_real):
    rid = ended_run_with_snapshots(rig_real)
    n = rpreview(rig_real, rid).json()["confirmation_nonce"]
    url = f"/api/runs/{rid}/resume"
    assert rig_real.c.post(url, json={"from": "t2", "nonce": n}).status_code == 422
    assert rig_real.c.post(url, json={"from": "t2", "nonce": n, "confirm_usd": 5.0, "confirm_runs": 1}).status_code == 422
    assert rig_real.spawner.calls == []
    n = rpreview(rig_real, rid).json()["confirmation_nonce"]
    r = rig_real.c.post(url, json={"from": "t2", "nonce": n, "confirm_usd": 3.0, "confirm_runs": 1})
    assert r.status_code == 202
    assert rig_real.spawner.calls[0]["argv"].count("--confirm-spend") == 1


def test_resume_refused_while_active(rig):
    rid = ended_run_with_snapshots(rig)
    launch(rig, good_nonce(rig, repeat=1))
    n = rpreview(rig, rid).json()["confirmation_nonce"]
    assert rig.c.post(f"/api/runs/{rid}/resume", json={"from": "t2", "nonce": n}).status_code == 409
    assert rig.spawner.verbs() == ["run"]


# -- agreement of the process matcher with the real thing ----------------------------------------

@pytest.mark.parametrize("argv,ok", [
    (["python", "-m", "runner.cli", "--repo-root", "/r", "run", "s.yaml"], True),
    (["python", "-u", "-m", "runner.cli", "resume", "x", "--from", "t2"], True),
    (["/usr/bin/python3", "/venv/bin/lrae", "run", "s.yaml"], True),
    (["python", "-m", "runner.cli", "validate", "s.yaml"], False),
    (["python", "-c", "x", "-m", "runner.cli", "run"], False),
    (["python", "-m", "http.server", "run"], False),
    (["bash", "-c", "sleep 60", "lrae", "run"], False),
    (["vim", "lrae", "run"], False),
    ([], False),
])
def test_harness_cmdline_matcher(argv, ok):
    assert cc._argv_is_harness(argv) is ok
