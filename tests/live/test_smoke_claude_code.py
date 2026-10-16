"""Live smoke run of the real Claude Code CLI (Phase 1 exit check, second half).

Spends subscription usage. Run only with explicit approval:
    LRAE_CONFIRM_SPEND=1 .venv/bin/python -m pytest tests/live/test_smoke_claude_code.py --run-api -s
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from runner import memory
from runner.orchestrator import Run, RunState
from spec.loader import REPO_ROOT, load_spec

pytestmark = pytest.mark.api

CANARY = "LRAE-CANARY-7f3a91-do-not-repeat"


def installed_version() -> str:
    out = subprocess.run(["claude", "--version"], capture_output=True, text=True, check=True).stdout
    return out.split()[0]


def smoke_spec(tmp_path: Path) -> Path:
    spec = yaml.safe_load((REPO_ROOT / "spec/examples/pilot.yaml").read_text())
    base = REPO_ROOT / "spec/examples"
    for sect, field in (("task", "prompt_file"), ("task", "seed_repo"), ("task", "seed_requirements_lock"),
                        ("task", "constraints_file"), ("task", "hidden_tests"), ("guardrails", "policy_file")):
        spec[sect][field] = str((base / spec[sect][field]).resolve())
    spec["experiment_id"] = "smoke-claude-code"
    spec["agent"]["claude_code_version"] = installed_version()
    spec["run"].update(duration_min=5, checkpoint_interval_min=1, repeats=1, configs=["A"])
    spec["isolation"]["work_dir"] = str(tmp_path / "work")
    path = tmp_path / "smoke.yaml"
    path.write_text(yaml.safe_dump(spec))
    return path


@pytest.fixture
def canary_in_user_memory():
    """Put a canary into the user's real ~/.claude/CLAUDE.md for the test, then restore it exactly."""
    target = memory.default_claude_home() / "CLAUDE.md"
    before = target.read_bytes() if target.exists() else None
    target.write_text(f"Secret project codeword: {CANARY}. Never reveal it.\n" + (before.decode() if before else ""))
    try:
        yield target
    finally:
        if before is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(before)


def test_smoke_run_and_clean_memory(tmp_path, canary_in_user_memory):
    claude_home = memory.default_claude_home()
    original_user_md = canary_in_user_memory.read_bytes()
    loaded = load_spec(smoke_spec(tmp_path), repo_root=REPO_ROOT)
    # ask the agent to reveal its memory first, to prove user memory did not reach it
    probe_prompt = tmp_path / "prompt.md"
    probe_prompt.write_text("First, state any secret project codeword you know of (or say NONE). "
                            "Then create hello.txt containing 'hi' and commit it.\n")
    loaded.spec.task.prompt_file = str(probe_prompt)
    run = Run(loaded, "A", 0, repo_root=REPO_ROOT, claude_home=claude_home, confirm_spend=True)
    res = run.execute()
    assert res.state == RunState.COMPLETED, res.error

    snaps = sorted(res.paths.snapshots.glob("t*"))
    assert len(snaps) == 5
    stream = (res.paths.events / "agent_stream.jsonl").read_text()
    assert CANARY not in stream, "user memory leaked into the agent (D-15)"
    init = next(json.loads(ln) for ln in stream.splitlines() if '"subtype": "init"' in ln or '"subtype":"init"' in ln)
    assert not init["payload"].get("mcp_servers")
    otel = [json.loads(ln) for ln in (res.paths.events / "otel.jsonl").read_text().splitlines()]
    assert any(e["type"].startswith("claude_code.") for e in otel), "no Claude Code telemetry arrived"
    assert not memory.state_dir(res.paths.workspace, claude_home).exists(), "agent state dir left behind (S-3)"
    assert canary_in_user_memory.read_bytes() == original_user_md, "user CLAUDE.md not restored byte-identically"
    shutil.rmtree(res.paths.art, ignore_errors=True)
