"""jira-re task fixtures (docs/jira-re-design.md): spec, stages, seed, constraints, target tools, hidden suite."""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from runner.stages import load_stages
from scorer.metrics.c_constraints import PROBES, ProbeContext, score_constraints
from spec.loader import load_spec

REPO = Path(__file__).resolve().parents[2]
TASK = REPO / "fixtures" / "tasks" / "jira_re"
SEED = REPO / "fixtures" / "seed_jira_re"
SPEC = REPO / "spec" / "examples" / "jira-re.yaml"
sys.path.insert(0, str(TASK / "tools"))


def test_spec_loads_with_the_j1_features():
    s = load_spec(SPEC).spec
    assert s.task.toolchain.dir == "~/lrae-tools/re" and s.task.counterparts.rea.command.endswith("bin/rea-mcp")
    assert s.scoring.behavior.agent_suite_runner == "maven" and s.scoring.clean_room.enabled
    assert s.budget.per_run_usd == 200.0 and s.agent.model == "claude-opus-5-5"
    assert "vendor/**" in s.task.protected_paths and "Edit(vendor/**)" in s.task.permissions.deny


def test_stages_and_briefs():
    plan = load_stages(TASK / "stages.yaml")
    assert [st.id for st in plan.stages] == list(range(7))
    assert plan.stages[-1].kind == "release" and all(st.status_block for st in plan.stages)
    for st in plan.stages:
        assert Path(st.prompt).is_file()
    assert "external contract" in (TASK / "stage1.md").read_text()


def test_seed_rules_and_build():
    assert (SEED / "CLAUDE.md").read_bytes() == (TASK / "CLAUDE.md").read_bytes()   # D-15a
    build = (SEED / "build.sh").read_text()
    assert " -o " in build and "maven.repo.local.tail" in build and "lrae-tools/re" in build
    pom = (SEED / "pom.xml").read_text()
    for prop in ("jira.version", "amps.version", "maven.compiler.release"):
        assert f"<{prop}>" in pom
    assert "<packaging>atlassian-plugin</packaging>" in pom and "<id>atlassian-external</id>" in pom


def test_constraints_use_known_probes_and_hold_on_the_seed(tmp_path):
    constraints = yaml.safe_load((TASK / "constraints.yaml").read_text())["constraints"]
    assert all(c["probe"] in PROBES for c in constraints)
    seed = tmp_path / "seed"
    shutil.copytree(SEED, seed, ignore=shutil.ignore_patterns("*.jar"))
    c, detail = score_constraints(ProbeContext(seed, seed, None, ""), constraints)
    assert c == 0, detail


