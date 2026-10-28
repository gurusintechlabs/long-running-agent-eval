"""jira-re public-API tier (phase JA1, docs/jira-re-design.md §7.4): the class-file surface, the signature
comparison, the Maven-run behaviour tier and its self-check."""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TASK = REPO / "fixtures" / "tasks" / "jira_re"
sys.path.insert(0, str(TASK / "hidden"))

import _classfile as cf  # noqa: E402


# ---------------------------------------------------------------- generic signatures (pure)

@pytest.mark.parametrize("a, b", [
    ("<T:Ljava/lang/Object;>(TT;)TT;", "<E:Ljava/lang/Object;>(TE;)TE;"),
    ("<K:Ljava/lang/Object;V::Ljava/lang/Comparable<TV;>;>Ljava/lang/Object;",
     "<A:Ljava/lang/Object;B::Ljava/lang/Comparable<TB;>;>Ljava/lang/Object;"),
    ("(Ljava/util/List<+TT;>;[TU;)V", "(Ljava/util/List<+TX;>;[TY;)V"),
    ("Lx/Outer<TT;>.Inner<TU;>;", "Lx/Outer<TA;>.Inner<TB;>;"),
    ("<X:Ljava/lang/Exception;>()V^TX;", "<Q:Ljava/lang/Exception;>()V^TQ;"),
])
def test_type_variable_names_do_not_matter(a, b):
    assert cf.normalise_signature(a) == cf.normalise_signature(b)


@pytest.mark.parametrize("a, b", [
    ("<T:Ljava/lang/Object;>(TT;)TT;", "<T:Ljava/lang/Object;>(TT;)Ljava/lang/Object;"),
    ("(Ljava/util/List<+TT;>;)V", "(Ljava/util/List<-TT;>;)V"),
    ("<A:Ljava/lang/Object;B:Ljava/lang/Object;>(TA;TB;)V", "<A:Ljava/lang/Object;B:Ljava/lang/Object;>(TB;TA;)V"),
    ("Ljava/util/Map<Ljava/lang/String;*>;", "Ljava/util/Map<Ljava/lang/String;Ljava/lang/Object;>;"),
])
def test_different_generic_signatures_stay_different(a, b):
    assert cf.normalise_signature(a) != cf.normalise_signature(b)


def test_bad_signatures_raise():
    with pytest.raises(ValueError):
        cf.normalise_signature("(Ljava/util/List<")


def test_members_render_like_java():
    assert cf.render("find", "(J[Ljava/lang/String;)Ljava/util/List;") == \
        "find(long, java.lang.String[]) -> java.util.List"
    assert cf.render("<init>", "(I)V") == "<init>(int)"
    assert cf.render("MAX", "J") == "MAX: long"


# ---------------------------------------------------------------- compiled surfaces (javac)

def _javac():
    javac = shutil.which("javac")
    if not javac or subprocess.run([javac, "-version"], capture_output=True).returncode != 0:
        pytest.skip("no JDK")
    return javac


def _compile(tmp: Path, name: str, sources: dict[str, str]) -> dict[str, cf.TypeSurface]:
    src, out = tmp / name / "src", tmp / name / "classes"
    for rel, text in sources.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text)
    out.mkdir(parents=True)
    subprocess.run([_javac(), "--release", "11", "-d", str(out), *map(str, src.rglob("*.java"))], check=True)
    return cf.surface_from_classes(cf.classes_in_dir(out))


ORIGINAL = {
    "api/Store.java": """package api;
public interface Store<T extends Comparable<T>> extends Iterable<T> {
    long MAX = 99L;
    String NAME = "store";
    T get(long id) throws java.io.IOException;
    default int size() { return 0; }
    static <E extends Comparable<E>> Store<E> empty() { return null; }
}""",
    "api/Base.java": """package api;
public abstract class Base {
    protected Base(int x) {}
    public abstract void run(String... args);
    public final String label() { return ""; }
    public static class Rule { public int weight; public Rule() {} }
    static class Hidden { public void x() {} }
    private void secret() {}
    public String toString() { return "b"; }
}""",
    "api/Kind.java": "package api; public enum Kind { A, B; public boolean big() { return this == B; } }",
    "api/internal/Impl.java": "package api.internal; class Impl {}",
}


