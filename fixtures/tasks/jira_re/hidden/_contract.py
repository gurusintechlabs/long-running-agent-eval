"""The original plugin's external contract, read from its class files (phase JS2, docs/jira-re-design.md §7.2).

Pure Python, like ``_classfile``. Three extractors, each limited to what another party can observe:

* **REST endpoints** of the ``<rest>`` modules that apply to the pinned Jira (``<restrict>`` ranges): HTTP
  method, full path (``/rest/<path>/<version>/...``), media types, parameters (kind, name, Java type,
  default), the request body's type, and the security annotations (anonymous access, websudo). Resource
  methods inherited from superclasses and sub-resource locators are followed, as JAX-RS does.
* **The Active Objects schema** of the ``<ao>`` module: table names with the namespace's ``AO_xxxxxx``
  prefix, and every column (name, Java type, string length, not null, indexed, unique, primary key, auto
  increment, default, referenced table).
* **JSON shapes**: the properties Jackson writes for a class (public fields and getters, ``@JsonProperty``
  renames, ``@JsonIgnore``), with JSON types; nested classes of the plugin stay class names, so the caller
  can name them.

The analyst's ``build_contract.py`` writes these into ``spec/SPEC.md`` and ``check_spec.py`` checks that
SPEC.md covers them. Class names in the results are internal; callers must not print them into ``spec/``.
"""
from __future__ import annotations

import fnmatch
import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import _classfile as cf

JAXRS = ("javax.ws.rs.", "jakarta.ws.rs.")
HTTP_METHODS = ("GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH")
PARAM_KINDS = {"PathParam": "path", "QueryParam": "query", "FormParam": "form", "HeaderParam": "header",
               "CookieParam": "cookie", "MatrixParam": "matrix", "FormDataParam": "form"}
SECURITY = ("AnonymousAllowed", "AnonymousSiteAccess", "UnrestrictedAccess", "UnlicensedSiteAccess",
            "LicensedOnly", "AdminOnly", "SystemAdminOnly", "WebSudoRequired", "WebSudoNotRequired",
            "XsrfProtectionExcluded", "CorsAllowed")
PENDING = "(not yet described)"     # build_contract's placeholder for an endpoint the analyst has not described


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def applies(el: ET.Element, jira: str) -> bool:
    """True when ``el`` has no ``<restrict>``, or one whose version range contains ``jira``."""
    rs = el.findall("restrict")
    if not rs:
        return True
    want = _version(jira)
    for r in rs:
        m = re.fullmatch(r"\s*([\[(])\s*([\d.]*)\s*(?:,\s*([\d.]*))?\s*([\])])\s*", r.get("version", ""))
        if not m:
            continue
        lo_inc, lo, hi, hi_inc = m.groups()
        if hi is None and lo_inc == "[" and hi_inc == ")":      # "[11.0.0)": from 11.0.0 on
            hi = ""
        ok_lo = not lo or (want >= _version(lo) if lo_inc == "[" else want > _version(lo))
        ok_hi = not hi or (want <= _version(hi) if hi_inc == "]" else want < _version(hi))
        if ok_lo and ok_hi:
            return True
    return False


def jar_classes(jar: Path, libs: list[str] = ()) -> dict[str, bytes]:
    """Class files of the jar and of the bundled jars matching ``libs`` (globs over its entries)."""
    out = cf.classes_in_jar(jar)
    with zipfile.ZipFile(jar) as z:
        for lib in (n for n in z.namelist() if any(fnmatch.fnmatchcase(n, g) for g in libs)):
            for name, data in cf.classes_in_jar(z.read(lib)).items():
                out.setdefault(name, data)
    return out


def descriptor(jar: Path) -> ET.Element | None:
    with zipfile.ZipFile(jar) as z:
        return ET.fromstring(z.read("atlassian-plugin.xml")) if "atlassian-plugin.xml" in z.namelist() else None


