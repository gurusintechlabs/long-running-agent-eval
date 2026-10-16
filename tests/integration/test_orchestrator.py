import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from runner import memory
from runner.orchestrator import Run, RunState, recover_unfinalized
from runner.procs import find_in_dir
from spec.loader import load_spec

from .conftest import git

pytestmark = pytest.mark.local


def do_run(env, repeat=0, loaded=None, **kw):
    loaded = loaded or load_spec(env["spec_path"], repo_root=env["repo_root"])
    run = Run(loaded, "A", repeat, repo_root=env["repo_root"], claude_home=env["claude_home"],
              host_home=env["home"], **kw)
    return run.execute(), loaded


def events(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines()]


def test_scripted_run_completes_with_all_artifacts(env):
    res, loaded = do_run(env)
    assert res.state == RunState.COMPLETED, res.error
    p = res.paths
    assert p.run_id == loaded.run_id("A", 0)
    for k in range(1, 5):
        meta = json.loads((p.snapshots / f"t{k}" / "meta.json").read_text())
        assert meta["k"] == k
        assert (p.snapshots / f"t{k}" / "workspace" / f"step{k}.txt").exists()
        assert not (p.snapshots / f"t{k}" / "workspace" / f"step{k + 1}.txt").exists()
    tags = git(p.mirror, "tag", "-l").split()
    assert tags == [f"ckpt/t{k}" for k in range(1, 5)]
    assert git(p.mirror, "rev-list", "--count", "ckpt/t4") == "5"  # seed + 4 agent commits
    manifest = json.loads(p.manifest.read_text())
    assert manifest["spec_hash"] == loaded.spec_hash and manifest["end"]["state"] == "COMPLETED"
    assert manifest["isolation_mode"] == "local" and manifest["seed_commit"] == env["sha"]


def test_state_transitions_logged_in_order(env):
    res, _ = do_run(env)
    ev = events(res.paths.events / "orchestrator.jsonl")
    states = [e["payload"]["to"] for e in ev if e["type"] == "state"]
    assert states[0] == "PREPARING" and "RUNNING" in states and "FINALIZING" in states
    assert states[-1] == "COMPLETED"
    assert states.count("CHECKPOINTING") == 4
    assert [e["seq"] for e in ev] == list(range(len(ev)))


def test_streams_and_otel_recorded(env):
    res, _ = do_run(env)
    stream = events(res.paths.events / "agent_stream.jsonl")
    assert any(e["type"] == "stream.system" for e in stream)
    assert any(e["type"] == "stream.assistant" for e in stream)
    otel = events(res.paths.events / "otel.jsonl")
    costs = [e for e in otel if e["type"] == "claude_code.api_request"]
    assert len(costs) == 4 and all(e["payload"]["_resource"]["lrae.run_id"] == res.paths.run_id for e in costs)
    metas = [json.loads((res.paths.snapshots / f"t{k}" / "meta.json").read_text()) for k in range(1, 5)]
    assert [m["cumulative_cost_usd"] for m in metas] == pytest.approx([0.01, 0.02, 0.03, 0.04])


def test_cleanup_after_run(env):
    res, _ = do_run(env)
    assert not res.paths.work.exists(), "work dir should be deleted"
    sd = memory.state_dir(res.paths.workspace, env["claude_home"])
    assert not sd.exists(), "agent state dir must be deleted (S-3)"
    assert not find_in_dir(res.paths.work.parent), "no process may survive the run (S-6)"
    assert (res.paths.snapshots / "t4" / "agent_state" / "script-state.json").exists()


def test_keep_work_dir_option(env):
    spec = yaml.safe_load(env["spec_path"].read_text())
    spec["isolation"]["keep_work_dir"] = True
    env["spec_path"].write_text(yaml.safe_dump(spec))
    res, _ = do_run(env)
    assert res.paths.work.exists()
    assert not memory.state_dir(res.paths.workspace, env["claude_home"]).exists()


