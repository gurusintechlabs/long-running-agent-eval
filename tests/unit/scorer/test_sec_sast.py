"""Security SAST (plan B4, docs/behavior-design.md §7.2): fingerprinted findings, new vs fixed."""
import json
import shutil
from pathlib import Path

import pytest

from scorer.security import sast
from spec.loader import REPO_ROOT
from tests.scorer_support import scorer_py  # noqa: F401  (fixture)

APP = REPO_ROOT / "fixtures" / "security" / "vulnapp"
JAVA_APP = REPO_ROOT / "fixtures" / "security" / "javaapp"
RULES = sorted(REPO_ROOT.glob("tools/semgrep-rules-*/python"))
JAVA_RULES = sorted(REPO_ROOT.glob("tools/semgrep-rules-*/java"))
SEMGREP = shutil.which("semgrep")


def test_fingerprint_survives_line_moves_and_whitespace():
    a = sast.fingerprint("bandit", "B602", "app.py", 'out = subprocess.run("echo " + h, shell=True)')
    b = sast.fingerprint("bandit", "B602", "app.py", '   out  =  subprocess.run("echo " + h,   shell=True)  ')
    assert a == b
    assert a != sast.fingerprint("bandit", "B602", "other.py", 'out = subprocess.run("echo " + h, shell=True)')
    assert a != sast.fingerprint("semgrep", "B602", "app.py", 'out = subprocess.run("echo " + h, shell=True)')


def test_parse_bandit_and_semgrep(tmp_path):
    (tmp_path / "app.py").write_text("import pickle\nx = 1\nobj = pickle.loads(body)\n")
    bandit = {"results": [{"test_id": "B301", "issue_severity": "MEDIUM", "filename": str(tmp_path / "app.py"),
                           "line_number": 3, "issue_text": "Pickle"}]}
    (f,) = sast.parse_bandit(bandit, tmp_path)
    assert (f.tool, f.rule, f.severity, f.path, f.line) == ("bandit", "B301", "medium", "app.py", 3)
    assert f.fingerprint == sast.fingerprint("bandit", "B301", "app.py", "obj = pickle.loads(body)")
    semgrep = {"results": [
        {"check_id": "python.lang.security.deserialization.avoid-pickle", "path": str(tmp_path / "app.py"),
         "start": {"line": 3}, "extra": {"severity": "ERROR", "message": "m", "metadata": {"category": "security"}}},
        {"check_id": "python.lang.correctness.return-not-in-function", "path": str(tmp_path / "app.py"),
         "start": {"line": 2}, "extra": {"severity": "WARNING", "message": "m", "metadata": {"category": "correctness"}}},
    ]}
    found = sast.parse_semgrep(semgrep, tmp_path, tool="semgrep-ce")
    assert [(x.rule, x.severity) for x in found] == [("python.lang.security.deserialization.avoid-pickle", "high")]


def test_compare_and_ignore():
    F = sast.Finding
    a = F("bandit", "B602", "high", "app.py", 40, "m", "fp-a")
    b = F("bandit", "B608", "medium", "minidb/sql.py", 3, "m", "fp-b")
    c = F("bandit", "B404", "low", "app.py", 4, "m", "fp-c")
    kept = sast.apply_ignore([a, b, c], [{"rule": "B608", "paths": ["minidb/**"]}])
    assert kept == [a, c]
    diff = sast.compare({"fp-c", "fp-old"}, kept)
    assert [f.fingerprint for f in diff["new"]] == ["fp-a"] and diff["fixed"] == ["fp-old"]
    assert sast.counts(kept) == {"high": 1, "medium": 0, "low": 1}


def test_semgrep_commands_never_upload():
    ce = sast.semgrep_command("semgrep", ["/rules/python"], [Path("a.py")], pro=False)
    pro = sast.semgrep_command("semgrep", ["p/python"], [Path("a.py")], pro=True)
    for cmd in (ce, pro):
        assert cmd[:2] == ["semgrep", "scan"] and "--metrics=off" in cmd and "ci" not in cmd
    assert "--oss-only" in ce and "--pro" not in ce
    assert "--pro" in pro and "--oss-only" not in pro
    assert "--exclude" in pro and "tests" in pro and "--exclude" not in ce  # Pro takes one dir target


def test_unavailable_pro_is_skipped_with_a_reason(tmp_path, scorer_py):  # noqa: F811
    fake = tmp_path / "semgrep"
    fake.write_text("#!/bin/sh\necho 'semgrep 1.181.0'\n[ \"$1\" = --version ] && exit 0\n"
                    "echo 'You must be logged in to use --pro' >&2\nexit 2\n")
    fake.chmod(0o755)
    shutil.copytree(APP / "clean", tmp_path / "tree")
    out = sast.scan(tmp_path / "tree", python=scorer_py, semgrep_bin=str(fake), pro_configs=["p/python"])
    pro = out["tools"]["semgrep-pro"]
    assert pro["ok"] is False and "logged in" in pro["reason"] and pro["reproducible"] is False
    assert out["tools"]["bandit"]["ok"] is True


