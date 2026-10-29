"""jira-re Part 2 of the spec, the public Java API (phase JS3, docs/jira-re-design.md §7.4): Java declarations
from class files, ``build_api.py``'s rendering of ``spec/API.md`` from the analyst's notes, and check_spec's
API.md rules."""
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TASK = REPO / "fixtures" / "tasks" / "jira_re"
sys.path.insert(0, str(TASK / "hidden"))
sys.path.insert(0, str(TASK / "analyst"))

import _classfile as cf  # noqa: E402
import build_api as ba  # noqa: E402
from _contract import PENDING  # noqa: E402

API = {
    "a/api/Shape.java": """package a.api;
public interface Shape<T extends Comparable<? super T>> extends Iterable<T> {
  int SIDES = 4;
  String NAME = "shape";
  <R> java.util.List<R> map(java.util.function.Function<? super T, ? extends R> f) throws java.io.IOException;
  default boolean empty() { return true; }
  @SafeVarargs static <T extends Comparable<? super T>> Shape<T> of(T... items) { return null; }
  long[] ids();
}""",
    "a/api/Base.java": """package a.api;
public abstract class Base<K, V> implements Shape<String> {
  protected Base(int x) { table = null; }
  public final java.util.Map<K, java.util.List<V>> table;
  public static final long BIG = 5L;
  protected abstract void hook(String... names);
  public static class Entry<E> { public Entry() {} public E get() { return null; } }
  public class Inner { public Inner(String s) {} }
  public interface Visitor { void visit(Base<?, ?>.Inner node, Entry<String>[] entries); }
  private static class Hidden {}
}""",
    "a/api/Color.java": """package a.api;
public enum Color { RED, GREEN; public int code() { return 0; } }""",
    "a/api/Marker.java": """package a.api; import java.lang.annotation.*;
@Retention(RetentionPolicy.RUNTIME) public @interface Marker {
  String value() default "x"; int[] n() default {1, 2}; Color c() default Color.RED; boolean on() default true;
  Class<?> type();
}""",
    "a/api/Hidden.java": "package a.api; class Hidden { public void x() {} }",
    "a/api/sub/Util.java": """package a.api.sub;
public final class Util { private Util() {} public static int twice(int x) { return 2 * x; } }""",
}


def _javac():
    javac = shutil.which("javac")
    if not javac or subprocess.run([javac, "-version"], capture_output=True).returncode != 0:
        pytest.skip("no JDK")
    return javac


@pytest.fixture(scope="module")
def classes(tmp_path_factory) -> dict[str, bytes]:
    tmp = tmp_path_factory.mktemp("apidoc")
    src, out = tmp / "src", tmp / "classes"
    for rel, text in API.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text)
    out.mkdir()
    subprocess.run([_javac(), "--release", "11", "-d", str(out), *map(str, src.rglob("*.java"))], check=True)
    return cf.classes_in_dir(out)


@pytest.fixture(scope="module")
def docs(classes):
    return {d.name: d for d in ba.document(classes)}


# ---------------------------------------------------------------- declarations

def test_signatures_render_as_java_with_their_type_variable_names():
    assert ba.method_parts("<R:Ljava/lang/Object;>(Ljava/util/function/Function<-TT;+TR;>;)Ljava/util/List<TR;>;"
                           "^Ljava/io/IOException;") == \
        ("<R>", ["java.util.function.Function<? super T, ? extends R>"], "java.util.List<R>", ["java.io.IOException"])
    assert ba.class_parts("<T::Ljava/lang/Comparable<-TT;>;>Ljava/lang/Object;Ljava/lang/Iterable<TT;>;") == \
        ("<T extends Comparable<? super T>>", ["Object", "Iterable<T>"])
    assert ba.descriptor_type("[[La/api/Base$Entry;") == "a.api.Base.Entry[][]"
    assert ba.descriptor_type("La/api/Base<**>.Inner;") == "a.api.Base<?, ?>.Inner"
    assert ba.class_parts("<T:Ljava/lang/Number;:Ljava/lang/Runnable;>Ljava/lang/Object;")[0] == \
        "<T extends Number & Runnable>"


def test_types_and_members_are_declared_like_java(docs):
    shape = docs["a.api.Shape"]
    assert shape.declaration == "public interface Shape<T extends Comparable<? super T>> extends Iterable<T>"
    assert dict(shape.members) == {
        "SIDES": "public static final int SIDES = 4",
        "NAME": 'public static final String NAME = "shape"',
        "map(java.util.function.Function)":
            "public abstract <R> java.util.List<R> map(java.util.function.Function<? super T, ? extends R>) "
            "throws java.io.IOException",
        "empty()": "public default boolean empty()",
        "of(Comparable[])": "public static <T extends Comparable<? super T>> a.api.Shape<T> of(T...)",
        "ids()": "public abstract long[] ids()",
    }
    assert [k for k, _ in shape.members] == ["SIDES", "NAME", "map(java.util.function.Function)", "empty()",
                                             "of(Comparable[])", "ids()"]       # source order
    base = docs["a.api.Base"]
    assert base.declaration == "public abstract class Base<K, V> implements a.api.Shape<String>"
    assert dict(base.members) == {
        "<init>(int)": "protected Base(int)",
        "table": "public final java.util.Map<K, java.util.List<V>> table",
        "BIG": "public static final long BIG = 5",
        "hook(String[])": "protected abstract void hook(String...)",
    }


