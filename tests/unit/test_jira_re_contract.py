"""jira-re external contract from class files (phase JS2, docs/jira-re-design.md §7.2): annotations, REST
endpoints, the Active Objects schema and JSON shapes, and the SPEC.md coverage rules of check_spec."""
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
import _contract as ct  # noqa: E402


def _ann(pkg: str, name: str, body: str = "String value() default \"\";", target: str = "") -> tuple[str, str]:
    return (f"{pkg.replace('.', '/')}/{name}.java",
            f"package {pkg}; import java.lang.annotation.*; @Retention(RetentionPolicy.RUNTIME) {target}"
            f"public @interface {name} {{ {body} }}")


STUBS = dict([
    _ann("javax.ws.rs", "Path"), _ann("javax.ws.rs", "GET", ""), _ann("javax.ws.rs", "POST", ""),
    _ann("javax.ws.rs", "DELETE", ""), _ann("javax.ws.rs", "QueryParam"), _ann("javax.ws.rs", "PathParam"),
    _ann("javax.ws.rs", "FormParam"), _ann("javax.ws.rs", "DefaultValue"),
    _ann("javax.ws.rs", "Produces", "String[] value() default {};"),
    _ann("javax.ws.rs", "Consumes", "String[] value() default {};"),
    _ann("javax.ws.rs.core", "Context", ""),
    _ann("com.atlassian.plugins.rest.common.security", "AnonymousAllowed", ""),
    _ann("net.java.ao.schema", "Table"), _ann("net.java.ao.schema", "NotNull", ""),
    _ann("net.java.ao.schema", "Indexed", ""), _ann("net.java.ao.schema", "Unique", ""),
    _ann("net.java.ao.schema", "Default"), _ann("net.java.ao.schema", "PrimaryKey"),
    _ann("net.java.ao.schema", "AutoIncrement", ""),
    _ann("net.java.ao.schema", "StringLength", "int UNLIMITED = -1; int value();"),
    _ann("net.java.ao", "Accessor"), _ann("net.java.ao", "Mutator"), _ann("net.java.ao", "OneToMany", ""),
    _ann("com.fasterxml.jackson.annotation", "JsonProperty"), _ann("com.fasterxml.jackson.annotation", "JsonIgnore", ""),
    ("javax/ws/rs/core/Response.java", "package javax.ws.rs.core; public class Response {}"),
    ("net/java/ao/RawEntity.java", "package net.java.ao; public interface RawEntity<T> {}"),
    ("net/java/ao/Entity.java", "package net.java.ao; public interface Entity extends RawEntity<Integer> { int getID(); }"),
])