def test_an_identical_rewrite_is_compatible(tmp_path):
    want = _compile(tmp_path, "orig", ORIGINAL)
    assert set(want) == {"api.Store", "api.Base", "api.Base$Rule", "api.Kind"}   # no package/private types
    renamed = {**ORIGINAL, "api/Store.java": ORIGINAL["api/Store.java"].replace("<T extends Comparable<T>>",
               "<X extends Comparable<X>>").replace("T get", "X get").replace("Iterable<T>", "Iterable<X>")}
    got = _compile(tmp_path, "rewrite", renamed)
    assert all(cf.compare_type(t, got) == [] for t in want.values())
    s = want["api.Store"].members
    assert s["MAX:J"].constant == 99 and s["NAME:Ljava/lang/String;"].constant == "store"
    assert "default" in s["size()I"].flags and "static" in s["empty()Lapi/Store;"].flags
    assert s["get(J)Ljava/lang/Comparable;"].exceptions == ("java.io.IOException",)
    assert "varargs" in want["api.Base"].members["run([Ljava/lang/String;)V"].flags
    assert want["api.Base$Rule"].flags == ("public", "static")


@pytest.mark.parametrize("change, expect", [
    (("api/Store.java", "T get(long id)", "T get(int id)"), "missing method"),
    (("api/Store.java", " throws java.io.IOException", ""), "exceptions"),
    (("api/Store.java", "long MAX = 99L", "long MAX = 98L"), "constant"),
    (("api/Store.java", "default int size() { return 0; }", "int size();"), "flags"),
    (("api/Store.java", "Comparable<T>> extends", "Comparable<? super T>> extends"), "signature"),
    (("api/Store.java", " extends Iterable<T>", ""), "does not implement"),
    (("api/Store.java", "static <E", "void more(); static <E"), "extra abstract method"),
    (("api/Base.java", "protected Base(int x)", "public Base(int x)"), "flags"),
    (("api/Base.java", "public abstract void run(String... args);", "public void run(String[] args) {}"), "flags"),
    (("api/Base.java", "public final String label()", "public String label()"), "flags"),
    (("api/Base.java", "public static class Rule", "public class Rule"), "flags"),
    (("api/Base.java", "public int weight;", "public long weight;"), "missing field"),
    (("api/Base.java", "public static class Rule", "static class Rule"), "missing (class"),
    (("api/Kind.java", "A, B; public boolean big() { return this == B; }", "A; public boolean big() { return false; }"), "missing field"),
])
def test_incompatible_rewrites_are_named(tmp_path, change, expect):
    want = _compile(tmp_path, "orig", ORIGINAL)
    rel, old, new = change
    assert old in ORIGINAL[rel]
    got = _compile(tmp_path, "rewrite", {**ORIGINAL, rel: ORIGINAL[rel].replace(old, new)})
    problems = [p for t in want.values() for p in cf.compare_type(t, got)]
    assert problems and any(expect in p for p in problems), problems


def test_inherited_members_count_as_present(tmp_path):
    """A class that inherits a method its original re-declared is still binary compatible; Object's
    methods always reach a class."""
    want = _compile(tmp_path, "orig", ORIGINAL)
    moved = {**ORIGINAL, "api/Base.java": ORIGINAL["api/Base.java"].replace(
        'public String toString() { return "b"; }', "")}
    got = _compile(tmp_path, "rewrite", moved)
    assert cf.compare_type(want["api.Base"], got) == []


def test_the_real_api_surface_parses_and_matches_itself():
    """On this machine's real jar (harness-side; skipped elsewhere): every class file parses, and the
    surface compares clean against itself."""
    jars = sorted((TASK / "vendor" / "api").glob("*.jar"))
    if len(jars) != 1:
        pytest.skip("no extracted public API jar (prepare_seed.py)")
    classes = cf.classes_in_jar(jars[0])
    for data in classes.values():
        raw = cf.parse_class(data)
        for m in raw.methods + raw.fields:
            if "Signature" in m.attrs:
                cf.normalise_signature(raw.utf8(int.from_bytes(m.attrs["Signature"], "big")))
    surface = cf.surface_from_classes(classes)
    assert len({cf.top_level(n) for n in surface}) > 100
    assert all(cf.compare_type(t, surface) == [] for t in surface.values())


