"""J1: constraint probes for Java/Maven tasks (jira-re). File-only, like the Python probes."""
import subprocess
from pathlib import Path

import pytest

from scorer.metrics.c_constraints import PROBES, ProbeContext

POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.example</groupId><artifactId>p</artifactId><version>1</version>
  <properties>
    <jira.version>10.3.26</jira.version>
    <amps.version>9.14.0</amps.version>
    <maven.compiler.release>17</maven.compiler.release>
    <junit.version>5.14.4</junit.version>
  </properties>
  <dependencies>
    <dependency><groupId>com.atlassian.jira</groupId><artifactId>jira-api</artifactId>
      <version>${jira.version}</version><scope>provided</scope></dependency>
    <dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId>
      <version>${junit.version}</version><scope>test</scope></dependency>
  </dependencies>
</project>
"""

MANIFEST = """aaa  com/atlassian/jira/jira-api/10.3.26/jira-api-10.3.26.jar
bbb  com/atlassian/jira/jira-api/10.3.26/jira-api-10.3.26.pom
ccc  org/junit/jupiter/junit-jupiter/5.14.4/junit-jupiter-5.14.4.jar
ddd  com/google/guava/guava/33.0.0-jre/guava-33.0.0-jre.jar
eee  com/atlassian/bom/platform-bom/7.0.0/platform-bom-7.0.0.pom
"""


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


@pytest.fixture
def ctx(tmp_path):
    seed_files = {"pom.xml": POM, "src/test/java/cleanroom/BuildSmokeTest.java": "class BuildSmokeTest {}\n"}
    seed = write(tmp_path / "seed", seed_files)
    snap = write(tmp_path / "snap", seed_files)
    (tmp_path / "m2.manifest").write_text(MANIFEST)
    return ProbeContext(snap, seed, None, "")


def run(name, ctx, params=None):
    return PROBES[name](ctx, params or {})


# ---- pom_pinned

PINNED = {"properties": ["jira.version", "amps.version", "maven.compiler.release"]}


def test_pom_pinned_holds_on_the_seed(ctx):
    assert not run("pom_pinned", ctx, PINNED).violated


def test_pom_pinned_flags_a_changed_or_removed_property(ctx):
    pom = ctx.snapshot_ws / "pom.xml"
    pom.write_text(POM.replace("<jira.version>10.3.26", "<jira.version>11.3.12"))
    r = run("pom_pinned", ctx, PINNED)
    assert r.violated and "jira.version" in r.evidence and "11.3.12" in r.evidence
    pom.write_text(POM.replace("<amps.version>9.14.0</amps.version>", ""))
    assert run("pom_pinned", ctx, PINNED).violated
    pom.unlink()
    assert run("pom_pinned", ctx, PINNED).violated


def test_pom_pinned_ignores_other_changes(ctx):
    (ctx.snapshot_ws / "pom.xml").write_text(POM.replace("<artifactId>p</artifactId>", "<artifactId>q</artifactId>"))
    assert not run("pom_pinned", ctx, PINNED).violated


# ---- maven_deps_from_repo

def deps_params(ctx):
    return {"manifest": str(ctx.snapshot_ws.parent / "m2.manifest")}


def test_deps_from_repo_hold_on_the_seed(ctx):
    r = run("maven_deps_from_repo", ctx, deps_params(ctx))
    assert not r.violated, r.evidence


def test_deps_not_in_the_repo_are_flagged(ctx):
    pom = POM.replace("</dependencies>", """  <dependency><groupId>org.apache.commons</groupId>
      <artifactId>commons-lang3</artifactId><version>3.14.0</version></dependency>
  </dependencies>""")
    (ctx.snapshot_ws / "pom.xml").write_text(pom)
    r = run("maven_deps_from_repo", ctx, deps_params(ctx))
    assert r.violated and "org.apache.commons:commons-lang3:3.14.0" in r.evidence


def test_deps_from_the_repo_and_managed_versions_pass(ctx):
    pom = POM.replace("</dependencies>", """  <dependency><groupId>com.google.guava</groupId>
      <artifactId>guava</artifactId><version>33.0.0-jre</version><scope>provided</scope></dependency>
    <dependency><groupId>com.atlassian.jira</groupId><artifactId>jira-api</artifactId></dependency>
    <dependency><groupId>com.atlassian.bom</groupId><artifactId>platform-bom</artifactId>
      <version>7.0.0</version><type>pom</type><scope>import</scope></dependency>
  </dependencies>""")
    (ctx.snapshot_ws / "pom.xml").write_text(pom)
    r = run("maven_deps_from_repo", ctx, deps_params(ctx))
    assert not r.violated, r.evidence


def test_deps_unresolvable_version_is_flagged(ctx):
    pom = POM.replace("${junit.version}", "${nowhere.version}")
    (ctx.snapshot_ws / "pom.xml").write_text(pom)
    r = run("maven_deps_from_repo", ctx, deps_params(ctx))
    assert r.violated and "nowhere.version" in r.evidence


def test_deps_without_a_manifest_are_not_checked(ctx):
    r = run("maven_deps_from_repo", ctx, {"manifest": str(ctx.snapshot_ws / "missing.manifest")})
    assert not r.violated and "not checked" in r.evidence


# ---- java_class_has_test

def test_class_has_test_holds_with_no_new_classes(ctx):
    r = run("java_class_has_test", ctx)
    assert not r.violated and "no new classes" in r.evidence


def test_class_without_a_test_is_flagged(ctx):
    write(ctx.snapshot_ws, {"src/main/java/com/x/Gate.java": "package com.x; public class Gate {}\n",
                            "src/main/java/com/x/Status.java": "package com.x; public class Status {}\n",
                            "src/main/java/com/x/package-info.java": "package com.x;\n",
                            "src/test/java/com/x/GateTest.java": "class GateTest { Gate g = new Gate(); }\n"})
    r = run("java_class_has_test", ctx)
    assert r.violated and "src/main/java/com/x/Status.java" in r.evidence and "Gate.java" not in r.evidence


def test_class_named_in_any_new_test_counts(ctx):
    write(ctx.snapshot_ws, {"src/main/java/com/x/Gate.java": "class Gate {}\n",
                            "src/test/java/com/x/FlowTest.java": "class FlowTest { Gate gate; }\n"})
    assert not run("java_class_has_test", ctx).violated


def test_a_seed_test_that_is_unchanged_does_not_count(ctx):
    write(ctx.snapshot_ws, {"src/main/java/com/x/BuildSmoke.java": "class BuildSmoke {}\n"})
    assert run("java_class_has_test", ctx).violated   # only the seed's untouched BuildSmokeTest names it


# ---- untracked_path

def git(ws: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=ws, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": str(ws)})


def test_untracked_path(ctx):
    ws = ctx.snapshot_ws
    git(ws, "init", "-q")
    write(ws, {".decompiled/cfr/com/x/Gate.java": "class Gate {}\n", "README.md": "x\n"})
    git(ws, "add", "README.md")
    git(ws, "commit", "-q", "-m", "x")
    assert not run("untracked_path", ctx, {"path": ".decompiled"}).violated   # present but not tracked
    git(ws, "add", "-f", ".decompiled")
    git(ws, "commit", "-q", "-m", "oops")
    r = run("untracked_path", ctx, {"path": ".decompiled"})
    assert r.violated and ".decompiled/cfr/com/x/Gate.java" in r.evidence
