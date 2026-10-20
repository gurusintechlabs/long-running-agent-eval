import json
from pathlib import Path

from runner.prompt import assemble_prompt
from runner.runtimes.base import TurnContext
from runner.runtimes.claude_code import EMPTY_MCP, ClaudeCodeRuntime
from runner.runtimes.scripted import ScriptedRuntime


def ctx(tmp_path, **kw):
    base = dict(prompt="do it", session_id="11111111-1111-4111-8111-111111111111", first_turn=True,
                workspace=tmp_path / "ws", art=tmp_path / "art", settings_path=tmp_path / "art" / "hs.json",
                otel_endpoint="http://127.0.0.1:1", run_start_epoch=1.0, state_dir=tmp_path / "state")
    base.update(kw)
    return TurnContext(**base)


def test_first_turn_command(tmp_path):
    rt = ClaudeCodeRuntime(claude_bin="/usr/local/bin/claude", model="claude-opus-5-5")
    cmd = rt.build_command(ctx(tmp_path))
    assert cmd[0] == "/usr/local/bin/claude" and cmd[1:3] == ["-p", "do it"]
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5-5"
    assert cmd[cmd.index("--output-format") + 1] == "stream-json" and "--verbose" in cmd
    assert cmd[cmd.index("--setting-sources") + 1] == "project,local"
    assert "--strict-mcp-config" in cmd and "--dangerously-skip-permissions" in cmd
    assert cmd[cmd.index("--settings") + 1] == str(tmp_path / "art" / "hs.json")
    assert cmd[cmd.index("--session-id") + 1] == "11111111-1111-4111-8111-111111111111"
    assert "--resume" not in cmd


def test_later_turn_resumes(tmp_path):
    rt = ClaudeCodeRuntime(claude_bin="claude", model="claude-opus-5-5")
    cmd = rt.build_command(ctx(tmp_path, first_turn=False))
    assert cmd[cmd.index("--resume") + 1] == "11111111-1111-4111-8111-111111111111"
    assert "--session-id" not in cmd


def test_mcp_config_is_empty_file_arg(tmp_path):
    rt = ClaudeCodeRuntime(claude_bin="claude", model="claude-opus-5-5")
    cmd = rt.build_command(ctx(tmp_path))
    mcp = Path(cmd[cmd.index("--mcp-config") + 1])
    assert json.loads(EMPTY_MCP) == {"mcpServers": {}} and mcp.name == "empty-mcp.json"


def test_model_always_passed_never_default(tmp_path):
    rt = ClaudeCodeRuntime(claude_bin="claude", model="claude-sonnet-5-5")
    assert "claude-sonnet-5-5" in rt.build_command(ctx(tmp_path))


def test_auto_memory_off_not_supported_yet():
    import pytest
    with pytest.raises(NotImplementedError):
        ClaudeCodeRuntime(claude_bin="claude", model="claude-opus-5-5", auto_memory="off")


def test_scripted_command(tmp_path):
    rt = ScriptedRuntime(script=tmp_path / "s.yaml")
    cmd = rt.build_command(ctx(tmp_path, first_turn=False))
    assert cmd[1:3] == ["-m", "runner.runtimes.scripted_agent"]
    assert cmd[cmd.index("--script") + 1] == str(tmp_path / "s.yaml")
    assert cmd[cmd.index("--workspace") + 1] == str(tmp_path / "ws")
    assert cmd[cmd.index("--otel") + 1] == "http://127.0.0.1:1"
    assert cmd[cmd.index("--state") + 1] == str(tmp_path / "state" / "script-state.json")


def test_assemble_prompt_states_constraints_once(tmp_path):
    (tmp_path / "p.md").write_text("Build it.\n")
    (tmp_path / "c.yaml").write_text(
        "constraints:\n  - {id: a, text: 'Do not touch vendor/.', probe: x, params: {}}\n"
        "  - {id: b, text: 'No new deps.', probe: y, params: {}}\n")
    out = assemble_prompt(tmp_path / "p.md", tmp_path / "c.yaml")
    assert out.startswith("Build it.")
    assert out.count("Do not touch vendor/.") == 1 and out.count("No new deps.") == 1
    assert "Constraints" in out


def test_task_mcp_config_replaces_the_empty_one(tmp_path):
    """Plan B3: a task with an ops counterpart passes its own MCP config (still --strict-mcp-config)."""
    rt = ClaudeCodeRuntime(claude_bin="claude", model="claude-opus-5-5")
    cfg = tmp_path / "art" / "mcp.json"
    cmd = rt.build_command(ctx(tmp_path, mcp_config=cfg))
    assert cmd[cmd.index("--mcp-config") + 1] == str(cfg) and "--strict-mcp-config" in cmd
    s = ScriptedRuntime(tmp_path / "script.yaml")
    sc = s.build_command(ctx(tmp_path, mcp_config=cfg))
    assert sc[sc.index("--mcp-config") + 1] == str(cfg)
    assert "--mcp-config" not in s.build_command(ctx(tmp_path))


def test_safe_mode_only_for_tasks_without_workspace_memory_or_mcp(tmp_path):
    """Verified on CLI 2.1.301 (B3): --safe-mode stops both the workspace CLAUDE.md (D-15a) and the
    --mcp-config servers from loading, so those tasks run without it; every other task keeps it."""
    from types import SimpleNamespace

    from runner.runtimes.claude_code import safe_mode_for
    plain = SimpleNamespace(workspace_memory=None)
    assert safe_mode_for(plain, set()) == (True, None)
    on, why = safe_mode_for(SimpleNamespace(workspace_memory="/x/CLAUDE.md"), set())
    assert on is False and "workspace_memory" in why
    on, why = safe_mode_for(plain, {"ops"})
    assert on is False and "mcp" in why
    rt = ClaudeCodeRuntime(claude_bin="claude", model="claude-opus-5-5")
    assert "--safe-mode" in rt.build_command(ctx(tmp_path))
    rt.safe_mode = False
    cmd = rt.build_command(ctx(tmp_path))
    assert "--safe-mode" not in cmd and "--strict-mcp-config" in cmd and "--disable-slash-commands" in cmd