def test_runs_are_reproducible(env):
    r0, _ = do_run(env, repeat=0)
    r1, _ = do_run(env, repeat=1)
    assert r0.state == r1.state == RunState.COMPLETED
    assert r0.paths.work != r1.paths.work and r0.paths.art != r1.paths.art
    for k in range(1, 5):
        m0 = json.loads((r0.paths.snapshots / f"t{k}" / "meta.json").read_text())
        m1 = json.loads((r1.paths.snapshots / f"t{k}" / "meta.json").read_text())
        assert m0["worktree_hash"] == m1["worktree_hash"], k
        assert m0["head_tree"] == m1["head_tree"], k


def test_agent_env_is_scrubbed_during_run(env, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "a" * 36)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "supersecret")
    probe = {"do": "bash", "at": 0.2,
             "cmd": "env > envdump.txt"}
    spec = yaml.safe_load(env["spec_path"].read_text())
    sc = yaml.safe_load((env["tmp"] / "script.yaml").read_text())
    sc["actions"].insert(0, probe)
    (env["tmp"] / "script.yaml").write_text(yaml.safe_dump(sc))
    spec["isolation"]["keep_work_dir"] = True
    env["spec_path"].write_text(yaml.safe_dump(spec))
    res, _ = do_run(env)
    dump = (res.paths.workspace / "envdump.txt").read_text()
    assert "GITHUB_TOKEN" not in dump and "AWS_SECRET" not in dump and "supersecret" not in dump
    assert "OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:" in dump
    assert "CLAUDE_CODE_ENABLE_TELEMETRY=1" in dump
    assert f"TMPDIR={res.paths.tmp}" in dump


def test_failed_prepare_cleans_up(env):
    spec = yaml.safe_load(env["spec_path"].read_text())
    spec["task"]["seed_commit"] = "b" * 40
    env["spec_path"].write_text(yaml.safe_dump(spec))
    res, _ = do_run(env)
    assert res.state == RunState.FAILED and res.error
    assert not res.paths.work.exists()
    assert not memory.state_dir(res.paths.workspace, env["claude_home"]).exists()
    manifest = json.loads(res.paths.manifest.read_text())
    assert manifest["end"]["state"] == "FAILED"


def test_preflight_failure_marks_failed(env):
    (env["home"] / "CLAUDE.md").write_text("leaky memory")
    res, _ = do_run(env)
    assert res.state == RunState.FAILED and "L-1" in res.error
    assert not res.paths.work.exists()


def test_populated_state_dir_blocks_start(env):
    loaded = load_spec(env["spec_path"], repo_root=env["repo_root"])
    from runner.workdir import RunPaths
    paths = RunPaths.for_run(loaded.run_id("A", 0), Path(loaded.spec.isolation.work_dir), env["repo_root"])
    sd = memory.state_dir(paths.workspace, env["claude_home"])
    sd.mkdir(parents=True)
    (sd / "old.jsonl").write_text("{}")
    res, _ = do_run(env, loaded=loaded)
    assert res.state == RunState.FAILED and "L-3" in res.error


def test_existing_run_dir_is_refused(env):
    res, loaded = do_run(env)
    assert res.state == RunState.COMPLETED
    res2, _ = do_run(env, loaded=loaded)
    assert res2.state == RunState.FAILED and "exists" in res2.error


def test_recover_unfinalized_cleans_crashed_run(env, tmp_path):
    loaded = load_spec(env["spec_path"], repo_root=env["repo_root"])
    from runner.workdir import RunPaths
    paths = RunPaths.for_run(loaded.run_id("A", 5), Path(loaded.spec.isolation.work_dir), env["repo_root"])
    paths.create()
    paths.workspace.mkdir()
    sd = memory.state_dir(paths.workspace, env["claude_home"])
    sd.mkdir(parents=True)
    (sd / "s.jsonl").write_text("{}")
    orphan = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], cwd=paths.workspace,
                              start_new_session=True)
    paths.manifest.write_text(json.dumps({
        "run_id": paths.run_id, "harness_pid": 999999,
        "paths": {"work": str(paths.work), "workspace": str(paths.workspace), "state_dir": str(sd)},
        "start_epoch": time.time() - 100}))
    recovered = recover_unfinalized(env["repo_root"], env["claude_home"])
    assert recovered == [paths.run_id]
    time.sleep(0.3)
    assert orphan.poll() is not None, "orphan agent must be killed"
    assert not paths.work.exists() and not sd.exists()
    assert json.loads(paths.manifest.read_text())["end"]["censored_reason"] == "harness_crash"
    assert recover_unfinalized(env["repo_root"], env["claude_home"]) == []  # idempotent