def test_member_types_follow_their_enclosing_type_and_hidden_types_are_left_out(docs, classes):
    names = [d.name for d in ba.document(classes)]
    assert names == ["a.api.Base", "a.api.Base.Entry", "a.api.Base.Inner", "a.api.Base.Visitor", "a.api.Color",
                     "a.api.Marker", "a.api.Shape", "a.api.sub.Util"]
    assert docs["a.api.Base.Entry"].declaration == "public static class Base.Entry<E>"
    assert docs["a.api.Base.Inner"].declaration == "public class Base.Inner"
    assert dict(docs["a.api.Base.Inner"].members) == {"<init>(a.api.Base, String)": "public Inner(String)"}
    assert dict(docs["a.api.Base.Visitor"].members) == {
        "visit(a.api.Base.Inner, a.api.Base.Entry[])":
            "public abstract void visit(a.api.Base<?, ?>.Inner, a.api.Base.Entry<String>[])"}
    assert docs["a.api.sub.Util"].declaration == "public final class Util"
    assert [k for k, _ in docs["a.api.sub.Util"].members] == ["twice(int)"]


def test_enums_list_their_constants_and_annotations_their_defaults(docs):
    color = docs["a.api.Color"]
    assert color.declaration == "public enum Color"
    assert [d for _, d in color.members][:2] == ["RED (enum constant)", "GREEN (enum constant)"]
    assert {"values()", "valueOf(String)", "code()"} <= {k for k, _ in color.members}
    marker = docs["a.api.Marker"]
    assert marker.declaration == "public @interface Marker"
    assert dict(marker.members) == {
        "value()": 'public abstract String value() default "x"',
        "n()": "public abstract int[] n() default {1, 2}",
        "c()": "public abstract a.api.Color c() default a.api.Color.RED",
        "on()": "public abstract boolean on() default true",
        "type()": "public abstract Class<?> type()",
    }


def test_only_named_types_and_their_member_types_when_asked(classes):
    assert [d.name for d in ba.document(classes, ["a.api.Base"])] == \
        ["a.api.Base", "a.api.Base.Entry", "a.api.Base.Inner", "a.api.Base.Visitor"]


# ---------------------------------------------------------------- API.md

NOTES = {
    "intro": "How to read this file.",
    "packages": {"a.api": "Shapes.", "a.api.sub": "Helpers."},
    "types": {
        "a.api.Shape": {"summary": "A shape of comparable parts.", "members": {"SIDES": "Corner count.",
                                                                              "map(java.util.function.Function)": "Maps every part."}},
        "a.api.Color": {"summary": "A colour.", "members": {"RED": "Red.", "values()": "Override."}},
    },
}


def test_api_md_renders_declarations_notes_and_pending_placeholders(docs, classes):
    md, report = ba.build(ba.document(classes), NOTES)
    assert md.startswith("# API: the public Java API\n")
    assert "## Package `a.api`\n\nShapes.\n" in md and "## Package `a.api.sub`\n\nHelpers.\n" in md
    assert ("### `a.api.Shape`\n\n```java\npublic interface Shape<T extends Comparable<? super T>> extends Iterable<T>"
            "\n```\n\nA shape of comparable parts.\n") in md
    assert "| `public static final int SIDES = 4` | Corner count. |" in md
    assert f"| `public default boolean empty()` | {PENDING} |" in md
    assert "### `a.api.Base.Entry`" in md and "### `a.api.sub.Util`" in md and "Hidden" not in md
    assert "| `RED (enum constant)` | Red. |" in md and "| `public static a.api.Color[] values()` | Override. |" in md
    assert "valueOf(String) | All constants" not in md and "`IllegalArgumentException` when" in md   # Java's meaning
    assert report["types"] == (2, 8)
    assert md.index("### `a.api.Base`") < md.index("### `a.api.Base.Entry`") < md.index("### `a.api.Color`")
    assert ba.build(ba.document(classes), NOTES)[0] == md                                     # deterministic


@pytest.mark.parametrize("notes, name", [
    ({"packages": {"a.gone": "x"}}, "a.gone"),
    ({"types": {"a.api.Gone": {"summary": "x"}}}, "a.api.Gone"),
    ({"types": {"a.api.Shape": {"summary": "x", "members": {"map(Function)": "x"}}}}, "a.api.Shape#map(Function)"),
])
def test_stale_notes_fail_the_build(classes, notes, name):
    with pytest.raises(ValueError, match=name.replace("(", r"\(").replace(")", r"\)")):
        ba.build(ba.document(classes), notes)


