#!/usr/bin/env python3
"""Write the seed's ``spec/API.md``, Part 2 of the spec (phase JS3): the public Java API.

    .venv/bin/python fixtures/tasks/jira_re/analyst/build_api.py [--check] [--skeleton PKG ...]

Every client-visible type of the real API (``vendor/api/``) and every public or protected member is read off
the class files (``hidden/_classfile.py``) and written as a Java declaration: modifiers, type parameters with
their bounds, supertypes, parameter and return types with their generics, varargs, ``throws``, constant
values and annotation defaults. Two more types are contract although the API does not hold them
(``EXTRA_TYPES``, from the plugin jar: an OSGi service interface and its record type).

The meaning of each package, type and member comes from the analyst's notes, ``analyst/api-notes/*.json``
(harness-side), in the analyst's own words:

    {"intro": "markdown: how to read API.md",
     "packages": {"com.acme.api": "markdown"},
     "types":    {"com.acme.api.Outer.Inner": {"summary": "markdown", "members": {"<member key>": "meaning"}}}}

Types are named in Java source form (``Outer.Inner``). A member key is the member's name, for a method or
constructor (``<init>``) followed by its erased parameter types: ``NAME``, ``get(long, String)``,
``<init>(int)``, ``of(Object[])``. ``--skeleton`` prints the empty notes of some packages with every key.

Anything without notes is written as ``(not yet described)``, which ``check_spec.py`` reports. Notes for a
package, type or member that does not exist fail the build (stale notes), and so does any internal class
name in the output. ``--check`` exits 1 when API.md is stale.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK / "hidden"))
sys.path.insert(0, str(HERE))

import _classfile as cf  # noqa: E402
from _contract import PENDING  # noqa: E402

NOTES_DIR = HERE / "api-notes"
EXTRA_TYPES = ("com.almworks.jira.structure.generic.GenericItemHistoryManager",
               "com.almworks.jira.structure.generic.GenericItemHistoryRecord")
FQCN = re.compile(r"\b(?:[a-z_][a-z0-9_]*\.)+[A-Z][A-Za-z0-9_$]*(?:\.[A-Z][A-Za-z0-9_$]*)*")
STANDARD = {   # members every enum has; their meaning is Java's
    "values()": "All constants, in declaration order (a new array on every call).",
    "valueOf(String)": "The constant with exactly this name; `IllegalArgumentException` when there is none, "
                       "`NullPointerException` for null.",
}
ACC_ENUM, ACC_STATIC = 0x4000, 0x0008


def dotted(binary: str) -> str:
    return binary.replace("$", ".")


def short(name: str) -> str:
    """``java.lang.String`` -> ``String``; other names stay fully qualified."""
    return name[10:] if name.startswith("java.lang.") and "." not in name[10:] else name


# ---------------------------------------------------------------- generic signatures as Java text

class _Reader:
    """Java text of a JVM signature or descriptor (JVMS 4.7.9.1), keeping type variable names."""

    def __init__(self, sig: str):
        self.s, self.i = sig, 0

    def peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def take(self, stop: str) -> str:
        j = self.i
        while self.s[j] not in stop:
            j += 1
        out, self.i = self.s[self.i:j], j
        return out

    def type(self) -> str:
        c = self.s[self.i]
        self.i += 1
        if c in cf._PRIMS:
            return cf._PRIMS[c]
        if c == "[":
            return self.type() + "[]"
        if c == "T":
            name = self.take(";")
            self.i += 1
            return name
        if c != "L":
            raise ValueError(f"bad signature {self.s!r} at {self.i - 1}")
        parts = []
        while True:
            part = self.take("<;.").replace("/", ".")
            if self.peek() == "<":
                self.i += 1
                args = []
                while self.peek() != ">":
                    args.append(self.arg())
                self.i += 1
                part += f"<{', '.join(args)}>"
            parts.append(part)
            if self.peek() == ".":
                self.i += 1
                continue
            self.i += 1
            break
        head = parts[0]
        name, _, generics = head.partition("<")
        first = short(dotted(name)) + (f"<{generics}" if generics else "")
        return ".".join([first, *parts[1:]])

    def arg(self) -> str:
        c = self.peek()
        if c == "*":
            self.i += 1
            return "?"
        if c in "+-":
            self.i += 1
            return f"? {'extends' if c == '+' else 'super'} {self.type()}"
        return self.type()

    def type_params(self) -> str:
        if self.peek() != "<":
            return ""
        self.i += 1
        out = []
        while self.peek() != ">":
            name = self.take(":")
            bounds = []
            while self.peek() == ":":
                self.i += 1
                if self.peek() != ":":
                    bounds.append(self.type())
            bounds = [b for b in bounds if b != "Object"]
            out.append(name + (f" extends {' & '.join(bounds)}" if bounds else ""))
        self.i += 1
        return f"<{', '.join(out)}>"


def method_parts(sig: str) -> tuple[str, list[str], str, list[str]]:
    """``(type parameters, parameter types, return type, thrown types)`` of a method signature or descriptor."""
    r = _Reader(sig)
    tparams = r.type_params()
    r.i += 1                      # (
    params = []
    while r.peek() != ")":
        params.append(r.type())
    r.i += 1
    ret = r.type()
    throws = []
    while r.peek() == "^":
        r.i += 1
        throws.append(r.type())
    return tparams, params, ret, throws


def class_parts(sig: str) -> tuple[str, list[str]]:
    """``(type parameters, [superclass, interface, ...])`` of a class signature."""
    r = _Reader(sig)
    tparams = r.type_params()
    supers = []
    while r.peek():
        supers.append(r.type())
    return tparams, supers


def descriptor_type(desc: str) -> str:
    return _Reader(desc).type()


# ---------------------------------------------------------------- the documented surface

@dataclass
class Doc:
    """One documented type: its declaration and its members as (key, declaration)."""
    name: str                          # dotted, Java source form
    binary: str
    surface: cf.TypeSurface
    declaration: str
    members: list[tuple[str, str]]


def _raw_sig(raw: cf.RawClass, attrs: dict[str, bytes]) -> str | None:
    b = attrs.get("Signature")
    return raw.utf8(struct.unpack(">H", b)[0]) if b else None


def _annotation_default(raw: cf.RawClass, attrs: dict[str, bytes]) -> str | None:
    b = attrs.get("AnnotationDefault")
    if not b:
        return None
    value, _ = cf._element_value(raw, b, 0)
    enum_const = re.compile(r"^[\w.$]+\.[A-Z_][A-Z0-9_]*$")      # _element_value's "Type.CONST"

    def lit(v) -> str:
        if isinstance(v, list):
            return "{" + ", ".join(map(lit, v)) + "}"
        if isinstance(v, bool):
            return str(v).lower()
        if isinstance(v, str) and enum_const.match(v):
            return dotted(v)
        return json.dumps(v) if isinstance(v, str) else repr(v)
    return lit(value)


def member_key(m: cf.Member) -> str:
    if m.kind == "field":
        return m.name
    params = m.descriptor[1:].split(")", 1)[0]
    return f"{m.name}({', '.join(short(dotted(t)) for t in cf._java_types(params))})"


def _modifiers(flags: tuple[str, ...], order: tuple[str, ...]) -> str:
    return " ".join(f for f in order if f in flags)


def _const(v) -> str:
    if isinstance(v, str):
        return json.dumps(v)
    return repr(v)


def _simple(t: cf.TypeSurface) -> str:
    """``Outer.Inner`` for a member type, ``Name`` for a top-level one."""
    return dotted(t.name.rsplit(".", 1)[-1])


def type_declaration(t: cf.TypeSurface, raw: cf.RawClass) -> str:
    sig = _raw_sig(raw, raw.attrs)
    if sig:
        tparams, supers = class_parts(sig)
        superclass, interfaces = (supers[0], supers[1:]) if t.kind != "interface" and t.kind != "annotation" \
            else (None, supers[1:])
    else:
        tparams = ""
        superclass = short(dotted(raw.superclass)) if raw.superclass else None
        interfaces = [short(dotted(i)) for i in raw.interfaces]
    word = {"class": "class", "interface": "interface", "enum": "enum", "annotation": "@interface"}[t.kind]
    head = f"{_modifiers(t.flags, ('public', 'protected', 'abstract', 'static', 'final'))} {word} {_simple(t)}{tparams}"
    if t.kind == "class" and superclass and superclass != "Object":
        head += f" extends {superclass}"
    if t.kind == "annotation":
        interfaces = [i for i in interfaces if i != "java.lang.annotation.Annotation"]
    if interfaces:
        head += f" {'extends' if t.kind in ('interface', 'annotation') else 'implements'} {', '.join(interfaces)}"
    return head


def member_declaration(t: cf.TypeSurface, raw: cf.RawClass, m: cf.Member, rm: cf.RawMember) -> str:
    if m.kind == "field":
        if t.kind == "enum" and rm.access & ACC_ENUM:
            return f"{m.name} (enum constant)"
        sig = _raw_sig(raw, rm.attrs)
        typ = descriptor_type(sig or m.descriptor)
        decl = f"{_modifiers(m.flags, ('public', 'protected', 'static', 'final'))} {typ} {m.name}"
        return decl + (f" = {_const(m.constant)}" if m.constant is not None else "")
    sig = _raw_sig(raw, rm.attrs)
    tparams, params, ret, throws = method_parts(sig or m.descriptor)
    if not sig and m.name == "<init>" and t.outer and "static" not in t.flags and t.kind == "class" and params:
        params = params[1:]       # the enclosing instance, which Java source does not show
    if not throws:
        throws = [short(dotted(e)) for e in m.exceptions]
    if "varargs" in m.flags and params and params[-1].endswith("[]"):
        params[-1] = params[-1][:-2] + "..."
    mods = _modifiers(m.flags, ("public", "protected", "abstract", "default", "static", "final"))
    name = _simple(t).rsplit(".", 1)[-1] if m.name == "<init>" else m.name
    decl = f"{mods} {tparams + ' ' if tparams else ''}{'' if m.name == '<init>' else ret + ' '}{name}({', '.join(params)})"
    if throws:
        decl += f" throws {', '.join(throws)}"
    default = _annotation_default(raw, rm.attrs) if t.kind == "annotation" else None
    return decl + (f" default {default}" if default is not None else "")


def document(classes: dict[str, bytes], names: list[str] | None = None) -> list[Doc]:
    """The documented types among ``classes``: every client-visible one, or only ``names`` (binary) and their
    visible member types. Member types follow their enclosing type; otherwise by name."""
    surface = cf.surface_from_classes(classes)
    if names is not None:
        wanted = set(names)
        surface = {n: t for n, t in surface.items() if n in wanted or cf.top_level(n) in wanted}
    order = sorted(surface, key=lambda n: (n.rsplit(".", 1)[0], n))
    docs = []
    for n in order:
        t = surface[n]
        raw = cf.parse_class(classes[n])
        listed = []
        for kind, rms in (("field", raw.fields), ("method", raw.methods)):    # class-file order: source order
            for rm in rms:
                m = t.members.get(f"{rm.name}{rm.descriptor}" if kind == "method" else f"{rm.name}:{rm.descriptor}")
                if m is not None:
                    listed.append((member_key(m), member_declaration(t, raw, m, rm)))
        docs.append(Doc(dotted(n), n, t, type_declaration(t, raw), listed))
    return docs


# ---------------------------------------------------------------- notes and rendering

def load_notes(folder: Path) -> dict:
    out: dict = {"packages": {}, "types": {}}
    for f in sorted(folder.glob("*.json")):
        data = json.loads(f.read_text())
        if data.get("intro"):
            if "intro" in out:
                raise ValueError(f"{f.name}: 'intro' is written in two notes files")
            out["intro"] = data["intro"]
        for kind in ("packages", "types"):
            for k, v in (data.get(kind) or {}).items():
                if k in out[kind]:
                    raise ValueError(f"{f.name}: {kind} {k!r} is described in two notes files")
                out[kind][k] = v
    return out


def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _package(d: Doc) -> str:
    return cf.top_level(d.binary).rsplit(".", 1)[0]


def build(docs: list[Doc], notes: dict, *, internal: set[str] = frozenset(),
          allowed: set[str] = frozenset()) -> tuple[str, dict]:
    """API.md from ``docs`` and the notes. ``internal``: class names that must not appear (the plugin's own
    classes and non-public API classes), unless ``allowed``."""
    by_name = {d.name: d for d in docs}
    packages = sorted({_package(d) for d in docs})
    stale = sorted(set(notes.get("packages") or {}) - set(packages))
    stale += sorted(set(notes.get("types") or {}) - set(by_name))
    for name, n in (notes.get("types") or {}).items():
        if name in by_name:
            keys = {k for k, _ in by_name[name].members}
            stale += [f"{name}#{k}" for k in sorted(set(n.get("members") or {}) - keys)]
    if stale:
        raise ValueError(f"notes describe API names that do not exist: {', '.join(stale)}")

    lines = ["# API: the public Java API", "",
             "<!-- generated by build_api.py from the original's class files and the analyst's notes -->", "",
             notes.get("intro") or PENDING, ""]
    types_done = members_done = members_all = 0
    for pkg in packages:
        lines += [f"## Package `{pkg}`", "", (notes.get("packages") or {}).get(pkg) or PENDING, ""]
        for d in (x for x in docs if _package(x) == pkg):
            n = (notes.get("types") or {}).get(d.name) or {}
            meanings = n.get("members") or {}
            types_done += bool(n.get("summary"))
            lines += [f"### `{d.name}`", "", "```java", d.declaration, "```", "", n.get("summary") or PENDING, ""]
            if d.members:
                lines += ["| member | meaning |", "|---|---|"]
                for key, decl in d.members:
                    meaning = meanings.get(key) or (STANDARD.get(key) if d.surface.kind == "enum" else None)
                    members_done += bool(meaning)
                    members_all += 1
                    lines.append(f"| `{decl}` | {_cell(meaning or PENDING)} |")
                lines.append("")
    out = "\n".join(lines).rstrip() + "\n"
    leaked = sorted({x for x in FQCN.findall(out) if x not in allowed and (x in internal or x.replace(".", "$") in internal)})
    if leaked:
        raise ValueError(f"API.md would name internal classes: {', '.join(leaked)}")
    return out, {"types": (types_done, len(docs)), "members": (members_done, members_all)}


def skeleton(docs: list[Doc], packages: list[str]) -> dict:
    want = set(packages)
    out: dict = {"packages": {p: "" for p in packages}, "types": {}}
    for d in docs:
        if _package(d) in want:
            out["types"][d.name] = {"summary": "", "members": {k: "" for k, _ in d.members}}
    return out


def sources() -> tuple[list[Doc], set[str]]:
    """The documented types of the real API plus ``EXTRA_TYPES``, and the class names that must not appear."""
    import _api
    from _support import reference
    from check_spec import internal_libs
    jars = sorted((TASK / "vendor").glob("*.jar"))
    if len(jars) != 1:
        raise SystemExit(f"{TASK / 'vendor'} must hold exactly one jar; found {len(jars)}")
    api: dict[str, bytes] = {}
    for j in _api.api_jars():
        api.update(cf.classes_in_jar(j))
    plugin = cf.classes_in_jar(jars[0])
    docs = document(api) + document({n: plugin[n] for n in plugin if cf.top_level(n) in EXTRA_TYPES},
                                    list(EXTRA_TYPES))
    surface = {d.binary for d in docs}
    internal = (set(reference(jars[0], internal_libs()).all_classes) | set(api)) - surface
    return docs, {dotted(n) for n in internal} | internal


def main() -> int:
    from check_spec import SEED_SPEC, contract_classes
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if spec/API.md is stale")
    ap.add_argument("--skeleton", nargs="+", metavar="PKG", help="print empty notes for these packages")
    args = ap.parse_args()
    docs, internal = sources()
    if args.skeleton:
        print(json.dumps(skeleton(docs, args.skeleton), indent=1))
        return 0
    md, report = build(docs, load_notes(NOTES_DIR), internal=internal,
                       allowed=contract_classes(HERE / "contract-classes.txt"))
    path = SEED_SPEC / "API.md"
    summary = "; ".join(f"{k} {a}/{b} described" for k, (a, b) in report.items())
    if args.check:
        stale = not path.is_file() or path.read_text() != md
        print(f"{'stale' if stale else 'up to date'}: {summary}")
        return 1 if stale else 0
    path.write_text(md)
    print(f"wrote {path}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