PLUGIN = {
    "p/rest/v2/Base.java": """package p.rest.v2; import javax.ws.rs.*;
public abstract class Base { @GET @Path("/ping/") public String ping() { return ""; } }""",
    "p/rest/v2/ForestResource.java": """package p.rest.v2;
import javax.ws.rs.*; import javax.ws.rs.core.*; import p.rest.v2.data.Bean;
import com.atlassian.plugins.rest.common.security.AnonymousAllowed;
@Path("/forest") @Produces("application/json") @Consumes({"application/json", "text/plain"}) @AnonymousAllowed
public class ForestResource extends Base {
  @GET @Path("{id}") public Response get(@PathParam("id") long id, @QueryParam("depth") @DefaultValue("1") int depth,
                                         @Context Object request) { return null; }
  @POST @Produces("text/plain") public Bean update(Bean body) { return body; }
  @Path("sub") public Sub sub() { return new Sub(); }
  public void helper() {}
}""",
    "p/rest/v2/Sub.java": """package p.rest.v2; import javax.ws.rs.*;
public class Sub { @DELETE @Path("{k}") public void del(@PathParam("k") String k, @FormParam("why") String why) {} }""",
    "p/rest/other/NotScanned.java": """package p.rest.other; import javax.ws.rs.*;
@Path("/x") public class NotScanned { @GET public String get() { return ""; } }""",
    "p/rest/v2/data/Bean.java": """package p.rest.v2.data;
import java.util.*; import com.fasterxml.jackson.annotation.*;
public class Bean {
  public static int COUNT;
  public long id;
  public List<Item> items;
  public Map<String, Object> extra;
  @JsonProperty("display") public String name;
  @JsonIgnore public String secret;
  private int hidden;
  public boolean isOpen() { return true; }
  public String getLabel() { return ""; }
}""",
    "p/rest/v2/data/Persp.java": """package p.rest.v2.data; import com.fasterxml.jackson.annotation.*;
public class Persp {
  public long id;
  @JsonIgnore public String spec;
  @JsonProperty("spec") public Object getSpecJson() { return null; }
  @JsonProperty("written") public void setWritten(String w) {}
}""",
    "p/rest/v2/data/Item.java": "package p.rest.v2.data; public class Item { public String key; public Double ratio; "
                                "public int[] counts; }",
    "p/db/RowAO.java": """package p.db; import net.java.ao.*; import net.java.ao.schema.*; import java.util.Date;
@Table("ROW") public interface RowAO extends Entity {
  @Accessor("C_ITEM_TYPE") @NotNull @Indexed int getItemType();
  @Mutator("C_ITEM_TYPE") void setItemType(int t);
  @StringLength(190) String getItemStringId();
  @StringLength(StringLength.UNLIMITED) String getBody();
  Date getCreated();
  OtherAO getParent();
  @OneToMany OtherAO[] getChildren();
}""",
    "p/db/OtherAO.java": """package p.db; import net.java.ao.*; import net.java.ao.schema.*;
@Table("OTHER") public interface OtherAO extends RawEntity<String> {
  @PrimaryKey("KEY") @StringLength(64) String getKey();
  boolean isFlag();
  @Default("7") @Unique Integer getLevel();
}""",
    "p/db/NoTableAO.java": "package p.db; public interface NoTableAO extends net.java.ao.Entity { long getCount(); }",
}


def _javac():
    javac = shutil.which("javac")
    if not javac or subprocess.run([javac, "-version"], capture_output=True).returncode != 0:
        pytest.skip("no JDK")
    return javac


@pytest.fixture(scope="module")
def classes(tmp_path_factory) -> dict[str, bytes]:
    tmp = tmp_path_factory.mktemp("contract")
    src, out = tmp / "src", tmp / "classes"
    for rel, text in {**STUBS, **PLUGIN}.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text)
    out.mkdir()
    subprocess.run([_javac(), "--release", "11", "-parameters", "-d", str(out), *map(str, src.rglob("*.java"))],
                   check=True)
    return cf.classes_in_dir(out)


# ---------------------------------------------------------------- annotations

def test_annotations_are_decoded_on_classes_methods_and_parameters(classes):
    raw = cf.parse_class(classes["p.rest.v2.ForestResource"])
    anns = {a.type: a.values for a in cf.annotations(raw, raw.attrs)}
    assert anns["javax.ws.rs.Path"] == {"value": "/forest"}
    assert anns["javax.ws.rs.Consumes"] == {"value": ["application/json", "text/plain"]}
    assert "com.atlassian.plugins.rest.common.security.AnonymousAllowed" in anns
    get = next(m for m in raw.methods if m.name == "get")
    params = cf.parameter_annotations(raw, get.attrs)
    assert [[a.type.rsplit(".", 1)[-1] for a in p] for p in params] == [["PathParam"], ["QueryParam", "DefaultValue"],
                                                                        ["Context"]]
    assert params[1][1].values == {"value": "1"}
    ao = cf.parse_class(classes["p.db.RowAO"])
    body = next(m for m in ao.methods if m.name == "getBody")
    assert cf.annotations(ao, body.attrs)[0].values == {"value": -1}


# ---------------------------------------------------------------- REST

