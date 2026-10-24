"""J1: the agent's own suite for Maven tasks (D-24): `sh build.sh test` on a temp copy, surefire XML."""
import os
import stat
from pathlib import Path

from scorer.behavior import agent_suite

REPO = Path(__file__).resolve().parents[3]
SEED_BUILD = REPO / "fixtures" / "seed_jira_re" / "build.sh"

REPORT = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="cleanroom.GateTest" tests="4" failures="1" errors="1" skipped="1">
  <testcase name="c001_accepts()" classname="cleanroom.GateTest" time="0.01"/>
  <testcase name="c002_rejects()" classname="cleanroom.GateTest"><failure message="boom">trace</failure></testcase>
  <testcase name="c003_crashes()" classname="cleanroom.GateTest"><error type="NPE"/></testcase>
  <testcase name="c004_later()" classname="cleanroom.GateTest"><skipped/></testcase>
</testsuite>
"""


def fake_tools(tmp_path: Path, script: str) -> Path:
    tools = tmp_path / "tools"
    (tools / "bin").mkdir(parents=True)
    mvn = tools / "bin" / "mvn"
    mvn.write_text("#!/bin/sh\n" + script)
    mvn.chmod(mvn.stat().st_mode | stat.S_IXUSR)
    return tools


def tree(tmp_path: Path) -> Path:
    t = tmp_path / "ws"
    t.mkdir()
    (t / "build.sh").write_text(SEED_BUILD.read_text())   # the real seed script, as the agent has it
    (t / "pom.xml").write_text("<project/>\n")
    return t


def write_report_script(report: str, rc: int) -> str:
    return (f'echo "$@" > mvn-args.txt\necho "LRAE_RE_TOOLS=$LRAE_RE_TOOLS HOME=$HOME" > mvn-env.txt\n'
            f"mkdir -p target/surefire-reports\ncat > target/surefire-reports/TEST-cleanroom.GateTest.xml <<'X'\n"
            f"{report}X\nexit {rc}\n")


def test_surefire_reports_parsed(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    (d / "TEST-a.xml").write_text(REPORT)
    (d / "TEST-broken.xml").write_text("<testsuite")          # a half-written report is ignored
    (d / "other.txt").write_text("x")
    assert agent_suite.parse_surefire_reports(d) == {
        "cleanroom.GateTest#c001_accepts()": "passed", "cleanroom.GateTest#c002_rejects()": "failed",
        "cleanroom.GateTest#c003_crashes()": "error", "cleanroom.GateTest#c004_later()": "skipped"}
    assert agent_suite.parse_surefire_reports(tmp_path / "missing") is None


def test_maven_run_counts_outcomes_and_never_touches_the_source(tmp_path):
    tools = fake_tools(tmp_path, write_report_script(REPORT, 1))
    ws = tree(tmp_path)
    own = agent_suite.run_own_suite(ws, Path("/usr/bin/python3"), runner="maven", tools_dir=tools, timeout_s=60)
    assert (own["passed"], own["failed"], own["errors"], own["skipped"], own["total"]) == (1, 1, 1, 1, 4)
    assert own["reason"] is None and agent_suite.finished(own)
    assert own["failing"] == ["cleanroom.GateTest#c002_rejects()", "cleanroom.GateTest#c003_crashes()"]
    assert not (ws / "target").exists()                     # ran on a temp copy


def test_maven_build_failure_without_reports_is_unknown(tmp_path):
    tools = fake_tools(tmp_path, "echo '[ERROR] COMPILATION ERROR'\nexit 1\n")
    own = agent_suite.run_own_suite(tree(tmp_path), Path("/usr/bin/python3"), runner="maven", tools_dir=tools,
                                    timeout_s=60)
    assert own["reason"] == "build_failed" and not agent_suite.finished(own) and own["total"] == 0


def test_maven_green_build_without_tests_is_no_tests(tmp_path):
    tools = fake_tools(tmp_path, "exit 0\n")
    own = agent_suite.run_own_suite(tree(tmp_path), Path("/usr/bin/python3"), runner="maven", tools_dir=tools,
                                    timeout_s=60)
    assert own["reason"] == "no_tests" and agent_suite.finished(own)


def test_maven_timeout(tmp_path):
    tools = fake_tools(tmp_path, "sleep 30\n")
    own = agent_suite.run_own_suite(tree(tmp_path), Path("/usr/bin/python3"), runner="maven", tools_dir=tools,
                                    timeout_s=1)
    assert own["reason"] == "suite_timeout_1s" and not agent_suite.finished(own)


def test_maven_env_is_scrubbed_and_points_at_the_toolchain(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_HOST_VAR", "x")
    dump = tmp_path / "dump"
    tools = fake_tools(tmp_path, f'env > "{dump}.env"\necho "$@" > "{dump}.args"\nexit 0\n')
    agent_suite.run_own_suite(tree(tmp_path), Path("/usr/bin/python3"), runner="maven", tools_dir=tools, timeout_s=60)
    env = dict(line.split("=", 1) for line in Path(f"{dump}.env").read_text().splitlines() if "=" in line)
    assert "SECRET_HOST_VAR" not in env and env["LRAE_RE_TOOLS"] == str(tools)
    assert env["HOME"] != os.environ["HOME"]
    args = Path(f"{dump}.args").read_text().split()
    # build.sh runs Maven offline, with "test", against the toolchain's shared tail repository
    assert "-o" in args and args[-1] == "test" and f"-Dmaven.repo.local.tail={tools}/m2" in args


def test_cache_keys_differ_by_runner(tmp_path):
    tools = fake_tools(tmp_path, write_report_script(REPORT, 1))
    ws = tree(tmp_path)
    cache = agent_suite.SuiteCache(tmp_path / "cache.json")
    m = cache.get_or_run(ws, Path("/usr/bin/python3"), runner="maven", tools_dir=tools, timeout_s=60)
    assert m["total"] == 4 and m["runner"] == "maven"
    assert agent_suite.tree_digest(ws, runner="maven") != agent_suite.tree_digest(ws)
    assert os.path.exists(tmp_path / "cache.json")
