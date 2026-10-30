"""jira-re task fixtures (docs/jira-re-design.md): spec, stages, seed, constraints, target tools, hidden suite."""
import json
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


def test_spec_is_for_an_implementer():
    """Design §7.2: no REA, no jar in the seed; the scorer reads the jar harness-side."""
    s = load_spec(SPEC).spec
    assert s.task.toolchain.dir == "~/lrae-tools/re" and s.task.counterparts.rea is None
    assert s.scoring.behavior.agent_suite_runner == "maven" and s.scoring.clean_room.enabled
    assert Path(s.scoring.clean_room.jar) == TASK / "vendor"          # a dir: the spec names no jar
    assert s.budget.per_run_usd == 200.0 and s.agent.model == "claude-opus-5-5"
    assert "spec/**" in s.task.protected_paths and "Edit(spec/**)" in s.task.permissions.deny
    assert not any("vendor" in d for d in s.task.permissions.deny)


def test_seed_has_no_jar_and_no_reverse_engineering_tools():
    assert not list(SEED.rglob("*.jar")) and not (SEED / "vendor").exists()
    text = "\n".join(p.read_text() for p in SEED.rglob("*") if p.is_file() and p.suffix in (".md", ".sh", ".xml"))
    for word in ("vendor/", "decompil", "jadx", "vineflower", "mcp__rea", "javap"):
        assert word not in text.lower(), word
    assert (SEED / "spec" / "README.md").is_file()