def test_rest_endpoints_cover_inheritance_and_sub_resources_in_scanned_packages_only(classes):
    eps = ct.rest_endpoints(classes, ["p.rest.v2"], "/rest/structure/2.0")
    by = {(e.method, e.path): e for e in eps}
    assert set(by) == {("GET", "/rest/structure/2.0/forest/{id}"), ("POST", "/rest/structure/2.0/forest"),
                       ("DELETE", "/rest/structure/2.0/forest/sub/{k}"), ("GET", "/rest/structure/2.0/forest/ping")}
    get = by["GET", "/rest/structure/2.0/forest/{id}"]
    assert [(p.kind, p.name, p.java, p.default) for p in get.params] == [
        ("path", "id", "long", None), ("query", "depth", "int", "1")]     # @Context is not part of the contract
    assert get.produces == ("application/json",) and get.consumes == ("application/json", "text/plain")
    assert get.anonymous and get.source == "p.rest.v2.ForestResource#get"
    post = by["POST", "/rest/structure/2.0/forest"]
    assert post.produces == ("text/plain",)                             # the method overrides the class
    assert [(p.kind, p.java) for p in post.params] == [("body", "p.rest.v2.data.Bean")]
    assert post.returns == "p.rest.v2.data.Bean"
    sub = by["DELETE", "/rest/structure/2.0/forest/sub/{k}"]
    assert [(p.kind, p.name) for p in sub.params] == [("path", "k"), ("form", "why")]
    assert not sub.anonymous                                            # a sub-resource class of its own
    assert ct.endpoint_id(get) == "GET /rest/structure/2.0/forest/{id}"


def test_rest_modules_follow_the_restrict_ranges():
    import xml.etree.ElementTree as ET
    root = ET.fromstring(
        '<atlassian-plugin key="k">'
        '<rest key="r" path="/structure" version="1.0"><restrict application="jira" version="[9.0.0,10.0.0)"/>'
        '<package>a.javax</package><package>a.provider</package></rest>'
        '<rest key="r" path="/structure" version="1.0"><restrict application="jira" version="[11.0.0,)"/>'
        '<package>a.jakarta</package></rest>'
        '<rest key="c" path="/cfd" version="1.0"><package>c</package></rest></atlassian-plugin>')
    assert ct.rest_modules(root, "9.12.2") == [("r", "/rest/structure/1.0", ["a.javax", "a.provider"]),
                                               ("c", "/rest/cfd/1.0", ["c"])]
    assert ct.rest_modules(root, "11.1.0")[0] == ("r", "/rest/structure/1.0", ["a.jakarta"])


# ---------------------------------------------------------------- Active Objects

def test_ao_prefix_is_the_md5_rule():
    assert ct.ao_prefix("com.almworks.jira.structure") == "AO_8BAD1B"


def test_ao_schema_from_entities(classes):
    tables = {t.name: t for t in ct.ao_tables(classes, ["p.db.RowAO", "p.db.OtherAO", "p.db.NoTableAO"], "ns")}
    pre = ct.ao_prefix("ns")
    assert set(tables) == {f"{pre}_ROW", f"{pre}_OTHER", f"{pre}_NO_TABLE_AO"}
    row = {c.name: c for c in tables[f"{pre}_ROW"].columns}
    assert list(row) == ["ID", "C_ITEM_TYPE", "ITEM_STRING_ID", "BODY", "CREATED", "PARENT_ID"]
    assert (row["ID"].java, row["ID"].primary_key, row["ID"].auto_increment) == ("int", True, True)
    assert (row["C_ITEM_TYPE"].not_null, row["C_ITEM_TYPE"].indexed) == (True, True)
    assert row["ITEM_STRING_ID"].length == 190 and row["BODY"].length == -1
    assert row["CREATED"].java == "java.util.Date"
    assert row["PARENT_ID"].references == f"{pre}_OTHER"
    other = {c.name: c for c in tables[f"{pre}_OTHER"].columns}
    assert list(other) == ["KEY", "FLAG", "LEVEL"]
    assert other["KEY"].primary_key and other["KEY"].length == 64
    assert (other["LEVEL"].default, other["LEVEL"].unique, other["LEVEL"].java) == ("7", True, "java.lang.Integer")
    assert [c.name for c in tables[f"{pre}_NO_TABLE_AO"].columns] == ["ID", "COUNT"]


# ---------------------------------------------------------------- JSON shapes

def test_json_fields_follow_jackson_visibility(classes):
    fields = {f.name: f.json for f in ct.json_fields(classes, "p.rest.v2.data.Bean")}
    assert fields == {"id": "integer", "items": "array<p.rest.v2.data.Item>", "extra": "map<string, any>",
                      "display": "string", "open": "boolean", "label": "string"}
    assert {f.name: f.json for f in ct.json_fields(classes, "p.rest.v2.data.Item")} == {
        "key": "string", "ratio": "number", "counts": "array<integer>"}


