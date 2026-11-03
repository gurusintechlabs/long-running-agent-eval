"""AI vulnerability review (plan B4, docs/behavior-design.md §7.3): one dedicated call per stage end."""
import json
import shutil

import pytest

from scorer.security import ai_review
from spec.loader import REPO_ROOT

APP = REPO_ROOT / "fixtures" / "security" / "vulnapp"
CONTEXT = {"name": "file service", "component": "app.py", "languages": "Python 3, stdlib http.server",
           "communicates_with": "HTTP clients on loopback", "threat_model": "untrusted HTTP clients",
           "ai_integrations": "none"}


def envelope(result, cost=0.5, is_error=False):
    return json.dumps({"type": "result", "subtype": "success", "is_error": is_error, "result": result,
                       "total_cost_usd": cost})


BLOCK = {"sound": False, "findings": [
    {"id": "VULN-1", "title": "Shell injection in /ping", "category": "2A", "cwe": "CWE-78", "severity": "Critical",
     "confidence": "High", "chainable": False, "chain_partners": [],
     "locations": [{"path": "app.py", "line": 40, "symbol": "do_GET"}]},
    {"id": "VULN-2", "title": "Verbose banner", "category": "2G", "cwe": "CWE-200", "severity": "Low",
     "confidence": "Medium", "chainable": True, "chain_partners": ["VULN-1"], "locations": [{"path": "app.py"}]}],
    "chains": [{"ids": ["VULN-2", "VULN-1"], "severity": "Critical", "summary": "x"}]}


def report(block=BLOCK):
    return "## Phase 1\n...analysis...\n\n```lrae-findings\n" + json.dumps(block) + "\n```\n"


def test_prompt_fills_context_and_sast_and_keeps_the_methodology():
    p = ai_review.build_prompt(CONTEXT, [{"tool": "bandit", "rule": "B602", "severity": "high", "path": "app.py",
                                          "line": 40, "message": "shell=True"}])
    assert "Phase 3 — Exploit Chain Analysis" in p and "lrae-findings" in p
    assert "> Application name: file service" in p and "{{" not in p
    assert "bandit B602 (high) app.py:40" in p


def test_extract_and_validate_the_findings_block():
    out = ai_review.extract_findings(report())
    assert [f["id"] for f in out["findings"]] == ["VULN-1", "VULN-2"] and out["sound"] is False
    assert ai_review.summarize(out) == {"high_or_critical": 1, "by_severity": {"Critical": 1, "High": 0, "Medium": 0,
                                                                              "Low": 1}, "chains": 1}
    for bad in ("no block at all", "```lrae-findings\n{not json}\n```",
                report({"sound": False, "findings": [{"id": "V", "severity": "Severe"}], "chains": []})):
        with pytest.raises(ai_review.ReviewOutputError):
            ai_review.extract_findings(bad)


def test_code_copy_has_no_tests_git_or_harness_files(tmp_path):
    src = tmp_path / "ws"
    shutil.copytree(APP / "vuln", src)
    (src / "tests").mkdir()
    (src / "tests" / "test_app.py").write_text("x")
    (src / "test_more.py").write_text("x")
    (src / ".git").mkdir()
    (src / ".git" / "HEAD").write_text("x")
    (src / "conftest.py").write_text("x")
    dest = tmp_path / "copy"
    ai_review.code_copy(src, dest)
    names = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert "app.py" in names and "data/readme.txt" in names
    assert not {n for n in names if n.startswith((".git", "tests")) or n in ("test_more.py", "conftest.py")}


def test_code_copy_of_a_maven_workspace(tmp_path):
    """jira-re: product Java and the analyst's spec (the intended access rules) stay; tests, build output, Maven's
    repository, decompiled sources and the agent's subagent worktrees go."""
    src = tmp_path / "ws"
    for rel in ("src/main/java/p/Resource.java", "src/main/resources/atlassian-plugin.xml", "spec/SPEC.md", "pom.xml",
                "src/test/java/p/ResourceTest.java", "target/classes/p/Resource.class", ".m2/repo/x.jar",
                ".decompiled/p/Resource.java", ".claude/worktrees/agent-1/src/main/java/p/Resource.java"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text("x")
    dest = ai_review.code_copy(src, tmp_path / "copy")
    names = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert names == {"src/main/java/p/Resource.java", "src/main/resources/atlassian-plugin.xml", "spec/SPEC.md",
                     "pom.xml"}


class Runner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, prompt, model, cwd):
        self.calls.append((model, sorted(p.name for p in cwd.iterdir())))
        return self.outputs.pop(0)


def test_review_retries_once_then_caches(tmp_path):
    shutil.copytree(APP / "vuln", tmp_path / "tree")
    runner = Runner([envelope("garbled, no block", cost=0.1), envelope(report(), cost=0.4)])
    r = ai_review.review(tmp_path / "tree", model="claude-haiku-5-5", runner=runner, cache_dir=tmp_path / "cache",
                         context=CONTEXT, sast_findings=[])
    assert r["ok"] and r["attempts"] == 2 and r["cost_usd"] == pytest.approx(0.5) and not r["cached"]
    assert r["summary"]["high_or_critical"] == 1 and "app.py" in runner.calls[0][1]
    assert (tmp_path / "cache" / f"{r['key']}.md").read_text().startswith("## Phase 1")
    again = ai_review.review(tmp_path / "tree", model="claude-haiku-5-5", runner=Runner([]),
                             cache_dir=tmp_path / "cache", context=CONTEXT, sast_findings=[])
    assert again["cached"] and again["cost_usd"] == 0 and again["findings"] == r["findings"]


def test_review_failure_is_null_not_zero(tmp_path):
    shutil.copytree(APP / "clean", tmp_path / "tree")
    r = ai_review.review(tmp_path / "tree", model="m", runner=Runner([envelope("x"), envelope("y")]),
                         cache_dir=tmp_path / "cache", context=CONTEXT, sast_findings=[])
    assert r["ok"] is False and r["summary"] is None and r["reason"]
    assert not list((tmp_path / "cache").glob("*.json"))  # failures are not cached


def test_fake_reviewer_is_content_based(tmp_path):
    res = {}
    for v in ("clean", "vuln"):
        shutil.copytree(APP / v, tmp_path / v)
        res[v] = ai_review.review(tmp_path / v, model="m", runner=ai_review.FakeReviewer(),
                                  cache_dir=tmp_path / f"c-{v}", context=CONTEXT, sast_findings=[])
    assert res["clean"]["summary"]["high_or_critical"] == 0 and res["clean"]["sound"] is True
    assert res["vuln"]["summary"]["high_or_critical"] >= 2


def test_cli_runner_command_is_read_only(tmp_path):
    r = ai_review.ClaudeReviewRunner(claude_bin="/bin/claude", confirm_spend=True)
    cmd = r.command("claude-haiku-5-5", tmp_path / "mcp.json")
    assert cmd[cmd.index("--tools") + 1] == "Read,Grep,Glob" and "--safe-mode" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-5-5" and "--strict-mcp-config" in cmd
    assert "--dangerously-skip-permissions" not in cmd
    assert r.timeout_s >= 2700  # a whole-product review takes minutes
    from scorer.metrics.x_judge import SpendNotConfirmed
    with pytest.raises(SpendNotConfirmed):
        ai_review.ClaudeReviewRunner(claude_bin="/bin/claude", confirm_spend=False)
