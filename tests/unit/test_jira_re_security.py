"""jira-re hidden t10, the security contract (``hidden/_security.py``, owner 2026-11-02): REST security markers,
webwork XSRF and websudo checks and servlet filter coverage of the original, judged on the rewrite."""
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TASK = REPO / "fixtures" / "tasks" / "jira_re"
sys.path.insert(0, str(TASK / "hidden"))

import _classfile as cf  # noqa: E402
import _contract as ct  # noqa: E402
import _security as sec  # noqa: E402


def _ann(pkg: str, name: str, body: str = "") -> tuple[str, str]:
    return (f"{pkg.replace('.', '/')}/{name}.java",
            f"package {pkg}; import java.lang.annotation.*; @Retention(RetentionPolicy.RUNTIME) "
            f"public @interface {name} {{ {body} }}")


STUBS = dict([
    _ann("javax.ws.rs", "Path", 'String value() default "";'), _ann("javax.ws.rs", "GET"), _ann("javax.ws.rs", "POST"),
    _ann("javax.ws.rs", "PathParam", 'String value() default "";'),
    _ann("com.atlassian.plugins.rest.common.security", "AnonymousAllowed"),
    _ann("com.atlassian.plugins.rest.common.security", "XsrfProtectionExcluded"),
    _ann("com.atlassian.annotations.security", "UnrestrictedAccess"),
    _ann("com.atlassian.sal.api.websudo", "WebSudoRequired"),
    _ann("com.atlassian.jira.security.xsrf", "RequiresXsrfCheck"),
    ("com/atlassian/jira/security/xsrf/XsrfTokenGenerator.java", "package com.atlassian.jira.security.xsrf; "
     "public interface XsrfTokenGenerator { boolean validateToken(Object request, String token); }"),
])

# The "original": a resource, a websudo resource, an anonymous one, and two pages whose base class's !apply
# command needs an XSRF check (the base class sits in a bundled library in the real plugin).
ORIGINAL = {
    "o/rest/Items.java": """package o.rest; import javax.ws.rs.*;
@Path("/items") public class Items {
  @GET @Path("{id}") public String get(@PathParam("id") long id) { return ""; }
  @POST public String add() { return ""; } }""",
    "o/rest/Admin.java": """package o.rest; import javax.ws.rs.*; import com.atlassian.sal.api.websudo.WebSudoRequired;
@Path("/admin") @WebSudoRequired public class Admin { @POST public String set() { return ""; } }""",
    "o/rest/Pub.java": """package o.rest; import javax.ws.rs.*;
import com.atlassian.plugins.rest.common.security.AnonymousAllowed;
@Path("/pub") @AnonymousAllowed public class Pub { @GET public String get() { return ""; } }""",
    "o/ww/Base.java": """package o.ww; import com.atlassian.jira.security.xsrf.RequiresXsrfCheck;
public abstract class Base { public String doDefault() { return "input"; }
  @RequiresXsrfCheck public String doApply() { return "success"; } }""",
    "o/ww/Edit.java": """package o.ww; import com.atlassian.jira.security.xsrf.RequiresXsrfCheck;
public class Edit extends Base { @RequiresXsrfCheck public String doSave() { return "success"; } }""",
    "o/ww/Sudo.java": """package o.ww; import com.atlassian.sal.api.websudo.WebSudoRequired;
@WebSudoRequired public class Sudo extends Base {}""",
}
ORIGINAL_XML = """<atlassian-plugin key="p">
  <rest key="rest" path="/p" version="1.0"><package>o.rest</package></rest>
  <webwork1 key="ww"><actions>
    <action name="o.ww.Edit" alias="EditThing"/><action name="o.ww.Sudo" alias="SudoThing"/>
  </actions></webwork1>
  <servlet-filter key="guard" location="before-login" weight="200" class="o.F">
    <url-pattern>/secure/A.jspa</url-pattern><url-pattern>/rest/x/*</url-pattern>
    <dispatcher>REQUEST</dispatcher><dispatcher>FORWARD</dispatcher>
  </servlet-filter>
</atlassian-plugin>"""