def test_an_explicit_property_beats_an_ignored_field_and_annotated_setters_count(classes):
    assert {f.name: f.json for f in ct.json_fields(classes, "p.rest.v2.data.Persp")} == {
        "id": "integer", "spec": "any", "written": "string"}


def test_shapes_reachable_from_a_class_are_closed_over(classes):
    assert ct.reachable_shapes(classes, ["p.rest.v2.data.Bean"]) == ["p.rest.v2.data.Bean", "p.rest.v2.data.Item"]


# ---------------------------------------------------------------- check_spec coverage rules

SPEC_OK = """# Contract
| key | type |
|---|---|
| `res` | `rest` |
| `ao` | `ao` |

#### `GET /rest/s/2.0/forest/{id}`
Returns the forest.

#### `GET /rest/s/2.0/forest/ping`
Liveness.

#### `POST /rest/s/2.0/forest`
Updates it.

#### `DELETE /rest/s/2.0/forest/sub/{k}`
Deletes a key.

#### Table `AO_%(pre)s_ROW`
| `ID` | `C_ITEM_TYPE` | `ITEM_STRING_ID` | `BODY` | `CREATED` | `PARENT_ID` |

#### Table `AO_%(pre)s_OTHER`
| `KEY` | `FLAG` | `LEVEL` |

#### Table `AO_%(pre)s_NO_TABLE_AO`
`ID`, `COUNT`.
"""


@pytest.fixture
def plugin(classes, tmp_path):
    jar = tmp_path / "p.jar"
    with zipfile.ZipFile(jar, "w") as z:
        for name, data in classes.items():
            z.writestr(name.replace(".", "/") + ".class", data)
        z.writestr("atlassian-plugin.xml",
                   '<atlassian-plugin key="p"><rest key="res" path="/s" version="2.0"><package>p.rest.v2</package>'
                   '</rest><ao key="ao" namespace="ns"><entity>p.db.RowAO</entity><entity>p.db.OtherAO</entity>'
                   '<entity>p.db.NoTableAO</entity></ao></atlassian-plugin>')
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "SPEC.md").write_text(SPEC_OK % {"pre": ct.ao_prefix("ns")[3:]})
    return jar, spec


def _contract_problems(jar, spec):
    import check_spec
    return [p for p in check_spec.check(jar=jar, spec_dir=spec, analyst_dir=spec, jira="9.12.2").problems
            if p.startswith("SPEC.md")]


def test_a_complete_contract_section_passes(plugin):
    assert _contract_problems(*plugin) == []


def test_missing_modules_endpoints_descriptions_tables_and_columns_are_named(plugin):
    jar, spec = plugin
    pre = ct.ao_prefix("ns")
    text = (SPEC_OK % {"pre": pre[3:]}).replace("| `ao` | `ao` |\n", "| `ao` | `rest` |\n") \
        .replace("#### `GET /rest/s/2.0/forest/ping`\nLiveness.\n", "") \
        .replace("Updates it.", ct.PENDING) \
        .replace("#### Table `AO_%s_OTHER`\n| `KEY` | `FLAG` | `LEVEL` |\n" % pre[3:], "") \
        .replace("`CREATED` | ", "")
    (spec / "SPEC.md").write_text(text)
    assert sorted(_contract_problems(jar, spec)) == sorted([
        "SPEC.md: module 'ao' (ao) is not in the module table",
        "SPEC.md: REST endpoint GET /rest/s/2.0/forest/ping is not specified",
        "SPEC.md: REST endpoint POST /rest/s/2.0/forest is not described yet",
        f"SPEC.md: AO table {pre}_OTHER is not specified",
        f"SPEC.md: AO column {pre}_ROW.CREATED is not specified",
    ])


def test_the_body_parameter_has_its_generic_json_type(classes):
    post = next(e for e in ct.rest_endpoints(classes, ["p.rest.v2"], "/r") if e.method == "POST")
    assert post.params[0].json == "p.rest.v2.data.Bean"


# ---------------------------------------------------------------- build_contract