def test_internal_class_names_fail_the_build_unless_allowed(classes):
    notes = {"types": {"a.api.Shape": {"summary": "Stored by p.internal.RuleStore."}}}
    with pytest.raises(ValueError, match="p.internal.RuleStore"):
        ba.build(ba.document(classes), notes, internal={"p.internal.RuleStore"})
    ba.build(ba.document(classes), notes, internal={"p.internal.RuleStore"}, allowed={"p.internal.RuleStore"})


def test_notes_files_merge_and_refuse_duplicates(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"intro": "i", "packages": {"a.api": "x"}}))
    (tmp_path / "b.json").write_text(json.dumps({"types": {"a.api.Shape": {"summary": "s"}}}))
    assert ba.load_notes(tmp_path) == {"intro": "i", "packages": {"a.api": "x"}, "types": {"a.api.Shape": {"summary": "s"}}}
    (tmp_path / "c.json").write_text(json.dumps({"packages": {"a.api": "y"}}))
    with pytest.raises(ValueError, match="a.api"):
        ba.load_notes(tmp_path)


def test_skeleton_lists_every_type_and_member_key_of_a_package(classes):
    sk = ba.skeleton(ba.document(classes), ["a.api.sub"])
    assert sk == {"packages": {"a.api.sub": ""}, "types": {"a.api.sub.Util": {"summary": "", "members": {"twice(int)": ""}}}}


# ---------------------------------------------------------------- check_spec on API.md

@pytest.fixture
def analyst(classes, tmp_path):
    """A plugin jar with one module, its spec (inventory, claims, an empty contract) and the API jar."""
    jar, api = tmp_path / "p.jar", tmp_path / "api.jar"
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr("atlassian-plugin.xml", '<atlassian-plugin key="p"><servlet key="s"/></atlassian-plugin>')
    with zipfile.ZipFile(api, "w") as z:
        for name, data in classes.items():
            z.writestr(name.replace(".", "/") + ".class", data)
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "inventory.json").write_text('{"modules": [{"key": "s", "type": "servlet", "purpose": "x"}]}')
    (spec / "claims.jsonl").write_text('{"id": "C-0001", "module": "s", "behaviour": "b", "confidence": "high"}\n')
    (spec / "SPEC.md").write_text("| `s` | `servlet` |\n")
    (tmp_path / "claims-evidence.jsonl").write_text('{"id": "C-0001", "evidence": ["atlassian-plugin.xml"]}\n')
    (tmp_path / "spec-changes-1.md").write_text("changes\n")
    return jar, api, spec, tmp_path


def _full_notes(classes) -> dict:
    docs = ba.document(classes)
    sk = ba.skeleton(docs, sorted({ba._package(d) for d in docs}))
    sk["intro"] = "Intro."
    sk["packages"] = {p: "P." for p in sk["packages"]}
    for t in sk["types"].values():
        t["summary"] = "S."
        t["members"] = {k: "M." for k in t["members"]}
    return sk


def _api_problems(analyst):
    import check_spec
    jar, api, spec, folder = analyst
    rep = check_spec.check(jar=jar, spec_dir=spec, analyst_dir=folder, api_jars=[api], jira="9.12.2")
    return rep, [p for p in rep.problems if ("API" in p or "package" in p) and not p.startswith("claims")]


def test_a_fully_described_api_md_passes(analyst, classes):
    (analyst[2] / "API.md").write_text(ba.build(ba.document(classes), _full_notes(classes))[0])
    rep, problems = _api_problems(analyst)
    assert problems == [] and (rep.api_types, rep.api_specified) == (5, 5)
    assert rep.api_members_described == rep.api_members > 20


def test_missing_types_and_pending_descriptions_are_reported_per_top_level_type(analyst, classes):
    notes = _full_notes(classes)
    notes["types"]["a.api.Base.Entry"]["members"]["get()"] = ""
    notes["types"]["a.api.Color"]["summary"] = ""
    notes["packages"]["a.api.sub"] = ""
    md = ba.build(ba.document(classes), notes)[0]
    md = md.replace("### `a.api.Marker`", "### Marker")
    (analyst[2] / "API.md").write_text(md)
    rep, problems = _api_problems(analyst)
    assert sorted(problems) == sorted([
        "API.md: public API type a.api.Base: 1 description pending",
        "API.md: public API type a.api.Color: 1 description pending",
        "API.md: public API type a.api.Marker is not specified",
        "API.md: package a.api.sub: summary pending",
    ])
    assert rep.api_specified == 2


def test_without_api_md_every_type_is_unspecified(analyst):
    rep, problems = _api_problems(analyst)
    assert len([p for p in problems if p.endswith("is not specified")]) == 2 + 8 and rep.api_specified == 0