# The rewrite: its own class names and packages. Each class drops or keeps one check (see the tests).
REWRITE = {
    "r/api/ItemsResource.java": """package r.api; import javax.ws.rs.*;
import com.atlassian.plugins.rest.common.security.*;
@Path("/items") public class ItemsResource {
  @GET @Path("{itemId}") @AnonymousAllowed public String get(@PathParam("itemId") long id) { return ""; }
  @POST @XsrfProtectionExcluded public String add() { return ""; } }""",
    "r/api/AdminResource.java": """package r.api; import javax.ws.rs.*;
@Path("/admin") public class AdminResource { @POST public String set() { return ""; } }""",
    "r/api/Extra.java": """package r.api; import javax.ws.rs.*;
import com.atlassian.plugins.rest.common.security.AnonymousAllowed;
@Path("/debug") @AnonymousAllowed public class Extra { @GET public String dump() { return ""; } }""",
    "r/web/Page.java": """package r.web; import com.atlassian.jira.security.xsrf.*;
public class Page { protected XsrfTokenGenerator xsrf;
  public String doApply() { return xsrf.validateToken(null, "t") ? "success" : "error"; } }""",
    "r/web/EditPage.java": """package r.web;
public class EditPage extends Page { public String doSave() { return "success"; } }""",
    "r/web/SudoPage.java": """package r.web; import com.atlassian.annotations.security.UnrestrictedAccess;
@UnrestrictedAccess public class SudoPage { public String doApply() { return "success"; } }""",
}
REWRITE_XML = """<atlassian-plugin key="p">
  <rest key="rest" path="/p" version="1.0"><package>r.api</package></rest>
  <webwork1 key="ww"><actions>
    <action name="r.web.EditPage" alias="EditThing"/><action name="r.web.SudoPage" alias="SudoThing"/>
  </actions></webwork1>
  <servlet-filter key="guard" location="after-encoding" weight="200" class="r.G">
    <url-pattern>/secure/A.jspa</url-pattern><dispatcher>REQUEST</dispatcher>
  </servlet-filter>
</atlassian-plugin>"""


def _compile(tmp: Path, sources: dict[str, str]) -> dict[str, bytes]:
    javac = shutil.which("javac")
    if not javac or subprocess.run([javac, "-version"], capture_output=True).returncode != 0:
        pytest.skip("no JDK")
    src, out = tmp / "src", tmp / "classes"
    for rel, text in {**STUBS, **sources}.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text)
    out.mkdir()
    subprocess.run([javac, "--release", "11", "-d", str(out), *map(str, src.rglob("*.java"))], check=True)
    return {k: v for k, v in cf.classes_in_dir(out).items() if k.startswith(("o.", "r."))}