def _simple(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _anns(raw: cf.RawClass, attrs: dict[str, bytes]) -> dict[str, cf.Annotation]:
    """Annotations by simple name (JAX-RS, Atlassian REST, AO and Jackson annotations have distinct ones)."""
    return {_simple(a.type): a for a in cf.annotations(raw, attrs)}


def _as_list(v) -> tuple[str, ...]:
    return tuple(v) if isinstance(v, list) else (v,) if v else ()


# ---------------------------------------------------------------- REST

@dataclass
class Param:
    kind: str                # path | query | form | header | cookie | matrix | body
    name: str | None
    java: str
    default: str | None = None
    json: str = ""           # the JSON type, from the generic signature where there is one


@dataclass
class Endpoint:
    method: str
    path: str
    consumes: tuple[str, ...]
    produces: tuple[str, ...]
    params: list[Param]
    returns: str             # erased Java type; ``javax.ws.rs.core.Response`` says nothing of the payload
    returns_json: str        # the JSON type of ``returns`` (see ``json_type``)
    security: tuple[str, ...]
    source: str              # internal: declaring class#method (for the analyst's notes, never for spec/)

    @property
    def anonymous(self) -> bool:
        return any(s in self.security for s in ("AnonymousAllowed", "UnrestrictedAccess", "AnonymousSiteAccess"))


def endpoint_id(e: Endpoint) -> str:
    return f"{e.method} {e.path}"


def rest_modules(root: ET.Element, jira: str) -> list[tuple[str, str, list[str]]]:
    """``(key, base path, packages)`` of each ``<rest>`` module that applies to ``jira``, once per key."""
    out, seen = [], set()
    for el in root:
        if el.tag != "rest" or el.get("key") in seen or not applies(el, jira):
            continue
        seen.add(el.get("key"))
        base = "/rest/" + "/".join(s.strip("/") for s in (el.get("path", ""), el.get("version", "")) if s.strip("/"))
        out.append((el.get("key"), base, [p.text.strip() for p in el.findall("package") if p.text]))
    return out


def _join(*parts: str) -> str:
    segs = [s.strip("/") for s in parts if s and s.strip("/")]
    return "/" + "/".join(segs)


def _ancestry(classes: dict[str, bytes], name: str) -> list[cf.RawClass]:
    """``name`` and its superclasses and interfaces that ``classes`` holds, most derived first."""
    out, todo, seen = [], [name], set()
    while todo:
        n = todo.pop(0)
        if n in seen or n not in classes:
            continue
        seen.add(n)
        raw = cf.parse_class(classes[n])
        out.append(raw)
        todo += ([raw.superclass] if raw.superclass else []) + raw.interfaces
    return out


def _resource_methods(classes, name):
    """``(declaring class, method, annotations)`` of every JAX-RS-annotated method of ``name``. As in JAX-RS,
    an override without annotations inherits those of the overridden method."""
    picked: dict[tuple[str, str], tuple[cf.RawClass, cf.RawMember, dict]] = {}
    for raw in _ancestry(classes, name):
        for m in raw.methods:
            if m.access & (cf.ACC_STATIC | cf.ACC_SYNTHETIC | cf.ACC_BRIDGE) or not m.access & cf.ACC_PUBLIC:
                continue
            key = (m.name, m.descriptor.split(")", 1)[0])
            if key in picked:
                continue
            anns = _anns(raw, m.attrs)
            jaxrs = {k: a for k, a in anns.items() if a.type.startswith(JAXRS)}
            if jaxrs:
                picked[key] = (raw, m, anns)
    return list(picked.values())


def rest_endpoints(classes: dict[str, bytes], packages: list[str], base: str) -> list[Endpoint]:
    """Every endpoint of the root resources in ``packages`` (and their subpackages), under ``base``."""
    roots = []
    for n in sorted(classes):
        if not any(n.startswith(p + ".") for p in packages):
            continue
        raw = cf.parse_class(classes[n])
        if raw.access & (cf.ACC_ABSTRACT | cf.ACC_INTERFACE):
            continue
        path = _anns(raw, raw.attrs).get("Path")
        if path and path.type.startswith(JAXRS):
            roots.append((n, _join(base, str(path.values.get("value", "")))))
    out: list[Endpoint] = []
    for n, prefix in roots:
        _collect(classes, n, prefix, out, depth=0)
    order = {m: i for i, m in enumerate(HTTP_METHODS)}
    return sorted(out, key=lambda e: (e.path, order.get(e.method, 99), e.method))


def _collect(classes, name: str, prefix: str, out: list[Endpoint], depth: int) -> None:
    if depth > 8:
        return
    own = cf.parse_class(classes[name])
    cls_anns = _anns(own, own.attrs)
    for decl, m, anns in _resource_methods(classes, name):
        decl_anns = _anns(decl, decl.attrs)
        path = _join(prefix, str(anns["Path"].values.get("value", ""))) if "Path" in anns else prefix
        verbs = [v for v in HTTP_METHODS if v in anns and anns[v].type.startswith(JAXRS)]
        params_desc, ret = m.descriptor[1:].split(")", 1)
        if not verbs:
            if "Path" in anns and ret.startswith("L"):        # a sub-resource locator
                sub = ret[1:-1].replace("/", ".")
                if sub in classes:
                    _collect(classes, sub, path, out, depth + 1)
            continue

        def media(kind: str) -> tuple[str, ...]:
            for source in (anns, cls_anns, decl_anns):
                if kind in source and source[kind].type.startswith(JAXRS):
                    return _as_list(source[kind].values.get("value"))
            return ()
        types = cf._java_types(params_desc)
        p_anns = cf.parameter_annotations(decl, m.attrs)
        p_anns = [[]] * (len(types) - len(p_anns)) + p_anns
        sig = m.attrs.get("Signature")
        sig = decl.utf8(int.from_bytes(sig, "big")) if sig else m.descriptor
        jsons = _param_json(sig)
        if len(jsons) != len(types):                       # a signature without the synthetic parameters
            jsons = [json_type(_descriptor_of(t)) for t in types]
        params = []
        for java, pa, js in zip(types, p_anns, jsons):
            by = {_simple(a.type): a for a in pa}
            if "Context" in by or "Suspended" in by:
                continue
            kind = next((PARAM_KINDS[k] for k in by if k in PARAM_KINDS), None)
            default = by["DefaultValue"].values.get("value") if "DefaultValue" in by else None
            if kind:
                name = next(by[k].values.get("value") for k in by if k in PARAM_KINDS)
                params.append(Param(kind, str(name), java, default, js))
            else:
                params.append(Param("body", None, java, default, js))
        security = tuple(s for s in SECURITY if s in anns or s in cls_anns or s in decl_anns)
        ret_sig = sig.rsplit(")", 1)[1]
        for v in verbs:
            out.append(Endpoint(v, path, media("Consumes"), media("Produces"), params, cf._java_types(ret)[0],
                                json_type(ret_sig), security, f"{decl.name}#{m.name}"))


# ---------------------------------------------------------------- Active Objects

@dataclass
class Column:
    name: str
    java: str
    length: int | None = None            # @StringLength; -1 is unlimited
    not_null: bool = False
    indexed: bool = False
    unique: bool = False
    primary_key: bool = False
    auto_increment: bool = False
    default: str | None = None
    references: str | None = None        # the referenced table, for a column holding another entity


@dataclass
class Table:
    name: str
    entity: str                          # internal
    columns: list[Column] = field(default_factory=list)


def ao_prefix(namespace: str) -> str:
    """Active Objects' table prefix: ``AO_`` and the last six hex digits of the MD5 of the namespace."""
    return "AO_" + hashlib.md5(namespace.encode()).hexdigest()[-6:].upper()


def upper_underscore(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
    return s.upper()


def _is_entity(classes, name: str) -> bool:
    return any(i in ("net.java.ao.RawEntity", "net.java.ao.Entity") or
               (not i.startswith("net.java.ao.") and _is_entity(classes, i))
               for i in (cf.parse_class(classes[name]).interfaces if name in classes else []))


def _extends_entity(classes, name: str) -> bool:
    return any(i == "net.java.ao.Entity" or (not i.startswith("net.java.ao.") and _extends_entity(classes, i))
               for i in (cf.parse_class(classes[name]).interfaces if name in classes else []))


def _table_name(classes, name: str, prefix: str) -> str:
    raw = cf.parse_class(classes[name])
    t = _anns(raw, raw.attrs).get("Table")
    return f"{prefix}_{t.values['value'] if t else upper_underscore(_simple(name).rsplit('$', 1)[-1])}"


def ao_tables(classes: dict[str, bytes], entities: list[str], namespace: str) -> list[Table]:
    prefix = ao_prefix(namespace)
    out = []
    for e in entities:
        if e not in classes:
            continue
        t = Table(_table_name(classes, e, prefix), e)
        if _extends_entity(classes, e):
            t.columns.append(Column("ID", "int", not_null=True, primary_key=True, auto_increment=True))
        seen = {c.name for c in t.columns}
        for raw in _ancestry(classes, e):
            if raw.name.startswith("net.java.ao."):
                continue
            for m in raw.methods:
                col = _column(classes, raw, m, prefix)
                if col and col.name not in seen:
                    seen.add(col.name)
                    t.columns.append(col)
        out.append(t)
    return out


def _column(classes, raw: cf.RawClass, m: cf.RawMember, prefix: str) -> Column | None:
    params, ret = m.descriptor[1:].split(")", 1)
    prop = re.match(r"(?:get|is)([A-Z].*)", m.name)
    if params or ret == "V" or not prop or m.access & cf.ACC_STATIC:
        return None
    anns = _anns(raw, m.attrs)
    if anns.keys() & {"Ignore", "OneToMany", "ManyToMany", "OneToOne", "Transient"} or ret.startswith("["):
        return None
    java = cf._java_types(ret)[0]
    name = anns["Accessor"].values.get("value") if "Accessor" in anns else None
    pk = "PrimaryKey" in anns
    name = name or (anns["PrimaryKey"].values.get("value") if pk else None)
    references = None
    if java in classes and _is_entity(classes, java):
        references = _table_name(classes, java, prefix)
        name = name or upper_underscore(prop.group(1)) + "_ID"
        java = "int" if _extends_entity(classes, java) else next(
            (c.java for c in ao_tables(classes, [java], "")[0].columns if c.primary_key), "java.lang.Object")
    name = name or upper_underscore(prop.group(1))
    length = anns["StringLength"].values.get("value") if "StringLength" in anns else None
    return Column(str(name), java, length, "NotNull" in anns, "Indexed" in anns, "Unique" in anns, pk,
                  "AutoIncrement" in anns, anns["Default"].values.get("value") if "Default" in anns else None,
                  references)


# ---------------------------------------------------------------- JSON shapes

INTEGERS = {"B", "S", "I", "J", "java.lang.Byte", "java.lang.Short", "java.lang.Integer", "java.lang.Long",
            "java.math.BigInteger", "java.util.concurrent.atomic.AtomicLong", "java.util.concurrent.atomic.AtomicInteger"}
NUMBERS = {"F", "D", "java.lang.Float", "java.lang.Double", "java.math.BigDecimal", "java.lang.Number"}
BOOLEANS = {"Z", "java.lang.Boolean"}
STRINGS = {"C", "java.lang.String", "java.lang.CharSequence", "java.lang.Character"}
ARRAYS = {"java.util.List", "java.util.Collection", "java.util.Set", "java.util.SortedSet", "java.util.Iterable",
          "java.lang.Iterable", "java.util.ArrayList", "java.util.LinkedHashSet", "java.util.HashSet",
          "java.util.TreeSet", "java.util.LinkedList"}
MAPS = {"java.util.Map", "java.util.HashMap", "java.util.LinkedHashMap", "java.util.TreeMap", "java.util.SortedMap"}


@dataclass
class Prop:
    name: str
    json: str                # integer | number | boolean | string | date | any | array<T> | map<K, V> | a class name
    java: str


def json_type(sig: str) -> str:
    """The JSON type of a field type signature (``Ljava/util/List<Lx/Item;>;``), plugin classes left by name."""
    t, _ = _sig_type(sig, 0)
    return t


_PRIM_CODE = {"byte": "B", "char": "C", "double": "D", "float": "F", "int": "I", "long": "J", "short": "S",
              "boolean": "Z"}


def _descriptor_of(java: str) -> str:
    dims = java.count("[]")
    base = java.replace("[]", "")
    return "[" * dims + (_PRIM_CODE.get(base) or f"L{base.replace('.', '/')};")


def _param_json(sig: str) -> list[str]:
    """JSON types of a method signature's parameters (``<T:...>(...)R``)."""
    i = 0
    if sig.startswith("<"):                              # formal type parameters
        depth = 0
        for i, ch in enumerate(sig):
            depth += {"<": 1, ">": -1}.get(ch, 0)
            if depth == 0:
                break
        i += 1
    i = sig.index("(", i) + 1
    out = []
    while sig[i] != ")":
        t, i = _sig_type(sig, i)
        out.append(t)
    return out


def _sig_type(s: str, i: int) -> tuple[str, int]:
    c = s[i]
    if c == "[":
        inner, i = _sig_type(s, i + 1)
        return f"array<{inner}>", i
    if c == "T":
        return "any", s.index(";", i) + 1
    if c in "+-":
        return _sig_type(s, i + 1)
    if c == "*":
        return "any", i + 1
    if c != "L":
        return _json_of(c, []), i + 1
    j, args, name = i + 1, [], ""
    while s[j] not in "<;":
        j += 1
    name = s[i + 1:j].replace("/", ".")
    if s[j] == "<":
        j += 1
        while s[j] != ">":
            a, j = _sig_type(s, j)
            args.append(a)
        j += 1
    while s[j] == ".":                                   # inner class of a generic outer: Outer<T>.Inner<U>
        k = j + 1
        while s[k] not in "<;.":
            k += 1
        name += "$" + s[j + 1:k]
        j, args = k, []
        if s[j] == "<":
            j += 1
            while s[j] != ">":
                a, j = _sig_type(s, j)
                args.append(a)
            j += 1
    return _json_of(name, args), j + 1


def _json_of(name: str, args: list[str]) -> str:
    if name == "V":
        return "none"
    if name in INTEGERS:
        return "integer"
    if name in NUMBERS:
        return "number"
    if name in BOOLEANS:
        return "boolean"
    if name in STRINGS:
        return "string"
    if name in ("java.util.Date", "java.sql.Timestamp", "java.time.Instant"):
        return "date"
    if name in ARRAYS:
        return f"array<{args[0] if args else 'any'}>"
    if name in MAPS:
        k, v = (args + ["any", "any"])[:2]
        return f"map<{'string' if k in ('string', 'integer') else k}, {v}>"
    if name in ("java.lang.Object", "java.io.Serializable") or name.split(".")[-1] in (
            "JsonNode", "ObjectNode", "JSONObject", "JSONArray", "ArrayNode"):
        return "any"
    if name == "java.util.Optional":
        return args[0] if args else "any"
    return name


def _sig_of(raw: cf.RawClass, m: cf.RawMember, getter: bool) -> str:
    sig = m.attrs.get("Signature")
    s = raw.utf8(int.from_bytes(sig, "big")) if sig else m.descriptor
    return s.rsplit(")", 1)[1] if getter else s


def is_enum(classes, name: str) -> bool:
    return name in classes and bool(cf.parse_class(classes[name]).access & cf.ACC_ENUM)


def enum_constants(classes, name: str) -> list[str]:
    raw = cf.parse_class(classes[name])
    return [f.name for f in raw.fields if f.access & cf.ACC_ENUM]


def json_fields(classes: dict[str, bytes], name: str) -> list[Prop]:
    """The properties Jackson writes for ``name`` (with its superclasses), in declaration order."""
    props: dict[str, Prop] = {}
    ignored: set[str] = set()
    explicit: set[str] = set()       # named by an explicit @JsonProperty, which wins over @JsonIgnore elsewhere
    chain = [r for r in _ancestry(classes, name) if not r.access & cf.ACC_INTERFACE]
    for raw in reversed(chain):                          # superclass properties first, as Jackson orders them
        for f in raw.fields:
            anns = _anns(raw, f.attrs)
            renamed = anns["JsonProperty"].values.get("value") if "JsonProperty" in anns else None
            if f.access & (cf.ACC_STATIC | cf.ACC_SYNTHETIC) or f.access & 0x80:   # 0x80: transient
                continue
            if "JsonIgnore" in anns:
                ignored.add(f.name)
                continue
            if "JsonProperty" in anns:
                explicit.add(renamed or f.name)
            if f.access & cf.ACC_PUBLIC or "JsonProperty" in anns:
                n = renamed or f.name
                props[n] = Prop(n, json_type(_sig_of(raw, f, False)), cf._java_types(f.descriptor)[0])
        for m in raw.methods:
            params, ret = m.descriptor[1:].split(")", 1)
            anns = _anns(raw, m.attrs)
            setter = re.match(r"set([A-Z].*)", m.name)
            if setter and ret == "V" and len(cf._java_types(params)) == 1 and "JsonProperty" in anns:
                n = anns["JsonProperty"].values.get("value") or setter.group(1)[0].lower() + setter.group(1)[1:]
                explicit.add(n)
                if n not in props:
                    sig = _sig_of(raw, m, False)
                    props[n] = Prop(n, (_param_json(sig) or ["any"])[0], cf._java_types(params)[0])
                continue
            g = re.match(r"(get|is)([A-Z].*)", m.name)
            if params or ret == "V" or not g or m.name == "getClass" or m.access & (cf.ACC_STATIC | cf.ACC_SYNTHETIC
                                                                                    | cf.ACC_BRIDGE):
                continue
            if g.group(1) == "is" and ret != "Z":
                continue
            prop = g.group(2)[0].lower() + g.group(2)[1:]
            if "JsonIgnore" in anns:
                ignored.add(prop)
                continue
            if m.access & cf.ACC_PUBLIC or "JsonProperty" in anns:
                n = (anns["JsonProperty"].values.get("value") if "JsonProperty" in anns else None) or prop
                if "JsonProperty" in anns:
                    explicit.add(n)
                if n not in props:
                    props[n] = Prop(n, json_type(_sig_of(raw, m, True)), cf._java_types(ret)[0])
    return [p for n, p in props.items() if n not in ignored - explicit]


def _refs(json: str) -> list[str]:
    return [t for t in re.split(r"[<>, ]+", json) if "." in t]


def reachable_shapes(classes: dict[str, bytes], roots: list[str]) -> list[str]:
    """``roots`` and every class of ``classes`` their JSON properties reach, sorted."""
    seen, todo = set(), [r for r in roots if r in classes]
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        if is_enum(classes, n):
            continue
        for p in json_fields(classes, n):
            todo += [t for t in _refs(p.json) if t in classes and t not in seen]
    return sorted(seen)