def test_stages_and_briefs():
    plan = load_stages(TASK / "stages.yaml")
    assert [st.id for st in plan.stages] == list(range(7))
    assert plan.stages[-1].kind == "release" and all(st.status_block for st in plan.stages)
    for st in plan.stages:
        assert Path(st.prompt).is_file()
    assert "spec/" in (TASK / "stage0.md").read_text() and "decompil" not in (TASK / "stage0.md").read_text()
    cr = plan.stages[5]
    assert cr.kind == "change_request" and cr.env_actions[0].params["path"] == "spec/CHANGES-1.md"


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
    shutil.copytree(SEED, seed)
    c, detail = score_constraints(ProbeContext(seed, seed, None, ""), constraints)
    assert c == 0, detail
    ws = tmp_path / "ws"                     # the stage-5 change request is allowed into spec/
    shutil.copytree(SEED, ws)
    (ws / "spec" / "CHANGES-1.md").write_text("corrections\n")
    assert score_constraints(ProbeContext(ws, seed, None, ""), constraints)[0] == 0
    (ws / "spec" / "README.md").write_text("edited by the agent\n")
    assert score_constraints(ProbeContext(ws, seed, None, ""), constraints)[0] == 1


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
    """``(target.yaml, vendor dir)``: the jar sits harness-side, next to the task (design §7.2)."""
    vendor = tmp_path / "vendor"
    vendor.mkdir(parents=True)
    _jar_with_pom(vendor / "approvals-1.4.jar", EMBEDDED_POM, '<atlassian-plugin key="com.acme.approvals"/>')
    target = tmp_path / "target.yaml"
    target.write_text(yaml.safe_dump({"jar": "approvals-1.4.jar", "sha256": "", "jira_version": "auto",
                                      "amps_version": "auto", "java_release": "auto", **fields}))
    return target, vendor


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
    target, vendor = _target(tmp_path)
    _jar_with_pom(vendor / "approvals-1.4.jar", "<project/>")
    with pytest.raises(SystemExit, match="jira_version"):
        jira_target.load(target, vendor)


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
    ws.mkdir()
    jar = tmp_path / "harness" / "p.jar"     # harness-side: the implementer's workspace has no jar
    jar.parent.mkdir()
    with zipfile.ZipFile(jar, "w") as z:
        for f in classes.rglob("*.class"):
            z.write(f, f.relative_to(classes).as_posix())
        z.writestr("atlassian-plugin.xml", '<atlassian-plugin key="com.acme.p"><plugin-info/>'
                                           '<workflow-validator key="gate" class="com.acme.Gate"/></atlassian-plugin>')
    files = {
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
                         env={"LRAE_WORKSPACE": str(ws), "LRAE_TARGET_JAR": str(jar), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
    assert res.returncode == 0 and "F" not in res.stdout.splitlines()[0], res.stdout[-2000:]
    sys.path.insert(0, str(TASK / "hidden"))
    from _support import reference
    assert reference(jar).resolve("com.acme.Gate.Rule#w")     # method-level grounding on real class files


# --- found on the first real jar (2026-10-26): several embedded poms, jira.compile.version, vendor modules ---

SUBMODULE_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.acme.approvals</groupId><artifactId>aaa-helper</artifactId><version>1.4</version>
</project>
"""

PLUGIN_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.acme.approvals</groupId><artifactId>approvals</artifactId><version>1.4</version>
  <packaging>atlassian-plugin</packaging>
  <properties><jira.compile.version>9.12.0</jira.compile.version><amps.version>9.2.3</amps.version>
    <sal.version>5.0.5</sal.version></properties>
  <dependencies>
    <dependency><groupId>com.atlassian.jira</groupId><artifactId>jira-api</artifactId>
      <version>${jira.compile.version}</version><scope>provided</scope></dependency>
    <dependency><groupId>com.atlassian.sal</groupId><artifactId>sal-api</artifactId><version>${sal.version}</version>
      <scope>provided</scope></dependency>
    <dependency><groupId>com.acme.approvals</groupId><artifactId>approvals-api</artifactId><version>1.4</version></dependency>
    <dependency><groupId>com.acme.shared</groupId><artifactId>acme-commons</artifactId><version>3.0</version></dependency>
  </dependencies>
</project>
"""


def test_the_plugin_pom_wins_over_submodule_poms(tmp_path):
    import jira_target
    target, vendor = _target(tmp_path)
    with zipfile.ZipFile(vendor / "approvals-1.4.jar", "w") as z:
        z.writestr("META-INF/maven/com.acme.approvals/aaa-helper/pom.xml", SUBMODULE_POM)   # sorts first
        z.writestr("META-INF/maven/com.acme.approvals/approvals/pom.xml", PLUGIN_POM)
        z.writestr("atlassian-plugin.xml", '<atlassian-plugin key="com.acme.approvals"/>')
    t = jira_target.load(target, vendor)
    assert t.pom_name == "META-INF/maven/com.acme.approvals/approvals/pom.xml"
    assert (t.jira_version, t.amps_version, t.java_release) == ("9.12.0", "9.2.3", "11")
    assert t.sources["jira_version"] == "embedded pom (jira.compile.version)"
    # the vendor's own modules are part of what gets rewritten, never a dependency of the rewrite
    assert [d.coords for d in t.original_deps] == ["com.atlassian.jira:jira-api:9.12.0", "com.atlassian.sal:sal-api:5.0.5"]
    assert t.vendor_deps == ["com.acme.approvals:approvals-api:1.4", "com.acme.shared:acme-commons:3.0"]


def test_priming_drops_dependencies_no_public_repository_has():
    import jira_target
    import prime_maven_repo
    deps = [jira_target.Dep("com.atlassian.jira", "jira-api", "9.12.0"), jira_target.Dep("com.x", "private", "1")]
    seen = []

    def exists(url: str) -> bool:
        seen.append(url)
        return "private" not in url
    kept, dropped = prime_maven_repo.available(deps, exists=exists)
    assert [d.artifact for d in kept] == ["jira-api"] and dropped == ["com.x:private:1"]
    assert any(u.endswith("com/atlassian/jira/jira-api/9.12.0/jira-api-9.12.0.pom") for u in seen)


def test_availability_check_fails_loudly_on_network_errors(monkeypatch):
    """A TLS or network failure is not "missing": treating it so silently dropped every dependency (2026-10-26)."""
    import subprocess as sp

    import prime_maven_repo

    def fake_run(cmd, **kw):
        code = {"ok": "200", "gone": "404"}.get(cmd[-1].rsplit("/", 1)[-1].split("-")[0], "000")
        return sp.CompletedProcess(cmd, 0 if code != "000" else 60, stdout=code, stderr="")
    monkeypatch.setattr(prime_maven_repo.subprocess, "run", fake_run)
    assert prime_maven_repo._url_exists("https://x/a/ok-1.pom") is True
    assert prime_maven_repo._url_exists("https://x/a/gone-1.pom") is False
    with pytest.raises(RuntimeError, match="cannot reach"):
        prime_maven_repo._url_exists("https://x/a/tls-1.pom")


# --- found priming the real jar (2026-10-26): Jira 9.12's poms pull artifacts no public repository has ---

MAVEN_MISSING = """[ERROR] Failed to execute goal on project cleanroom-plugin: Could not resolve dependencies
[ERROR] dependency: commons-httpclient:commons-httpclient:jar:3.1-jenkins-3 (provided)
[ERROR] \tCould not find artifact commons-httpclient:commons-httpclient:jar:3.1-jenkins-3 in atlassian-external (https://x/)
[ERROR] \tCould not find artifact commons-httpclient:commons-httpclient:jar:3.1-jenkins-3 in central (https://y/)
[ERROR] \tCould not find artifact jndi:jndi:jar:1.2.1 in central (https://y/)
"""


def test_missing_artifacts_are_parsed_from_maven_output():
    import prime_maven_repo
    assert prime_maven_repo.missing_artifacts(MAVEN_MISSING) == ["commons-httpclient:commons-httpclient", "jndi:jndi"]
    assert prime_maven_repo.missing_artifacts("[INFO] BUILD SUCCESS") == []
    cached = ("[ERROR] \tjndi:jndi:jar:1.2.1 was not found in https://y/ during a previous attempt. This failure was"
              " cached in the local repository\n[ERROR] \tcommons-httpclient:commons-httpclient:jar:3.1-jenkins-3 was"
              " not found in https://x/ during a previous attempt.")
    assert prime_maven_repo.missing_artifacts(cached) == ["jndi:jndi", "commons-httpclient:commons-httpclient"]


def test_exclusions_are_pinned_into_the_seed_pom_idempotently(tmp_path):
    import xml.etree.ElementTree as ET

    import jira_target
    t = jira_target.load(*_target(tmp_path, maven_exclusions=["jndi:jndi", "commons-httpclient:commons-httpclient"]))
    assert t.exclusions == ["commons-httpclient:commons-httpclient", "jndi:jndi"]
    once = jira_target.render_seed_pom((SEED / "pom.xml").read_text(), t)
    assert jira_target.render_seed_pom(once, t) == once
    root = ET.fromstring(once)
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    api = [d for d in root.iterfind(".//m:dependency", ns) if d.findtext("m:artifactId", namespaces=ns) == "jira-api"][0]
    excl = sorted(f"{e.findtext('m:groupId', namespaces=ns)}:{e.findtext('m:artifactId', namespaces=ns)}"
                  for e in api.iterfind("m:exclusions/m:exclusion", ns))
    assert excl == ["commons-httpclient:commons-httpclient", "jndi:jndi"]
    none = jira_target.render_seed_pom(once, jira_target.load(*_target(tmp_path / "b")))
    assert "<exclusion>" not in none                          # cleared again when the list is empty


def test_priming_pom_applies_exclusions_to_added_dependencies():
    import jira_target
    import prime_maven_repo
    out = prime_maven_repo.priming_pom((SEED / "pom.xml").read_text(),
                                       [jira_target.Dep("com.atlassian.jira", "jira-core", "9.12.0")],
                                       exclusions=["jndi:jndi"])
    core = out[out.index("<artifactId>jira-core</artifactId>"):]
    assert "<groupId>jndi</groupId>" in core[:core.index("</dependency>")]


# --- JA: the analyst's spec is checked once, harness-side (analyst/check_spec.py; design §7.2) ---

def _analyst_fixture(tmp_path: Path):
    """A synthetic two-module plugin and a complete, clean analyst spec for it."""
    jar = tmp_path / "p.jar"
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr("com/acme/Gate.class", b"not parsed")            # class-level grounding only
        z.writestr("com/acme/internal/RuleEngine.class", b"not parsed")
        z.writestr("atlassian-plugin.xml", '<atlassian-plugin key="com.acme.p"><plugin-info/>'
                                           '<workflow-validator key="gate" class="com.acme.Gate"/>'
                                           '<component key="engine" class="com.acme.internal.RuleEngine"/>'
                                           '<component-import key="imp" interface="x.Y"/></atlassian-plugin>')
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "SPEC.md").write_text("# Contract\nThe validator class is com.acme.Gate (persisted in workflows).\n"
                                  "| key | type |\n|---|---|\n| `gate` | `workflow-validator` |\n"
                                  "| `engine` | `component` |\n")
    (spec / "INVENTORY.md").write_text("A gate.\n")
    (spec / "inventory.json").write_text(
        '{"plugin": {"key": "com.acme.p"}, "modules": ['
        '{"key": "gate", "type": "workflow-validator", "class": "com.acme.Gate", "purpose": "checks"},'
        '{"key": "engine", "type": "component", "class": null, "purpose": "rules"}]}')
    (spec / "claims.jsonl").write_text(
        '{"id": "C-0001", "module": "gate", "behaviour": "When x, y.", "confidence": "high", "status": "active"}\n'
        '{"id": "C-0002", "module": "engine", "behaviour": "When a, b.", "confidence": "medium", "status": "active"}\n')
    analyst = tmp_path / "analyst"
    analyst.mkdir()
    (analyst / "claims-evidence.jsonl").write_text('{"id": "C-0001", "evidence": ["com.acme.Gate"]}\n'
                                                    '{"id": "C-0002", "evidence": ["com.acme.internal.RuleEngine"]}\n')
    (analyst / "contract-classes.txt").write_text("com.acme.Gate   # workflow definitions persist it\n")
    (analyst / "spec-changes-1.md").write_text("# Corrections\n- C-0002 retracted, see C-0003.\n")
    return jar, spec, analyst


def _check(jar, spec, analyst):
    sys.path.insert(0, str(TASK / "analyst"))
    import check_spec
    return check_spec.check(jar=jar, spec_dir=spec, analyst_dir=analyst)


def test_spec_check_passes_a_complete_clean_spec(tmp_path):
    report = _check(*_analyst_fixture(tmp_path))
    assert report.problems == [] and report.modules == 2 and report.claimed == 2


def test_spec_check_finds_gaps_leaks_and_bad_evidence(tmp_path):
    jar, spec, analyst = _analyst_fixture(tmp_path)
    (spec / "claims.jsonl").write_text(
        '{"id": "C-0001", "module": "gate", "behaviour": "x", "confidence": "high", "status": "active",'
        ' "evidence": ["com.acme.Gate"]}\n')
    (spec / "SPEC.md").write_text("Internally com.acme.internal.RuleEngine does it.\n")
    (analyst / "claims-evidence.jsonl").write_text('{"id": "C-0001", "evidence": ["com.acme.Nope"]}\n')
    (analyst / "spec-changes-1.md").write_text("PLACEHOLDER: later\n")
    text = "\n".join(_check(jar, spec, analyst).problems)
    assert "engine" in text and "no active claim" in text                   # coverage
    assert "C-0001" in text and "evidence" in text and "claims.jsonl" in text  # evidence in the implementer's copy
    assert "com.acme.Nope" in text                                          # grounding
    assert "com.acme.internal.RuleEngine" in text and "SPEC.md" in text      # leaked internal name
    assert "placeholder" in text.lower()


def test_spec_check_finds_internal_simple_class_names(tmp_path):
    """A bare CamelCase name of an internal class leaks as much as its dotted name; a word the contract
    needs (a URL alias equal to a class name) is allowed by listing it alone in contract-classes.txt."""
    jar, spec, analyst = _analyst_fixture(tmp_path)
    (spec / "INVENTORY.md").write_text("The RuleEngine evaluates rules; a Gate checks; RulesEngineering is fine.\n")
    text = "\n".join(_check(jar, spec, analyst).problems)
    assert "INVENTORY.md" in text and "RuleEngine" in text and "Gate" not in text, text
    with (analyst / "contract-classes.txt").open("a") as f:
        f.write("RuleEngine   # the word is also a contract URL alias\n")
    assert _check(jar, spec, analyst).problems == []


def test_spec_check_finds_acronym_led_internal_names(tmp_path):
    """JC2: a simple name that starts with an acronym (``AOBasedStore``) is a CamelCase name too, also inside a
    dotted key whose package is not the class's own; all-capital words and plain words stay allowed."""
    jar, spec, analyst = _analyst_fixture(tmp_path)
    with zipfile.ZipFile(jar, "a") as z:
        z.writestr("com/acme/internal/AOBasedStore.class", b"not parsed")
    (spec / "INVENTORY.md").write_text("Tune `com.acme.old.AOBasedStore.limit`; JSON and Gate are words.\n")
    text = "\n".join(_check(jar, spec, analyst).problems)
    assert "AOBasedStore" in text and "JSON" not in text and "Gate" not in text, text


def test_spec_check_sees_internal_classes_in_bundled_jars(tmp_path):
    """Internal code also ships in jars under META-INF/lib (the vendor's commons and compat libraries, named
    by ``internal_libs`` globs); their classes leak like the plugin's own. Other bundled libraries do not."""
    import io
    jar, spec, analyst = _analyst_fixture(tmp_path)
    lib = io.BytesIO()
    with zipfile.ZipFile(lib, "w") as z:
        z.writestr("com/acme/commons/SharedHelper.class", b"not parsed")
    third = io.BytesIO()
    with zipfile.ZipFile(third, "w") as z:
        z.writestr("org/other/ThirdPartyThing.class", b"not parsed")
    with zipfile.ZipFile(jar, "a") as z:
        z.writestr("META-INF/lib/acme-commons-1.0.jar", lib.getvalue())
        z.writestr("META-INF/lib/other-2.0.jar", third.getvalue())
    (spec / "INVENTORY.md").write_text("Uses com.acme.commons.SharedHelper, a SharedHelper and a ThirdPartyThing.\n")
    sys.path.insert(0, str(TASK / "analyst"))
    import check_spec
    text = "\n".join(check_spec.check(jar=jar, spec_dir=spec, analyst_dir=analyst,
                                      libs=["META-INF/lib/acme-commons-*.jar"]).problems)
    assert "com.acme.commons.SharedHelper" in text and "names internal class SharedHelper by" in text, text
    assert "ThirdPartyThing" not in text


def test_evidence_may_point_into_bundled_internal_libraries(tmp_path):
    """JS1 (owner, 2026-10-28): much of the original's logic lives in the vendor's internal libraries, so
    evidence grounds against their classes too, once ``internal_libs`` names them."""
    import io
    jar, spec, analyst = _analyst_fixture(tmp_path)
    lib = io.BytesIO()
    with zipfile.ZipFile(lib, "w") as z:
        z.writestr("com/acme/commons/Summer.class", b"not parsed")
    with zipfile.ZipFile(jar, "a") as z:
        z.writestr("META-INF/lib/acme-commons-1.0.jar", lib.getvalue())
    (analyst / "claims-evidence.jsonl").write_text('{"id": "C-0001", "evidence": ["com.acme.Gate"]}\n'
                                                    '{"id": "C-0002", "evidence": ["com.acme.commons.Summer"]}\n')
    sys.path.insert(0, str(TASK / "analyst"))
    sys.path.insert(0, str(TASK / "hidden"))
    import check_spec
    from _support import reference
    libs = ["META-INF/lib/acme-commons-*.jar"]
    assert reference(jar, libs).resolve("com.acme.commons.Summer") and not reference(jar).resolve("com.acme.commons.Summer")
    assert set(reference(jar, libs).classes) - set(reference(jar).classes) == {"com.acme.commons.Summer"}
    without = check_spec.check(jar=jar, spec_dir=spec, analyst_dir=analyst).problems
    assert "claims-evidence.jsonl: C-0002: com.acme.commons.Summer is not in the jar" in without
    assert check_spec.check(jar=jar, spec_dir=spec, analyst_dir=analyst, libs=libs).problems == []


def test_the_spec_rules_out_contacting_the_vendor():
    """Owner, 2026-10-28: the replacement keeps the module keys of the phone-home parts but never contacts the
    vendor (licence reports, usage statistics upload, Marketplace update check)."""
    inv = json.loads((SEED / "spec" / "inventory.json").read_text())
    purpose = {m["key"]: m["purpose"] for m in inv["modules"]}
    for key in ("app-support-client", "app-support-connector", "plugin-update-checker", "statistics-manager"):
        assert "Out of scope" in purpose[key], key
    assert "Out of scope: contacting the vendor" in (SEED / "spec" / "INVENTORY.md").read_text()


def test_inventory_is_built_from_the_descriptor_and_the_analysts_notes(tmp_path):
    """build_inventory.py: contract fields come from the declaration for the pinned Jira; internal class
    names never reach spec/, contract classes and exported API interfaces do."""
    sys.path.insert(0, str(TASK / "analyst"))
    import build_inventory
    jar = tmp_path / "p.jar"
    with zipfile.ZipFile(jar, "w") as z:
        for c in ("com/acme/Gate", "com/acme/internal/RuleEngine", "com/acme/F9", "com/acme/F10"):
            z.writestr(c + ".class", b"not parsed")
        z.writestr("com/acme/internal/Board.class", _mini_class("com/acme/internal/Board"))
        z.writestr("atlassian-plugin.xml",
                   '<atlassian-plugin key="com.acme.p" name="P"><plugin-info><version>1.2</version></plugin-info>'
                   '<workflow-validator key="gate" class="com.acme.internal.RuleEngine">'
                   '<validator-class>com.acme.Gate</validator-class></workflow-validator>'
                   '<component key="engine" public="true" class="com.acme.internal.RuleEngine">'
                   '<interface>com.acme.api.Engine</interface></component>'
                   '<servlet-filter key="f" class="com.acme.F10" location="before-dispatch">'
                   '<restrict application="jira" version="[10.0.0,)"/><url-pattern>/ten/*</url-pattern></servlet-filter>'
                   '<servlet-filter key="f" class="com.acme.F9" location="before-dispatch">'
                   '<restrict application="jira" version="[9.0.0,10.0.0)"/><url-pattern>/nine/*</url-pattern></servlet-filter>'
                   '<webwork1 key="ww" class="java.lang.Object"><actions>'
                   '<action name="com.acme.internal.Board" alias="Board"><command name="edit" alias="Board"/>'
                   '</action></actions></webwork1>'
                   '<web-item key="wi" section="top" weight="10"><label key="wi.label"/>'
                   '<link>/secure/Board.jspa</link></web-item></atlassian-plugin>')
    notes = {"groups": {"ui": "pages"}, "modules": {"gate": {"purpose": "checks", "group": "ui",
                                                            "contract_notes": ["CLASS: com.acme.Gate"]}}}
    inv = build_inventory.build(jar, notes, {"com.acme.Gate"}, "9.12.0", {"wi.label": "Board"})
    mods = {m["key"]: m for m in inv["modules"]}
    assert inv["plugin"] == {"key": "com.acme.p", "name": "P", "plugins_version": None, "version": "1.2",
                             "jira_version": "9.12.0", "modules": 5}
    assert mods["gate"]["class"] == "com.acme.Gate" and mods["gate"]["purpose"] == "checks"
    assert "contract_notes" not in mods["gate"]
    assert mods["engine"]["class"] is None and mods["engine"]["contract"]["exports"] == ["com.acme.api.Engine"]
    assert mods["f"]["contract"]["url_patterns"] == ["/nine/*"] and mods["f"]["contract"]["declared_per_jira_range"]
    assert mods["ww"]["contract"]["actions"] == [{"alias": "Board", "commands": ["edit"]}]
    assert mods["wi"]["contract"]["label"] == "Board"
    assert "com.acme.internal" not in json.dumps(inv) and "com.acme.F9" not in json.dumps(inv)


@pytest.mark.local
def test_inventory_lists_webwork_commands_found_on_the_action_classes(tmp_path):
    """Webwork runs `!x` through any public `doX()`, declared or not, inherited or not (a base class in a
    bundled library gives every page `!apply`); `doExecute` is the plain URL, not a command."""
    javac = shutil.which("javac")
    if not javac or subprocess.run([javac, "-version"], capture_output=True).returncode != 0:
        pytest.skip("needs a JDK")
    sys.path.insert(0, str(TASK / "analyst"))
    import build_inventory
    src = tmp_path / "src" / "com" / "acme"
    src.mkdir(parents=True)
    (src / "Base.java").write_text("package com.acme; public abstract class Base {"
                                   " public final String doApply() { return null; }"
                                   " public final String doExecute() { return null; }"
                                   " protected String doValidation() { return null; }"
                                   " public String doSkipped(int x) { return null; }"
                                   " public void doNothing() { } }")
    (src / "Page.java").write_text("package com.acme; public class Page extends Base {"
                                   " public String doResume() { return null; } }")
    classes_dir = tmp_path / "classes"
    subprocess.run([javac, "-d", str(classes_dir), str(src / "Base.java"), str(src / "Page.java")], check=True)
    classes = {f"com.acme.{n}": (classes_dir / "com" / "acme" / f"{n}.class").read_bytes() for n in ("Base", "Page")}
    assert build_inventory.action_commands(classes, "com.acme.Page") == ["apply", "resume"]
    assert build_inventory.action_commands(classes, "com.acme.Gone") == []


def test_inventory_md_index_is_spliced_between_markers():
    sys.path.insert(0, str(TASK / "analyst"))
    import build_inventory
    inv = {"groups": {"ui": "Pages", "core": "Model"},                         # legend order is kept
           "modules": [{"key": "b", "type": "web-item", "group": "ui"}, {"key": "a", "type": "component",
                                                                      "group": "core"},
                       {"key": "c", "type": "web-resource", "group": "ui"}]}
    md = "# T\n\nprose\n<!-- index:start -->\nstale\n<!-- index:end -->\ntail\n"
    out = build_inventory.splice_index(md, inv)
    assert out.startswith("# T\n\nprose\n<!-- index:start -->\n") and out.endswith("<!-- index:end -->\ntail\n")
    assert "stale" not in out and out.index("Pages") < out.index("Model")
    assert "`b` (web-item), `c` (web-resource)" in out and "Pages" in out
    with pytest.raises(ValueError):
        build_inventory.splice_index("no markers", inv)


def test_a_module_restricted_per_jira_version_counts_once(tmp_path):
    """The real jar declares some keys up to three times, one per Jira range (``<restrict>``): one module each."""
    sys.path.insert(0, str(TASK / "hidden"))
    from _support import reference
    jar = tmp_path / "p.jar"
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr("atlassian-plugin.xml", '<atlassian-plugin key="k">'
                   '<rest key="api" path="/a"><restrict application="jira" version="[9.0.0,10.0.0)"/></rest>'
                   '<rest key="api" path="/a"><restrict application="jira" version="[10.0.0,)"/></rest>'
                   '<servlet key="s"/></atlassian-plugin>')
    assert [m.key for m in reference(jar).modules] == ["api", "s"]


def test_spec_check_wants_every_module_with_its_type(tmp_path):
    jar, spec, analyst = _analyst_fixture(tmp_path)
    (spec / "inventory.json").write_text('{"plugin": {"key": "com.acme.p"}, "modules": ['
                                         '{"key": "gate", "type": "workflow-function", "purpose": "x"}]}')
    text = "\n".join(_check(jar, spec, analyst).problems)
    assert "engine" in text and "workflow-validator" in text and "imp" not in text


# --- phase JA1: the public API in the analyst's spec ---

def _mini_class(name: str, public: bool = True, code: bool = False) -> bytes:
    """A minimal valid class file: ``name`` (dotted) extends Object, no members; with ``code``, one method
    ``public void m()`` with a body."""
    import struct

    def utf8(s: str) -> bytes:
        b = s.encode()
        return b"\x01" + struct.pack(">H", len(b)) + b
    pool = utf8(name.replace(".", "/")) + b"\x07\x00\x01" + utf8("java/lang/Object") + b"\x07\x00\x03"
    if not code:
        return (b"\xca\xfe\xba\xbe" + struct.pack(">HHH", 0, 52, 5) + pool
                + struct.pack(">HHHHHHH", 0x21 if public else 0x20, 2, 4, 0, 0, 0, 0))
    pool += utf8("m") + utf8("()V") + utf8("Code")
    body = struct.pack(">HHI", 0, 1, 1) + b"\xb1" + struct.pack(">HH", 0, 0)        # return
    method = struct.pack(">HHHH", 0x0001, 5, 6, 1) + struct.pack(">HI", 7, len(body)) + body
    return (b"\xca\xfe\xba\xbe" + struct.pack(">HHH", 0, 52, 8) + pool
            + struct.pack(">HHHHHH", 0x21 if public else 0x20, 2, 4, 0, 0, 1) + method + struct.pack(">H", 0))


def _api_fixture(tmp_path: Path):
    jar, spec, analyst = _analyst_fixture(tmp_path)
    api = tmp_path / "acme-api.jar"
    with zipfile.ZipFile(api, "w") as z:
        z.writestr("com/acme/api/Store.class", _mini_class("com.acme.api.Store"))
        z.writestr("com/acme/api/Ids.class", _mini_class("com.acme.api.Ids"))
        z.writestr("com/acme/api/impl/Cache.class", _mini_class("com.acme.api.impl.Cache", public=False))
    (spec / "API.md").write_text("# API\n\nIntro.\n\n## Package `com.acme.api`\n\nThe API.\n\n"
                                 "### `com.acme.api.Store`\n\nA store.\n\n### `com.acme.api.Ids`\n\nIds.\n")
    (analyst / "api-test-claims.json").write_text('{"t.StoreTest#gets": ["C-0001"]}\n')
    return jar, spec, analyst, api


def _check_api(jar, spec, analyst, api, tests=("t.StoreTest#gets",)):
    sys.path.insert(0, str(TASK / "analyst"))
    import check_spec
    return check_spec.check(jar=jar, spec_dir=spec, analyst_dir=analyst, api_jars=[api], api_tests=list(tests))


def test_spec_check_accepts_a_fully_specified_public_api(tmp_path):
    rep = _check_api(*_api_fixture(tmp_path))
    assert rep.problems == [] and (rep.api_types, rep.api_specified) == (2, 2)
    assert (rep.api_tests, rep.api_tests_claimed) == (1, 1)


def test_spec_check_wants_every_api_type_and_a_claim_behind_every_api_test(tmp_path):
    jar, spec, analyst, api = _api_fixture(tmp_path)
    (spec / "API.md").write_text((spec / "API.md").read_text().replace("### `com.acme.api.Ids`\n\nIds.\n", ""))
    (spec / "SPEC.md").write_text((spec / "SPEC.md").read_text() + "It caches in com.acme.api.impl.Cache.\n")
    (analyst / "api-test-claims.json").write_text('{"t.StoreTest#gets": ["C-0009"], "t.Gone#x": ["C-0001"]}\n')
    text = "\n".join(_check_api(jar, spec, analyst, api, tests=("t.StoreTest#gets", "t.IdsTest#parses")).problems)
    assert "com.acme.api.Ids" in text and "not specified" in text            # API coverage
    assert "com.acme.api.impl.Cache" in text and "internal" in text          # a non-public API class leaked
    assert "t.IdsTest#parses" in text and "C-0009" in text                   # every test backed by an active claim
    assert "t.Gone#x" in text                                                # stale mapping entry


def _api_with_code(tmp_path: Path):
    """The API fixture where ``com.acme.api.Ids`` carries code (its own behaviour), ``Store`` none."""
    jar, spec, analyst, api = _api_fixture(tmp_path)
    with zipfile.ZipFile(api, "w") as z:
        z.writestr("com/acme/api/Store.class", _mini_class("com.acme.api.Store"))
        z.writestr("com/acme/api/Ids.class", _mini_class("com.acme.api.Ids", code=True))
    return jar, spec, analyst, api


def _add_claim(spec: Path, analyst: Path, claim: str, evidence: str) -> None:
    with (spec / "claims.jsonl").open("a") as f:
        f.write(claim + "\n")
    with (analyst / "claims-evidence.jsonl").open("a") as f:
        f.write(evidence + "\n")


def test_every_api_type_with_code_needs_an_api_claim(tmp_path):
    """JC1: the API's own code (value and helper classes, default methods) is behaviour like a module's; a
    claim names its top-level API type in ``api`` (``module`` null), and its evidence may cite the API jar."""
    jar, spec, analyst, api = _api_with_code(tmp_path)
    rep = _check_api(jar, spec, analyst, api)
    assert rep.problems == ["claims.jsonl: no active claim describes API type 'com.acme.api.Ids'"], rep.problems
    assert (rep.api_code_types, rep.api_claimed) == (1, 0)
    _add_claim(spec, analyst,
               '{"id": "C-0003", "module": null, "api": "com.acme.api.Ids", "behaviour": "m does nothing.",'
               ' "confidence": "high", "status": "active"}',
               '{"id": "C-0003", "evidence": ["com.acme.api.Ids#m"]}')
    rep = _check_api(jar, spec, analyst, api)
    assert rep.problems == [] and (rep.api_code_types, rep.api_claimed) == (1, 1)


def test_a_claim_belongs_to_exactly_one_module_or_api_type(tmp_path):
    jar, spec, analyst, api = _api_with_code(tmp_path)
    for cid, owner in (("C-0003", '"module": null, "api": "com.acme.api.Ids"'),
                       ("C-0004", '"module": "gate", "api": "com.acme.api.Ids"'),
                       ("C-0005", '"module": null'),
                       ("C-0006", '"module": null, "api": "com.acme.api.Nope"'),
                       ("C-0007", '"module": null, "api": "com.acme.api.impl.Cache"')):
        _add_claim(spec, analyst, f'{{"id": "{cid}", {owner}, "behaviour": "b.", "confidence": "low"}}',
                   f'{{"id": "{cid}", "evidence": ["com.acme.api.Ids"]}}')
    text = "\n".join(_check_api(jar, spec, analyst, api).problems)
    assert "C-0003" not in text
    assert "C-0004: names both a module and an API type" in text
    assert "C-0005: names neither a module nor an API type" in text
    assert "C-0006: API type 'com.acme.api.Nope' is not a public top-level API type" in text
    assert "C-0007: API type 'com.acme.api.impl.Cache' is not a public top-level API type" in text


def test_spec_check_reads_jvm_form_names_too(tmp_path):
    """Generated files in spec/ (the visible signature test) name types as JVM descriptors; an internal
    class in that form is a leak too, a public API type is not."""
    jar, spec, analyst, api = _api_fixture(tmp_path)
    (spec / "api-tests").mkdir()
    (spec / "api-tests" / "SigTest.java").write_text(
        '"method public get()Lcom/acme/api/Store;"\n"method public m()Lcom/acme/api/impl/Cache;"\n'
        '"field public f:Lcom/acme/internal/RuleEngine;"\n')
    text = "\n".join(_check_api(jar, spec, analyst, api).problems)
    assert "com.acme.api.impl.Cache" in text and "com.acme.internal.RuleEngine" in text, text
    assert "com.acme.api.Store" not in text
