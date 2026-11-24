#!/usr/bin/env python3
"""Write the generated parts of the seed's ``spec/SPEC.md`` (phase JS2): the module table, the REST endpoints,
their JSON shapes and the Active Objects schema.

    .venv/bin/python fixtures/tasks/jira_re/analyst/build_contract.py [--check]

What can be read off the class files is extracted (``hidden/_contract.py``): every endpoint's method, path,
media types, parameters and access; the JSON keys and types of every payload class; every table and column.
What needs reading the code comes from the analyst's notes, ``analyst/contract-notes/*.json`` (harness-side):

    {"endpoints": {"GET /rest/...": {"summary", "params": {name or "body": meaning}, "request", "response", "errors"}},
     "shapes":    {"<payload class>": {"name": "own-words-name", "summary", "fields": {json key: meaning},
                                       "values": {enum constant: meaning}}},
     "tables":    {"AO_xxxxxx_NAME": {"summary", "columns": {column: meaning and stored format}}},
     "conventions": "markdown: what all REST endpoints share", "persisted": "markdown: other persisted names"}

Notes name a payload class only as ``{{fq.Class}}``; it is rendered as the shape's own-words name, so no class
name reaches ``spec/`` (the build fails if one would). The rest of SPEC.md is hand-written; only the text
between ``<!-- BEGIN generated: X -->`` and ``<!-- END generated: X -->`` is replaced. An endpoint, shape or
table without notes is written with the placeholder ``(not yet described)``, which ``check_spec.py`` reports.
Notes for an endpoint, shape field or table that does not exist fail the build (stale notes).
``--check`` exits 1 when SPEC.md is stale.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK / "hidden"))
sys.path.insert(0, str(HERE))

import _contract as ct  # noqa: E402
from _contract import PENDING  # noqa: E402

BLOCKS = ("modules", "rest-conventions", "rest-endpoints", "rest-shapes", "ao", "persisted")
TEXTS = {"conventions": "rest-conventions", "persisted": "persisted"}   # free markdown in the notes -> block
NOTES_DIR = HERE / "contract-notes"
REF = re.compile(r"\{\{([\w.$]+)\}\}")
FQCN = re.compile(r"\b(?:[a-z_][a-z0-9_]*\.)+[A-Z][A-Za-z0-9_$]*")
ACCESS = {"AnonymousAllowed": "anonymous users allowed", "WebSudoRequired": "Jira administrator with websudo",
          "XsrfProtectionExcluded": "no XSRF check", "CorsAllowed": "CORS allowed"}


def load_notes(folder: Path) -> dict:
    out = {"endpoints": {}, "shapes": {}, "tables": {}}
    for f in sorted(folder.glob("*.json")):
        data = json.loads(f.read_text())
        for key in TEXTS:
            if data.get(key):
                if key in out:
                    raise ValueError(f"{f.name}: {key!r} is written in two notes files")
                out[key] = data[key]
        for kind in ("endpoints", "shapes", "tables"):
            for k, v in (data.get(kind) or {}).items():
                if k in out[kind]:
                    raise ValueError(f"{f.name}: {kind} {k!r} is described in two notes files")
                out[kind][k] = v
    return out


def splice(md: str, block: str, body: str) -> str:
    begin, end = f"<!-- BEGIN generated: {block} -->", f"<!-- END generated: {block} -->"
    if begin not in md or end not in md:
        raise ValueError(f"SPEC.md has no markers for the generated block {block!r}")
    head, rest = md.split(begin, 1)
    return f"{head}{begin}\n{body.rstrip()}\n{end}{rest.split(end, 1)[1]}"


def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def build(md: str, *, jar: Path, libs: list[str], jira: str, notes: dict, inventory: dict,
          extra_classes: dict[str, bytes] | None = None, allowed: set[str] = frozenset()) -> tuple[str, dict]:
    """``allowed``: class names that are contract (``contract-classes.txt``) and may appear."""
    classes = ct.jar_classes(jar, libs)
    internal = set(classes)
    for n, data in (extra_classes or {}).items():
        classes.setdefault(n, data)
    root = ct.descriptor(jar)
    endpoints = [(key, e) for key, base, pk in ct.rest_modules(root, jira) for e in ct.rest_endpoints(classes, pk, base)]
    ids = {ct.endpoint_id(e) for _, e in endpoints}
    stale = sorted(set(notes["endpoints"]) - ids)
    if stale:
        raise ValueError(f"notes describe endpoints that do not exist: {', '.join(stale)}")

    texts = json.dumps(notes)
    refs = set(REF.findall(texts))
    unknown = sorted(r for r in refs | set(notes["shapes"]) if r not in classes)
    if unknown:
        raise ValueError(f"notes name payload classes that do not exist: {', '.join(unknown)}")
    roots = set(refs) | set(notes["shapes"])
    for _, e in endpoints:
        for t in [e.returns_json] + [p.json for p in e.params]:
            roots |= {x for x in ct._refs(t) if x in classes and not x.startswith(("javax.", "jakarta."))}
    shapes = ct.reachable_shapes(classes, sorted(roots))
    names: dict[str, str] = {}
    for i, s in enumerate(shapes, 1):
        names[s] = notes["shapes"].get(s, {}).get("name") or f"unnamed-{i}"
    dup = sorted({n for n in names.values() if list(names.values()).count(n) > 1})
    if dup:
        raise ValueError(f"two payload classes share the shape name {', '.join(dup)}")

    def link(cls: str) -> str:
        return f"[`{names[cls]}`](#shape-{names[cls]})"

    def jtype(t: str) -> str:
        if t == "javax.ws.rs.core.Response":
            return "see below"
        return re.sub(r"[\w.$]+\.[\w$]+", lambda m: link(m.group(0)) if m.group(0) in names else m.group(0), t)

    def text(s: str | None) -> str:
        return REF.sub(lambda m: link(m.group(1)), s or "")

    out = md
    for key, block in TEXTS.items():
        out = splice(out, block, text(notes.get(key)) or PENDING)
    # modules
    rows = ["| key | type | contract class | group |", "|---|---|---|---|"]
    for m in inventory["modules"]:
        rows.append(f"| `{m['key']}` | `{m['type']}` | {('`' + m['class'] + '`') if m.get('class') else ''} | "
                    f"{m.get('group') or ''} |")
    out = splice(out, "modules", "\n".join(rows))

    # endpoints, grouped by module
    lines, described, current = [], 0, None
    for key, e in endpoints:
        if key != current:
            current = key
            lines += [f"### Module `{key}`", ""]
        n = notes["endpoints"].get(ct.endpoint_id(e), {})
        described += bool(n.get("summary"))
        access = [ACCESS[s] for s in e.security if s in ACCESS] or ["logged-in user"]
        if "AnonymousAllowed" in e.security and "WebSudoRequired" in e.security:
            access.remove("anonymous users allowed")
        lines += [f"#### `{ct.endpoint_id(e)}`", "",
                  f"Access: {', '.join(access)}. Consumes: {', '.join(f'`{x}`' for x in e.consumes) or 'any'}. "
                  f"Produces: {', '.join(f'`{x}`' for x in e.produces) or 'any'}.", ""]
        if e.params:
            lines += ["| parameter | in | type | default | meaning |", "|---|---|---|---|---|"]
            for p in e.params:
                meaning = (n.get("params") or {}).get(p.name or "body", "")
                default = f"`{p.default}`" if p.default is not None else ""
                lines.append(f"| {('`' + p.name + '`') if p.name else '(body)'} | {p.kind} | {jtype(p.json)} | "
                             f"{default} | {_cell(text(meaning))} |")
            lines.append("")
        lines += [text(n.get("summary")) or PENDING, ""]
        if n.get("request"):
            lines += [f"**Request.** {text(n['request'])}", ""]
        body = "" if e.returns_json in ("javax.ws.rs.core.Response", "none") else f"Body: {jtype(e.returns_json)}. "
        if body and jtype(e.returns_json) in text(n.get("response")):      # the notes already name it
            body = ""
        if body or n.get("response"):
            lines += [f"**Response.** {body}{text(n.get('response'))}".rstrip(), ""]
        if n.get("errors"):
            lines += [f"**Errors.** {text(n['errors'])}", ""]
    out = splice(out, "rest-endpoints", "\n".join(lines))

    # shapes
    lines, named = [], 0
    for s in sorted(shapes, key=lambda c: names[c]):
        n = notes["shapes"].get(s, {})
        named += bool(n.get("name"))
        lines += [f'<a id="shape-{names[s]}"></a>', "", f"#### Shape `{names[s]}`", "", text(n.get("summary")) or PENDING, ""]
        if ct.is_enum(classes, s):
            consts = ct.enum_constants(classes, s)
            bad = sorted(set(n.get("values") or {}) - set(consts))
            if bad:
                raise ValueError(f"shape {names[s]}: notes describe unknown values {', '.join(bad)}")
            lines += ["A JSON string, one of:", "", "| value | meaning |", "|---|---|"]
            lines += [f"| `{c}` | {_cell(text((n.get('values') or {}).get(c, '')))} |" for c in consts]
        else:
            fields = ct.json_fields(classes, s)
            bad = sorted(set(n.get("fields") or {}) - {f.name for f in fields})
            if bad:
                raise ValueError(f"shape {names[s]}: notes describe unknown fields {', '.join(bad)}")
            if fields:
                lines += ["| key | JSON type | meaning |", "|---|---|---|"]
                lines += [f"| `{f.name}` | {jtype(f.json)} | {_cell(text((n.get('fields') or {}).get(f.name, '')))} |"
                          for f in fields]
        lines.append("")
    out = splice(out, "rest-shapes", "\n".join(lines))

    # Active Objects
    lines, tables_described, all_tables = [], 0, []
    for el in root.iter("ao"):
        entities = [x.text.strip() for x in el.findall("entity") if x.text]
        all_tables += ct.ao_tables(classes, entities, el.get("namespace", ""))
    stale = sorted(set(notes["tables"]) - {t.name for t in all_tables})
    if stale:
        raise ValueError(f"notes describe tables that do not exist: {', '.join(stale)}")
    for t in all_tables:
        n = notes["tables"].get(t.name, {})
        tables_described += bool(n.get("summary"))
        bad = sorted(set(n.get("columns") or {}) - {c.name for c in t.columns})
        if bad:
            raise ValueError(f"table {t.name}: notes describe unknown columns {', '.join(bad)}")
        lines += [f"#### Table `{t.name}`", "", text(n.get("summary")) or PENDING, "",
                  "| column | Java type | length | constraints | meaning and stored format |", "|---|---|---|---|---|"]
        for c in t.columns:
            java = re.sub(r"^java\.(lang|util)\.", "", c.java)
            length = "unlimited" if c.length == -1 else (str(c.length) if c.length else "")
            flags = [f for f, on in (("primary key", c.primary_key), ("auto increment", c.auto_increment),
                                     ("not null", c.not_null), ("unique", c.unique), ("indexed", c.indexed)) if on]
            if c.default is not None:
                flags.append(f"default `{c.default}`")
            if c.references:
                flags.append(f"references `{c.references}`")
            lines.append(f"| `{c.name}` | {java} | {length} | {', '.join(flags)} | "
                         f"{_cell(text((n.get('columns') or {}).get(c.name, '')))} |")
        lines.append("")
    out = splice(out, "ao", "\n".join(lines))

    leaked = sorted({n for n in FQCN.findall(out) if n not in allowed and (n in internal or n.replace(".", "$") in internal)})
    if leaked:
        raise ValueError(f"the generated contract would name internal classes: {', '.join(leaked)}")
    return out, {"endpoints": (described, len(endpoints)), "shapes": (named, len(shapes)),
                 "tables": (tables_described, len(all_tables))}


def main() -> int:
    import _api
    import _classfile as cf
    from check_spec import SEED_SPEC, contract_classes, internal_libs, jira_version
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if spec/SPEC.md is stale")
    args = ap.parse_args()
    jars = sorted((TASK / "vendor").glob("*.jar"))
    if len(jars) != 1:
        raise SystemExit(f"{TASK / 'vendor'} must hold exactly one jar; found {len(jars)}")
    extra: dict[str, bytes] = {}
    for j in _api.api_jars():
        extra.update(cf.classes_in_jar(j))
    path = SEED_SPEC / "SPEC.md"
    md, report = build(path.read_text(), jar=jars[0], libs=internal_libs(), jira=jira_version(),
                       notes=load_notes(NOTES_DIR), inventory=json.loads((SEED_SPEC / "inventory.json").read_text()),
                       extra_classes=extra, allowed=contract_classes(HERE / "contract-classes.txt"))
    summary = "; ".join(f"{k} {a}/{b} described" for k, (a, b) in report.items())
    if args.check:
        stale = path.read_text() != md
        print(f"{'stale' if stale else 'up to date'}: {summary}")
        return 1 if stale else 0
    path.write_text(md)
    print(f"wrote {path}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