def test_recover_skips_live_harness(env):
    from runner.workdir import RunPaths
    paths = RunPaths.for_run("live-run", env["home"] / "w", env["repo_root"])
    paths.create()
    paths.manifest.write_text(json.dumps({"run_id": "live-run", "harness_pid": os.getpid(),
                                          "paths": {"work": str(paths.work), "workspace": "x", "state_dir": "y"}}))
    assert recover_unfinalized(env["repo_root"], env["claude_home"]) == []
    assert paths.work.exists()


# -- CLI + crash/resume -------------------------------------------------------------------------

def cli(env, *args, **kw):
    return [sys.executable, "-m", "runner.cli", "--repo-root", str(env["repo_root"]),
            "--claude-home", str(env["claude_home"]), "--home", str(env["home"]), *args]


def wait_for(cond, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_cli_validate(env):
    out = subprocess.run(cli(env, "validate", str(env["spec_path"])), capture_output=True, text=True)
    assert out.returncode == 0 and "orch-test-A-r00-" in out.stdout


def test_cli_validate_bad_spec(env):
    env["spec_path"].write_text("spec_version: 2\n")
    out = subprocess.run(cli(env, "validate", str(env["spec_path"])), capture_output=True, text=True)
    assert out.returncode != 0


def test_cli_run_requires_confirm_spend_for_real_agent(env):
    spec = yaml.safe_load(env["spec_path"].read_text())
    spec["agent"] = {"runtime": "claude_code", "claude_code_version": "1.0.126", "model": "claude-opus-5-5"}
    env["spec_path"].write_text(yaml.safe_dump(spec))
    out = subprocess.run(cli(env, "run", str(env["spec_path"])), capture_output=True, text=True)
    assert out.returncode != 0 and "confirm-spend" in (out.stdout + out.stderr)


def test_crash_then_resume(env):
    proc = subprocess.Popen(cli(env, "run", str(env["spec_path"]), "--config", "A", "--repeat", "0"),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    loaded = load_spec(env["spec_path"], repo_root=env["repo_root"])
    run_id = loaded.run_id("A", 0)
    art = env["repo_root"] / "runs" / run_id
    assert wait_for(lambda: (art / "snapshots" / "t2" / "meta.json").exists()), "t2 never appeared"
    proc.send_signal(signal.SIGKILL)  # harness dies; the scripted agent is orphaned
    proc.wait()
    work = Path(loaded.spec.isolation.work_dir) / run_id
    assert work.exists()
    out = subprocess.run(cli(env, "resume", run_id, "--from", "t2"), capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    manifest = json.loads((art / "manifest.json").read_text())
    assert manifest["end"]["state"] == "COMPLETED" and manifest["resumed"] is True
    for k in range(1, 5):
        assert (art / "snapshots" / f"t{k}" / "meta.json").exists(), k
    final = art / "snapshots" / "t4" / "workspace"
    assert all((final / f"step{k}.txt").exists() for k in range(1, 5))
    assert not work.exists()
    assert not memory.state_dir(work / "workspace", env["claude_home"]).exists()
    assert not find_in_dir(work.parent), "no stray processes after resume"
    states = [e["payload"]["to"] for e in events(art / "events" / "orchestrator.jsonl") if e["type"] == "state"]
    assert "COMPLETED" in states
    assert any(e["type"] == "run.resumed" for e in events(art / "events" / "orchestrator.jsonl"))