# ---------------------------------------------------------------- target: the bundled public API

sys.path.insert(0, str(TASK / "tools"))
import jira_target  # noqa: E402

API_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.acme.approvals</groupId><artifactId>approvals-api</artifactId><version>2.1</version>
  <properties><ints.version>1.1.3</ints.version></properties>
  <dependencies>
    <dependency><groupId>com.acme.ints</groupId><artifactId>ints</artifactId><version>${ints.version}</version></dependency>
    <dependency><groupId>org.slf4j</groupId><artifactId>slf4j-api</artifactId><version>1.7.30</version>
      <scope>provided</scope></dependency>
    <dependency><groupId>junit</groupId><artifactId>junit</artifactId><version>4.13</version><scope>test</scope></dependency>
  </dependencies>
</project>
"""


def _plugin_with_api(tmp_path: Path, public_api=("META-INF/lib/approvals-api-*.jar",)):
    import io
    api = io.BytesIO()
    with zipfile.ZipFile(api, "w") as z:
        z.writestr("META-INF/maven/com.acme.approvals/approvals-api/pom.xml", API_POM)
        z.writestr("com/acme/api/Gate.class", b"\xca\xfe\xba\xbe")
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    with zipfile.ZipFile(vendor / "p.jar", "w") as z:
        z.writestr("atlassian-plugin.xml", '<atlassian-plugin key="com.acme.approvals"/>')
        z.writestr("META-INF/maven/com.acme.approvals/approvals/pom.xml",
                   "<project><groupId>com.acme.approvals</groupId><artifactId>approvals</artifactId>"
                   "<packaging>atlassian-plugin</packaging><properties><jira.version>9.12.0</jira.version>"
                   "</properties></project>")
        z.writestr("META-INF/lib/approvals-api-2.1.jar", api.getvalue())
        z.writestr("META-INF/lib/poi-5.4.1.jar", b"PK")
    target = tmp_path / "target.yaml"
    target.write_text(f"jar: p.jar\npublic_api: {list(public_api)}\n")
    return target, vendor


def test_the_public_api_is_named_in_target_yaml_and_its_dependencies_are_read(tmp_path):
    target, vendor = _plugin_with_api(tmp_path)
    t = jira_target.load(target, vendor)
    assert t.public_api == ["META-INF/lib/approvals-api-2.1.jar"]
    deps = jira_target.public_api_dependencies(t)
    # the API's own non-test dependencies, interpolated; same-organisation ones are kept (availability
    # decides, prime_maven_repo.available): the API's types appear in their signatures
    assert [(d.coords, d.scope) for d in deps] == [("com.acme.ints:ints:1.1.3", "compile"),
                                                   ("org.slf4j:slf4j-api:1.7.30", "provided")]


def test_a_public_api_glob_must_match(tmp_path):
    target, vendor = _plugin_with_api(tmp_path, public_api=("META-INF/lib/nothing-*.jar",))
    with pytest.raises(SystemExit, match="public_api"):
        jira_target.load(target, vendor)


def test_without_public_api_there_is_none(tmp_path):
    target, vendor = _plugin_with_api(tmp_path)
    target.write_text("jar: p.jar\n")
    t = jira_target.load(target, vendor)
    assert t.public_api == [] and jira_target.public_api_dependencies(t) == []


def test_the_public_api_is_extracted_next_to_the_jar(tmp_path):
    target, vendor = _plugin_with_api(tmp_path)
    t = jira_target.load(target, vendor)
    dest = vendor / "api"
    assert jira_target.extract_public_api(t, dest, check=True) is False        # stale: nothing there yet
    assert jira_target.extract_public_api(t, dest) is True
    assert [p.name for p in dest.glob("*.jar")] == ["approvals-api-2.1.jar"]
    assert jira_target.extract_public_api(t, dest, check=True) is True
    (dest / "old-api-1.0.jar").write_bytes(b"x")                              # a leftover is stale
    assert jira_target.extract_public_api(t, dest, check=True) is False
    jira_target.extract_public_api(t, dest)
    assert [p.name for p in dest.glob("*.jar")] == ["approvals-api-2.1.jar"]


def test_priming_includes_the_public_api_dependencies():
    import prime_maven_repo as pm
    t = jira_target.Target(jar=Path("x"), jira_version="9.12.0", amps_version="9.2.3", java_release="11",
                           sources={}, original_deps=[jira_target.Dep("org.slf4j", "slf4j-api", "1.7.30")])
    extra = [jira_target.Dep("org.slf4j", "slf4j-api", "1.7.30", "provided"), jira_target.Dep("com.acme.ints", "ints", "1.1.3")]
    assert [d.coords for d in pm.to_prime(t, extra)] == ["org.slf4j:slf4j-api:1.7.30", "com.acme.ints:ints:1.1.3"]


# ---------------------------------------------------------------- the hidden tier end to end (Maven)

TOOLS = Path.home() / "lrae-tools" / "re"
SEED = REPO / "fixtures" / "seed_jira_re"


def _counts(res: subprocess.CompletedProcess) -> dict[str, int]:
    lines = res.stdout.splitlines()
    return {w: sum(ln.startswith(w + " ") for ln in lines) for w in ("PASSED", "FAILED", "SKIPPED", "ERROR")}


def _hidden_run(ws: Path, api_jar: Path, stage: int, *k: str) -> subprocess.CompletedProcess:
    env = {"LRAE_WORKSPACE": str(ws), "LRAE_API_JARS": str(api_jar), "LRAE_RE_TOOLS": str(TOOLS),
           "LRAE_STAGE": str(stage), "PATH": "/usr/bin:/bin", "HOME": str(ws.parent)}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rA", *k],
                          cwd=TASK / "hidden", env=env, capture_output=True, text=True, timeout=900)


@pytest.mark.local
def test_signature_tier_on_a_synthetic_api(tmp_path):
    """A seed workspace that re-implements a two-type API passes t05; one missing method fails exactly
    that type, naming the method. Built with the real toolchain and offline repository."""
    if not (TOOLS / "bin" / "mvn").exists():
        pytest.skip("no toolchain")
    want = _compile(tmp_path, "orig", {k: v for k, v in ORIGINAL.items() if k != "api/internal/Impl.java"})
    assert want
    jar = tmp_path / "api.jar"
    with zipfile.ZipFile(jar, "w") as z:
        for f in (tmp_path / "orig" / "classes").rglob("*.class"):
            z.write(f, f.relative_to(tmp_path / "orig" / "classes").as_posix())
    ws = tmp_path / "ws"
    shutil.copytree(SEED, ws, ignore=shutil.ignore_patterns(".git", "target", ".m2"))
    for rel, text in ORIGINAL.items():
        (ws / "src" / "main" / "java" / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / "src" / "main" / "java" / rel).write_text(text)
    res = _hidden_run(ws, jar, 1, "test_t05_api_signatures.py")
    assert res.returncode == 0 and _counts(res)["PASSED"] == 3, res.stdout[-3000:]
    kind = ws / "src" / "main" / "java" / "api" / "Kind.java"
    kind.write_text(kind.read_text().replace("public boolean big() { return this == B; }", ""))
    res = _hidden_run(ws, jar, 1, "test_t05_api_signatures.py")
    c = _counts(res)
    assert (c["FAILED"], c["PASSED"]) == (1, 2) and "missing method public big() -> boolean" in res.stdout, \
        res.stdout[-3000:]


@pytest.mark.local
def test_api_tiers_on_the_fresh_seed_fail_with_reasons(tmp_path):
    """At stage 4 the fresh seed (no API) fails every API test, each with a reason; the hidden Java tests
    that cannot compile are reported per file. Uses this machine's real API jar."""
    jars = sorted((TASK / "vendor" / "api").glob("*.jar"))
    if len(jars) != 1 or not (TOOLS / "bin" / "mvn").exists():
        pytest.skip("no extracted public API jar or no toolchain")
    ws = tmp_path / "ws"
    shutil.copytree(SEED, ws, ignore=shutil.ignore_patterns(".git", "target", ".m2"))
    res = _hidden_run(ws, jars[0], 4, "test_t05_api_signatures.py", "test_t06_api_behaviour.py",
                      "test_t07_api_visible.py")
    c = _counts(res)
    assert c["PASSED"] == 0 and c["FAILED"] > 400, (c, res.stdout[-2000:])
    assert "missing (interface" in res.stdout and "does not compile against the rewrite" in res.stdout, res.stdout[-3000:]


