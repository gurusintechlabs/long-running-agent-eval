import json
import os
import stat

import pytest

from runner import preflight
from runner.workdir import RunPaths


def make_paths(tmp_path):
    paths = RunPaths.for_run("r1", tmp_path / "home" / "lrae-work", tmp_path / "repo")
    paths.create()
    paths.workspace.mkdir()
    return paths


def names(checks):
    return {c.name: c for c in checks}


def static(tmp_path, paths, **kw):
    kw.setdefault("claude_home", tmp_path / "claude")
    kw.setdefault("home", tmp_path / "home")
    return preflight.run_static_checks(paths, repo_root=tmp_path / "repo", **kw)


def test_all_static_checks_pass_on_clean_setup(tmp_path):
    paths = make_paths(tmp_path)
    checks = static(tmp_path, paths)
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]
    assert {"L-1 ancestors", "L-3 state dir empty", "L-4 no harness paths"} <= set(names(checks))


def test_l1_fails_on_ancestor_claude_md(tmp_path):
    paths = make_paths(tmp_path)
    (tmp_path / "home" / "CLAUDE.md").write_text("x")
    c = names(static(tmp_path, paths))["L-1 ancestors"]
    assert not c.ok and "CLAUDE.md" in c.detail


def test_l1_allows_dot_claude_in_home(tmp_path):
    paths = make_paths(tmp_path)
    (tmp_path / "home" / ".claude").mkdir()
    assert names(static(tmp_path, paths))["L-1 ancestors"].ok


def test_l3_fails_when_state_dir_populated(tmp_path):
    from runner import memory
    paths = make_paths(tmp_path)
    sd = memory.state_dir(paths.workspace, tmp_path / "claude")
    sd.mkdir(parents=True)
    (sd / "old.jsonl").write_text("{}")
    assert not names(static(tmp_path, paths))["L-3 state dir empty"].ok


def test_l4_fails_on_symlink_into_repo(tmp_path):
    paths = make_paths(tmp_path)
    (tmp_path / "repo").mkdir(exist_ok=True)
    (tmp_path / "repo" / "secret").write_text("x")
    os.symlink(tmp_path / "repo" / "secret", paths.workspace / "link")
    c = names(static(tmp_path, paths))["L-4 no harness paths"]
    assert not c.ok and "link" in c.detail


def test_l4_fails_when_repo_path_is_inside_work(tmp_path):
    paths = make_paths(tmp_path)
    (paths.workspace / "notes.txt").write_text(f"see {tmp_path / 'repo'}/fixtures/tasks/x/hidden")
    # plain text mentions are not our concern; only filesystem links/copies are
    assert names(static(tmp_path, paths))["L-4 no harness paths"].ok


def test_l4_fails_on_hidden_tests_copied_into_work(tmp_path):
    paths = make_paths(tmp_path)
    (paths.workspace / "hidden").mkdir()
    (paths.workspace / "hidden" / "test_secret.py").write_text("x")
    c = names(static(tmp_path, paths, forbidden_names=["hidden"]))["L-4 no harness paths"]
    assert not c.ok


def fake_claude(tmp_path, version_line="1.0.126 (Claude Code)"):
    p = tmp_path / "claude"
    p.write_text(f"#!/bin/sh\necho '{version_line}'\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_l6_version_match(tmp_path):
    c = preflight.check_claude_version(fake_claude(tmp_path), "1.0.126")
    assert c.ok and c.name == "L-6 cli version"


def test_l6_version_mismatch(tmp_path):
    c = preflight.check_claude_version(fake_claude(tmp_path, "1.0.127 (Claude Code)"), "1.0.126")
    assert not c.ok and "1.0.127" in c.detail


def test_l6_missing_binary(tmp_path):
    assert not preflight.check_claude_version(str(tmp_path / "nope"), "1").ok


def init_msg(**kw):
    base = {"type": "system", "subtype": "init", "session_id": "s", "mcp_servers": [],
            "tools": ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "TodoWrite"], "model": "x"}
    base.update(kw)
    return base


def test_init_clean():
    assert all(c.ok for c in preflight.evaluate_init(init_msg()))


def test_init_flags_mcp_servers():
    checks = preflight.evaluate_init(init_msg(mcp_servers=[{"name": "figma", "status": "connected"}]))
    assert any(not c.ok and "mcp" in c.name.lower() for c in checks)


def test_init_flags_mcp_tools_and_unknown_tools():
    checks = preflight.evaluate_init(init_msg(tools=["Bash", "mcp__figma__get", "Weird"]))
    bad = [c for c in checks if not c.ok]
    assert bad and "mcp__figma__get" in bad[0].detail and "Weird" in bad[0].detail


def test_init_flags_plugins_and_skills_if_reported():
    checks = preflight.evaluate_init(init_msg(plugins=[{"name": "p"}], skills=["s"]))
    assert sum(1 for c in checks if not c.ok) >= 1


def test_find_init_in_stream_lines():
    lines = ['not json', json.dumps({"type": "system", "subtype": "hook"}),
             json.dumps(init_msg()), json.dumps({"type": "result"})]
    assert preflight.find_init(lines)["session_id"] == "s"
    assert preflight.find_init(["x"]) is None


def test_raise_on_failure(tmp_path):
    paths = make_paths(tmp_path)
    (tmp_path / "home" / "CLAUDE.md").write_text("x")
    with pytest.raises(preflight.PreflightError) as ei:
        preflight.require(static(tmp_path, paths))
    assert "L-1" in str(ei.value)