def _jar_with_pom(path: Path, pom: str, descriptor: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/maven/com.acme/approvals/pom.xml", pom)
        if descriptor:
            z.writestr("atlassian-plugin.xml", descriptor)
    return path


EMBEDDED_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.acme</groupId><artifactId>approvals</artifactId><version>1.4</version>
  <properties><jira.version>9.12.40</jira.version><sal.version>6.0.2</sal.version></properties>
  <dependencies>
    <dependency><groupId>com.atlassian.jira</groupId><artifactId>jira-api</artifactId><version>${jira.version}</version>
      <scope>provided</scope></dependency>
    <dependency><groupId>com.atlassian.sal</groupId><artifactId>sal-api</artifactId><version>${sal.version}</version>
      <scope>provided</scope></dependency>
    <dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId><version>5.10.0</version>
      <scope>test</scope></dependency>
    <dependency><groupId>com.example</groupId><artifactId>mystery</artifactId><version>${not.here}</version></dependency>
  </dependencies>
</project>
"""


def _target(tmp_path: Path, **fields) -> tuple[Path, Path]:
    seed = tmp_path / "seed"
    (seed / "vendor").mkdir(parents=True)
    _jar_with_pom(seed / "vendor" / "approvals-1.4.jar", EMBEDDED_POM, '<atlassian-plugin key="com.acme.approvals"/>')
    target = tmp_path / "target.yaml"
    target.write_text(yaml.safe_dump({"jar": "approvals-1.4.jar", "sha256": "", "jira_version": "auto",
                                      "amps_version": "auto", "java_release": "auto", **fields}))
    return target, seed


def test_target_resolution_from_the_embedded_pom(tmp_path):
    import jira_target
    t = jira_target.load(*_target(tmp_path))
    assert (t.jira_version, t.amps_version, t.java_release) == ("9.12.40", "8.17.7", "11")
    assert t.sources["jira_version"].startswith("embedded pom") and t.sources["amps_version"] == "default for Jira 9"
    assert [d.coords for d in t.original_deps] == ["com.atlassian.jira:jira-api:9.12.40", "com.atlassian.sal:sal-api:6.0.2"]
    assert len(t.skipped_deps) == 1 and "mystery" in t.skipped_deps[0] and t.plugin_key == "com.acme.approvals"


def test_target_yaml_overrides_and_pom_pinning(tmp_path):
    import jira_target
    t = jira_target.load(*_target(tmp_path, jira_version="10.3.26", java_release="21"))
    assert (t.jira_version, t.amps_version, t.java_release) == ("10.3.26", "9.14.0", "21")
    pinned = jira_target.render_seed_pom((SEED / "pom.xml").read_text(), t)
    assert "<jira.version>10.3.26</jira.version>" in pinned and "<amps.version>9.14.0</amps.version>" in pinned
    assert "<maven.compiler.release>21</maven.compiler.release>" in pinned and "UNSET" not in pinned


def test_target_without_a_version_asks_for_one(tmp_path):
    import jira_target
    target, seed = _target(tmp_path)
    _jar_with_pom(seed / "vendor" / "approvals-1.4.jar", "<project/>")
    with pytest.raises(SystemExit, match="jira_version"):
        jira_target.load(target, seed)


def test_priming_pom_adds_the_original_dependencies_once():
    import xml.etree.ElementTree as ET

    import jira_target
    import prime_maven_repo
    deps = [jira_target.Dep("com.atlassian.jira", "jira-api", "10.3.26"),
            jira_target.Dep("com.atlassian.sal", "sal-api", "6.0.2", type="pom")]
    out = prime_maven_repo.priming_pom((SEED / "pom.xml").read_text(), deps)
    ET.fromstring(out)
    assert out.count("<artifactId>jira-api</artifactId>") == 1 and "<artifactId>sal-api</artifactId>" in out
    assert "<type>pom</type>" in out


@pytest.mark.local
def test_hidden_suite_on_a_synthetic_plugin(tmp_path):
    """Compiles a two-module plugin with the local JDK; a correct workspace passes the whole suite."""
    javac = shutil.which("javac")
    if not javac or subprocess.run([javac, "-version"], capture_output=True).returncode != 0:
        pytest.skip("no JDK")
    src = tmp_path / "src" / "com" / "acme"
    src.mkdir(parents=True)
    (src / "Gate.java").write_text("package com.acme; public class Gate { public boolean validate(String s)"
                                   " { return s != null; } public static class Rule { public int w() { return 1; } } }")
    classes = tmp_path / "classes"
    subprocess.run([javac, "-d", str(classes), str(src / "Gate.java")], check=True)
    ws = tmp_path / "ws"
    (ws / "vendor").mkdir(parents=True)
    with zipfile.ZipFile(ws / "vendor" / "p.jar", "w") as z:
        for f in classes.rglob("*.class"):
            z.write(f, f.relative_to(classes).as_posix())
        z.writestr("atlassian-plugin.xml", '<atlassian-plugin key="com.acme.p"><plugin-info/>'
                                           '<workflow-validator key="gate" class="com.acme.Gate"/></atlassian-plugin>')
    files = {
        "analysis/inventory.json": '{"modules": [{"key": "gate", "type": "workflow-validator", "purpose": "x",'
                                   ' "evidence": ["com.acme.Gate#validate", "com.acme.Gate.Rule#w"]}], "classes": []}',
        "analysis/claims.jsonl": '{"id": "C-001", "module": "gate", "behaviour": "x", "evidence": ["com.acme.Gate"],'
                                 ' "confidence": "high"}\n',
        "analysis/rewrite_map.json": '{"modules": {"gate": {"status": "done", "files": ["src/main/java/n/G.java"],'
                                     ' "tests": ["src/test/java/n/GTest.java"]}}}',
        "src/main/java/n/G.java": "class G {}", "src/test/java/n/GTest.java": "class GTest {}",
        "pom.xml": "<project><groupId>com.acme</groupId><artifactId>p</artifactId></project>",
        "src/main/resources/atlassian-plugin.xml": '<atlassian-plugin key="${project.groupId}.${project.artifactId}">'
                                                   '<workflow-validator key="gate" class="n.G"/></atlassian-plugin>',
        "RELEASE.md": "gate\n",
    }
    for rel, text in files.items():
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_text(text)
    res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=TASK / "hidden",
                         env={"LRAE_WORKSPACE": str(ws), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
    assert res.returncode == 0 and "F" not in res.stdout.splitlines()[0], res.stdout[-2000:]