def test_the_self_check_record_is_current_and_green():
    """``analyst/selfcheck_api.py`` must be re-run whenever the API tests (or the API jar) change."""
    sys.path.insert(0, str(TASK / "analyst"))
    import json

    import selfcheck_api
    rec = json.loads((TASK / "hidden" / "api" / "selfcheck.json").read_text())
    assert rec["tests_sha256"] == selfcheck_api.tests_digest(), "API tests changed: re-run selfcheck_api.py"
    assert rec["ok"] and rec["passed"] == rec["tests"] > 0
    import _api
    assert sorted(rec["outcomes"]) == sorted(t.id for t in _api.java_tests(_api.HIDDEN_TESTS)
                                             + _api.java_tests(_api.VISIBLE_TESTS))
    jars = _api.api_jars()
    if jars:   # harness-side, on this machine
        assert rec["api_jars"] == selfcheck_api.jar_digests(jars), "API jar changed: re-run selfcheck_api.py"


def test_the_visible_api_tests_are_generated_and_shipped_unchanged():
    """The seed's spec/api-tests/ is a byte copy of hidden/api/visible/ (prepare_seed.py), and the
    signature sample is current (gen_visible_api_tests.py)."""
    import _api
    vis = {p.relative_to(_api.VISIBLE_TESTS).as_posix(): p.read_bytes() for p in _api.VISIBLE_TESTS.rglob("*") if p.is_file()}
    seed = SEED / "spec" / "api-tests"
    shipped = {p.relative_to(seed).as_posix(): p.read_bytes() for p in seed.rglob("*") if p.is_file()}
    assert vis and shipped == vis
    if _api.api_jars():
        sys.path.insert(0, str(TASK / "analyst"))
        import gen_visible_api_tests as g
        assert (_api.VISIBLE_TESTS / "cleanroom/apitests/ApiSignatureSampleTest.java").read_text() == g.render()