@pytest.fixture(scope="module")
def sides(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("security")
    o = _compile(tmp / "o", ORIGINAL)
    r = _compile(tmp / "r", REWRITE)
    def ref(xml, classes):
        root = ET.fromstring(xml)
        return sec.Reference(sec.endpoints(root, classes, None), sec.actions(root, classes, None), sec.filters(root, None))
    return ref(ORIGINAL_XML, o), ref(REWRITE_XML, r), ref(ORIGINAL_XML, o)


def test_the_original_against_itself_has_no_problems(sides):
    want, _, same = sides
    assert want.ids()[-3:] == ["action:EditThing", "action:SudoThing", "filter:guard"]
    assert set(want.endpoints) == {"rest:GET:/rest/p/1.0/items/{}", "rest:POST:/rest/p/1.0/items",
                                   "rest:POST:/rest/p/1.0/admin", "rest:GET:/rest/p/1.0/pub"}
    assert want.actions["EditThing"].xsrf == {"save": True, "default": False, "apply": True}   # inherited apply
    assert want.actions["SudoThing"].websudo and want.actions["SudoThing"].xsrf["apply"]
    for i, e in want.endpoints.items():
        assert sec.endpoint_problems(e, same.endpoints[i]) == []
    for a, act in want.actions.items():
        assert sec.action_problems(act, same.actions[a]) == []
    assert sec.filter_problems(want.filters["guard"], same.filters["guard"]) == []


def test_rest_endpoints_more_open_than_the_original(sides):
    want, got, _ = sides
    get = "rest:GET:/rest/p/1.0/items/{}"      # the path parameter's name differs: the same URL
    assert "anonymous" in " ".join(sec.endpoint_problems(want.endpoints[get], got.endpoints[get]))
    add = "rest:POST:/rest/p/1.0/items"
    assert "XSRF" in " ".join(sec.endpoint_problems(want.endpoints[add], got.endpoints[add]))
    adm = "rest:POST:/rest/p/1.0/admin"
    assert "websudo" in " ".join(sec.endpoint_problems(want.endpoints[adm], got.endpoints[adm]))
    assert "rest:GET:/rest/p/1.0/pub" not in got.endpoints          # not declared: t10 skips it
    extra = [i for i, e in got.endpoints.items() if i not in want.endpoints and e.anonymous]
    assert extra == ["rest:GET:/rest/p/1.0/debug"]


def test_actions_keep_their_xsrf_and_websudo_checks(sides):
    want, got, _ = sides
    edit = sec.action_problems(want.actions["EditThing"], got.actions["EditThing"])
    assert edit == ["command 'save' has no XSRF check (@RequiresXsrfCheck); the original's has"]
    # apply: checked in code through Jira's XsrfTokenGenerator, which counts as a check
    assert got.actions["EditThing"].xsrf["apply"] is True
    sudo = " ".join(sec.action_problems(want.actions["SudoThing"], got.actions["SudoThing"]))
    assert "XSRF check" in sudo and "websudo" in sudo and "unrestricted" in sudo


def test_filters_keep_location_patterns_and_dispatchers(sides):
    want, got, _ = sides
    p = " ".join(sec.filter_problems(want.filters["guard"], got.filters["guard"]))
    assert "location is 'after-encoding'" in p and "/rest/x/*" in p and "FORWARD" in p
    assert sec.filters(ET.fromstring('<a><servlet-filter key="k" location="x"/></a>'), None)["k"].dispatchers == {"REQUEST"}


def test_norm_path():
    assert sec.norm_path("/a/{id}/b/{name: [a-z]+}") == "/a/{}/b/{}"


def test_real_plugin_reference():
    """The plugin in vendor/ (git-ignored; skipped without it): what t10 checks, and that the original passes."""
    jars = sorted((TASK / "vendor").glob("*.jar"))
    if len(jars) != 1:
        pytest.skip("no plugin jar in fixtures/tasks/jira_re/vendor")
    libs = sorted((TASK / "vendor" / "lib").glob("*.jar"))
    ref = sec.original(jars[0], libs, "9.12.0")
    assert (len(ref.endpoints), len(ref.actions), len(ref.filters)) == (163, 50, 8)
    assert sum(1 for e in ref.endpoints.values() if sec.WEBSUDO in e.security) == 4      # dark features
    assert sum(sum(a.xsrf.values()) for a in ref.actions.values()) == 66               # C-4909, C-5103, ...
    assert ref.actions["StructureDarkFeatures"].websudo
    assert ref.filters["security-filter"].dispatchers == {"REQUEST", "INCLUDE", "FORWARD", "ERROR"}
    assert ref.module_of("action:StructureDarkFeatures") == "ww-structure"
    assert ref.module_of("filter:security-filter") == "security-filter"
    assert {ref.module_of(i) for i in ref.endpoints} == {"rest-v1", "rest-v2", "rest-cfd"}
    for i, e in ref.endpoints.items():
        assert sec.endpoint_problems(e, e) == [], i
    for a in ref.actions.values():
        assert sec.action_problems(a, a) == [], a.alias