NOTES = {
    "endpoints": {
        "GET /rest/s/2.0/forest/{id}": {"summary": "Returns the forest.", "params": {"depth": "levels to return"},
                                        "response": "A {{p.rest.v2.data.Bean}}.", "errors": "404 when absent."},
        "POST /rest/s/2.0/forest": {"summary": "Updates it."},
    },
    "shapes": {
        "p.rest.v2.data.Bean": {"name": "forest-thing", "summary": "A forest.",
                                "fields": {"id": "its id", "items": "rows", "extra": "x", "display": "shown",
                                           "open": "o", "label": "l"}},
        "p.rest.v2.data.Item": {"name": "row-thing", "summary": "A row.",
                                "fields": {"key": "k", "ratio": "r", "counts": "c"}},
    },
    "tables": {"AO_%s_ROW": {"summary": "Rows.", "columns": {"C_ITEM_TYPE": "the item type"}}},
}


def _build(plugin, notes):
    import build_contract
    jar, spec = plugin
    md = "# Spec\n" + "".join(f"<!-- BEGIN generated: {b} -->\n<!-- END generated: {b} -->\n"
                               for b in build_contract.BLOCKS)
    inv = {"modules": [{"key": "res", "type": "rest", "class": None, "group": "g"},
                       {"key": "ao", "type": "ao", "class": None, "group": "g"}]}
    return build_contract.build(md, jar=jar, libs=[], jira="9.12.0", notes=notes, inventory=inv)


def test_build_contract_renders_endpoints_shapes_and_tables_without_class_names(plugin):
    import json
    notes = json.loads(json.dumps(NOTES).replace("AO_%s", ct.ao_prefix("ns")))
    md, report = _build(plugin, notes)
    assert "#### `GET /rest/s/2.0/forest/{id}`" in md and "Returns the forest." in md
    assert "levels to return" in md and "`depth`" in md and "`1`" in md
    assert "[`forest-thing`](#shape-forest-thing)" in md and "array<[`row-thing`](#shape-row-thing)>" in md
    assert "| `res` | `rest` |" in md and "| `ao` | `ao` |" in md
    assert f"`{ct.ao_prefix('ns')}_ROW`" in md and "the item type" in md
    assert "p.rest" not in md and "p.db" not in md and "{{" not in md
    assert ct.PENDING in md                     # two endpoints and some tables have no notes yet
    assert report["endpoints"] == (2, 4) and report["shapes"] == (2, 2)
    md2, _ = _build(plugin, notes)
    assert md2 == md                            # deterministic


def test_build_contract_rejects_stale_notes(plugin):
    bad = {**NOTES, "endpoints": {**NOTES["endpoints"], "GET /rest/s/2.0/gone": {"summary": "x"}}}
    with pytest.raises(ValueError, match="gone"):
        _build(plugin, bad)
    bad = {**NOTES, "shapes": {**NOTES["shapes"], "p.rest.v2.data.Item": {"name": "row-thing", "summary": "r",
                                                                         "fields": {"nope": "x"}}}}
    with pytest.raises(ValueError, match="nope"):
        _build(plugin, bad)
    bad = {**NOTES, "endpoints": {"POST /rest/s/2.0/forest": {"summary": "Takes {{p.rest.v2.data.Missing}}."}}}
    with pytest.raises(ValueError, match="Missing"):
        _build(plugin, bad)


def test_notes_files_merge_and_refuse_duplicates(tmp_path):
    import build_contract
    (tmp_path / "a.json").write_text('{"endpoints": {"GET /x": {"summary": "a"}}}')
    (tmp_path / "b.json").write_text('{"shapes": {"p.X": {"name": "x", "summary": "x"}}}')
    assert build_contract.load_notes(tmp_path) == {"endpoints": {"GET /x": {"summary": "a"}},
                                                   "shapes": {"p.X": {"name": "x", "summary": "x"}}, "tables": {}}
    (tmp_path / "c.json").write_text('{"endpoints": {"GET /x": {"summary": "c"}}}')
    with pytest.raises(ValueError, match="GET /x"):
        build_contract.load_notes(tmp_path)


def test_any_other_pending_description_is_reported(plugin):
    jar, spec = plugin
    text = (spec / "SPEC.md").read_text() + f"\n#### Shape `forest-thing`\n\n{ct.PENDING}\n"
    (spec / "SPEC.md").write_text(text)
    assert _contract_problems(jar, spec) == ["SPEC.md: a description is pending under '#### Shape `forest-thing`'"]