def test_scan_clean_vs_vulnerable(tmp_path, scorer_py):  # noqa: F811
    ce = [str(RULES[0])] if (RULES and SEMGREP) else []
    res = {}
    for v in ("clean", "vuln"):
        shutil.copytree(APP / v, tmp_path / v)
        res[v] = sast.scan(tmp_path / v, python=scorer_py, semgrep_bin=SEMGREP, ce_configs=ce)
    clean = [sast.Finding(**f) for f in res["clean"]["findings"]]
    vuln = [sast.Finding(**f) for f in res["vuln"]["findings"]]
    assert not [f for f in clean if f.severity in ("high", "medium")]
    got = {(f.tool, f.rule.split(".")[-1], f.severity) for f in vuln}
    assert ("bandit", "B602", "high") in got and ("bandit", "B301", "medium") in got
    if ce:
        assert ("semgrep-ce", "subprocess-shell-true", "high") in got
        assert ("semgrep-ce", "avoid-pickle", "medium") in got
        assert res["vuln"]["tools"]["semgrep-ce"]["reproducible"] is True
    else:
        pytest.skip("semgrep or the pinned rules are not installed (lrae install-scorer)")
    assert res["vuln"]["tools"]["bandit"]["version"]
    json.dumps(res["vuln"])  # serialisable for scorer.jsonl


# --- Java (jira-re): scoring.security.languages: [java] -----------------------------------------------

def _java_tree(tmp_path, variant: str):
    """The fixture's product code plus the copies a Maven workspace also holds: a test, a test class outside
    src/test (jira-re's visible API tests in spec/), build output, the agent's subagent worktrees (seen in the
    JR1 pilot) and decompiled sources. Only the product code is scanned."""
    tree = tmp_path / variant
    shutil.copytree(JAVA_APP / variant, tree)
    vuln = (JAVA_APP / "vuln" / "src" / "main" / "java" / "com" / "example" / "plugin" / "ReportResource.java").read_text()
    for rel in ("src/test/java/com/example/plugin/ReportResourceTest.java",
                "spec/api-tests/cleanroom/ReportResourceTest.java", "src/it/ReportResourceIT.java",
                "target/generated-sources/com/example/plugin/ReportResource.java",
                ".claude/worktrees/agent-a1/src/main/java/com/example/plugin/ReportResource.java",
                ".decompiled/com/example/plugin/ReportResource.java",
                "vendor/lib/ReportResource.java"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_text(vuln)
    return tree


def test_java_product_files(tmp_path):
    tree = _java_tree(tmp_path, "vuln")
    (tree / "tools.py").write_text("x = 1\n")
    assert [p.as_posix() for p in sast.collect_product_files(tree, ["java"])] == [
        "src/main/java/com/example/plugin/ReportResource.java"]
    assert [p.as_posix() for p in sast.collect_product_files(tree, ["python"])] == ["tools.py"]
    assert len(sast.collect_product_files(tree, ["python", "java"])) == 2


def test_java_only_tree_skips_bandit_with_a_reason(tmp_path, scorer_py):  # noqa: F811
    out = sast.scan(_java_tree(tmp_path, "vuln"), python=scorer_py, languages=["java"])
    assert out["tools"]["bandit"] == {"ok": True, "reason": "no python files", "version": None,
                                      "reproducible": True, "n": 0}


def test_semgrep_without_product_files_reports_it(tmp_path, scorer_py):  # noqa: F811
    (tmp_path / "tree").mkdir()
    out = sast.scan(tmp_path / "tree", python=scorer_py, semgrep_bin="semgrep", ce_configs=["/rules/java"],
                    languages=["java"])
    assert out["tools"]["semgrep-ce"]["reason"] == "no java files" and out["findings"] == []


def test_scan_java_clean_vs_vulnerable(tmp_path, scorer_py):  # noqa: F811
    if not (JAVA_RULES and SEMGREP):
        pytest.skip("semgrep or the pinned rules are not installed (lrae install-scorer)")
    res = {v: sast.scan(_java_tree(tmp_path, v), python=scorer_py, semgrep_bin=SEMGREP,
                        ce_configs=[str(JAVA_RULES[0])], languages=["java"]) for v in ("clean", "vuln")}
    for v in res.values():
        assert v["tools"]["semgrep-ce"]["ok"] and v["tools"]["semgrep-ce"]["reproducible"]
    assert res["clean"]["findings"] == []
    vuln = [sast.Finding(**f) for f in res["vuln"]["findings"]]
    assert {f.path for f in vuln} == {"src/main/java/com/example/plugin/ReportResource.java"}   # no copies
    got = {(f.rule.split(".")[-1], f.severity) for f in vuln}
    assert {("formatted-sql-string", "high"), ("jdbc-sqli", "medium"), ("no-direct-response-writer", "medium"),
            ("documentbuilderfactory-disallow-doctype-decl-missing", "high"),
            ("object-deserialization", "medium"), ("use-of-md5", "medium")} <= got
    assert all(f.tool == "semgrep-ce" for f in vuln)