def test_hidden_java_tests_use_plain_test_methods_only():
    """One surefire entry per discovered method: no parameterised, repeated or dynamic tests, and every
    test class sits in its own package (hidden vs visible)."""
    import _api
    for root, pkg in ((_api.HIDDEN_TESTS, "cleanroom.apitests.hidden"), (_api.VISIBLE_TESTS, "cleanroom.apitests")):
        for p in root.rglob("*.java"):
            text = p.read_text()
            for bad in ("@ParameterizedTest", "@RepeatedTest", "@TestFactory", "@TestTemplate", "@Nested"):
                assert bad not in text, f"{p.name}: {bad}"
            assert f"package {pkg};" in text, p.name
        assert _api.java_tests(root)


def test_internal_libs_are_extracted_for_the_scorer(tmp_path):
    """JS1: the vendor's internal libraries (``internal_libs``) go to vendor/lib/, for the copy-similarity
    reference; a glob that matches nothing is an error, like ``public_api``."""
    import io
    target, vendor = _plugin_with_api(tmp_path)
    commons = io.BytesIO()
    with zipfile.ZipFile(commons, "w") as z:
        z.writestr("com/acme/commons/Sum.class", b"\xca\xfe\xba\xbe")
    with zipfile.ZipFile(vendor / "p.jar", "a") as z:
        z.writestr("META-INF/lib/acme-commons-3.1.jar", commons.getvalue())
    target.write_text(target.read_text() + 'internal_libs: ["META-INF/lib/acme-commons-*.jar"]\n')
    t = jira_target.load(target, vendor)
    assert t.internal_libs == ["META-INF/lib/acme-commons-3.1.jar"]
    dest = vendor / "lib"
    assert jira_target.extract_internal_libs(t, dest, check=True) is False
    jira_target.extract_internal_libs(t, dest)
    assert [p.name for p in dest.glob("*.jar")] == ["acme-commons-3.1.jar"]
    assert jira_target.extract_internal_libs(t, dest, check=True) is True
    target.write_text(target.read_text().replace("acme-commons-*", "nothing-*"))
    with pytest.raises(SystemExit, match="internal_libs"):
        jira_target.load(target, vendor)
