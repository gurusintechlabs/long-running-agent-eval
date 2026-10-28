"""The binary surface of a public Java API, from class files alone (phase JA1, docs/jira-re-design.md §7.4).

The hidden signature tier compares the rewrite's compiled API with the original's, type by type, the way a
plugin compiled against the original would see it (binary and source compatibility):

* a type: its kind, access, ``abstract``/``final``/``static`` (nested types' flags come from the
  ``InnerClasses`` attribute), superclass, interfaces and generic signature;
* its public and protected members: fields (descriptor, ``static``/``final``, constant value) and methods
  and constructors (erased descriptor, ``static``/``abstract``/``final``/varargs, declared exceptions,
  generic signature).

Synthetic and bridge members are not surface. Generic signatures are compared with their type variables
renamed in order of first appearance, so ``<T>`` and ``<E>`` are the same signature. Pure Python: the
scorer needs no JDK to read a surface (it needs one to build the rewrite).
"""
from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ACC_PUBLIC, ACC_PRIVATE, ACC_PROTECTED, ACC_STATIC, ACC_FINAL = 0x1, 0x2, 0x4, 0x8, 0x10
ACC_BRIDGE, ACC_VARARGS, ACC_INTERFACE, ACC_ABSTRACT = 0x40, 0x80, 0x200, 0x400
ACC_SYNTHETIC, ACC_ANNOTATION, ACC_ENUM = 0x1000, 0x2000, 0x4000

_CP_SIZES = {3: 4, 4: 4, 5: 8, 6: 8, 7: 2, 8: 2, 9: 4, 10: 4, 11: 4, 12: 4, 15: 3, 16: 2, 17: 4, 18: 4,
             19: 2, 20: 2}


# ---------------------------------------------------------------- raw class file

@dataclass
class RawMember:
    access: int
    name: str
    descriptor: str
    attrs: dict[str, bytes]


@dataclass
class RawClass:
    name: str                       # binary name, dotted, with $ for nested types
    access: int
    superclass: str | None
    interfaces: list[str]
    fields: list[RawMember]
    methods: list[RawMember]
    attrs: dict[str, bytes]
    pool: dict[int, tuple[int, object]]

    def utf8(self, idx: int) -> str:
        return str(self.pool[idx][1])

    def class_name(self, idx: int) -> str:
        return self.utf8(int(self.pool[idx][1])).replace("/", ".")


def parse_class(data: bytes) -> RawClass:
    if data[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("not a class file")
    pos = 8
    (count,) = struct.unpack_from(">H", data, pos)
    pos += 2
    pool: dict[int, tuple[int, object]] = {}
    i = 1
    while i < count:
        tag = data[pos]
        pos += 1
        if tag == 1:
            (n,) = struct.unpack_from(">H", data, pos)
            pool[i] = (1, data[pos + 2:pos + 2 + n].decode("utf-8", "replace"))
            pos += 2 + n
        elif tag in _CP_SIZES:
            raw = data[pos:pos + _CP_SIZES[tag]]
            value: object = {3: lambda b: struct.unpack(">i", b)[0], 4: lambda b: struct.unpack(">f", b)[0],
                             5: lambda b: struct.unpack(">q", b)[0], 6: lambda b: struct.unpack(">d", b)[0],
                             7: lambda b: struct.unpack(">H", b)[0], 8: lambda b: struct.unpack(">H", b)[0],
                             }.get(tag, lambda b: b)(raw)
            pool[i] = (tag, value)
            pos += _CP_SIZES[tag]
            if tag in (5, 6):  # long and double take two slots
                i += 1
        else:
            raise ValueError(f"unknown constant pool tag {tag}")
        i += 1

    def utf8(idx: int) -> str:
        return str(pool[idx][1])

    def cls(idx: int) -> str | None:
        return utf8(int(pool[idx][1])).replace("/", ".") if idx else None

    access, this_idx, super_idx = struct.unpack_from(">HHH", data, pos)
    pos += 6
    (n_if,) = struct.unpack_from(">H", data, pos)
    pos += 2
    interfaces = [cls(struct.unpack_from(">H", data, pos + 2 * k)[0]) for k in range(n_if)]
    pos += 2 * n_if

    def attributes(p: int) -> tuple[dict[str, bytes], int]:
        (n,) = struct.unpack_from(">H", data, p)
        p += 2
        out = {}
        for _ in range(n):
            name_idx, length = struct.unpack_from(">HI", data, p)
            out[utf8(name_idx)] = data[p + 6:p + 6 + length]
            p += 6 + length
        return out, p

    def members(p: int) -> tuple[list[RawMember], int]:
        (n,) = struct.unpack_from(">H", data, p)
        p += 2
        out = []
        for _ in range(n):
            acc, name_idx, desc_idx = struct.unpack_from(">HHH", data, p)
            attrs, p = attributes(p + 6)
            out.append(RawMember(acc, utf8(name_idx), utf8(desc_idx), attrs))
        return out, p

    fields, pos = members(pos)
    methods, pos = members(pos)
    attrs, _ = attributes(pos)
    return RawClass(name=cls(this_idx) or "", access=access, superclass=cls(super_idx),
                    interfaces=[i for i in interfaces if i], fields=fields, methods=methods, attrs=attrs, pool=pool)


# ---------------------------------------------------------------- annotations (phase JS2: the REST and AO contract)

@dataclass
class Annotation:
    type: str                       # dotted binary name
    values: dict[str, object]       # str, int, float, bool, enum "Type.CONST", class name, Annotation, list


def _annotation(raw: RawClass, data: bytes, p: int) -> tuple[Annotation, int]:
    type_idx, n = struct.unpack_from(">HH", data, p)
    p += 4
    values = {}
    for _ in range(n):
        (name_idx,) = struct.unpack_from(">H", data, p)
        values[raw.utf8(name_idx)], p = _element_value(raw, data, p + 2)
    return Annotation(_descriptor_class(raw.utf8(type_idx)), values), p


def _element_value(raw: RawClass, data: bytes, p: int) -> tuple[object, int]:
    tag = chr(data[p])
    p += 1
    if tag in "BCDFIJSZs":
        (idx,) = struct.unpack_from(">H", data, p)
        v = raw.pool[idx][1]
        return (bool(v) if tag == "Z" else chr(v) if tag == "C" else v), p + 2
    if tag == "e":
        t, c = struct.unpack_from(">HH", data, p)
        return f"{_descriptor_class(raw.utf8(t))}.{raw.utf8(c)}", p + 4
    if tag == "c":
        (idx,) = struct.unpack_from(">H", data, p)
        return _descriptor_class(raw.utf8(idx)), p + 2
    if tag == "@":
        return _annotation(raw, data, p)
    if tag == "[":
        (n,) = struct.unpack_from(">H", data, p)
        p += 2
        out = []
        for _ in range(n):
            v, p = _element_value(raw, data, p)
            out.append(v)
        return out, p
    raise ValueError(f"unknown element value tag {tag!r}")


def _descriptor_class(desc: str) -> str:
    return desc[1:-1].replace("/", ".") if desc.startswith("L") and desc.endswith(";") else desc


def annotations(raw: RawClass, attrs: dict[str, bytes]) -> list[Annotation]:
    """Runtime-visible annotations of a class, field or method (``attrs`` of ``raw`` or of one of its members)."""
    data = attrs.get("RuntimeVisibleAnnotations")
    if not data:
        return []
    (n,) = struct.unpack_from(">H", data, 0)
    out, p = [], 2
    for _ in range(n):
        a, p = _annotation(raw, data, p)
        out.append(a)
    return out


def parameter_annotations(raw: RawClass, attrs: dict[str, bytes]) -> list[list[Annotation]]:
    """Runtime-visible annotations of each parameter of a method, in order (may be shorter than the descriptor's
    parameter list: javac omits synthetic leading parameters)."""
    data = attrs.get("RuntimeVisibleParameterAnnotations")
    if not data:
        return []
    out, p = [], 1
    for _ in range(data[0]):
        (n,) = struct.unpack_from(">H", data, p)
        p += 2
        one = []
        for _ in range(n):
            a, p = _annotation(raw, data, p)
            one.append(a)
        out.append(one)
    return out


# ---------------------------------------------------------------- generic signatures

def normalise_signature(sig: str | None) -> str | None:
    """``sig`` with every type variable renamed ``V0, V1, ...`` in order of first appearance."""
    if not sig:
        return None
    names: dict[str, str] = {}

    def var(name: str) -> str:
        return names.setdefault(name, f"V{len(names)}")

    out: list[str] = []
    i, n = 0, len(sig)

    def ident(stop: str) -> str:
        nonlocal i
        j = i
        while j < n and sig[j] not in stop:
            j += 1
        s = sig[i:j]
        i = j
        return s

    def ref_type() -> None:
        nonlocal i
        c = sig[i]
        if c == "L":
            out.append("L")
            i += 1
            while True:
                out.append(ident("<;."))
                if sig[i] == "<":
                    out.append("<")
                    i += 1
                    while sig[i] != ">":
                        type_arg()
                    out.append(">")
                    i += 1
                if sig[i] == ".":
                    out.append(".")
                    i += 1
                    continue
                out.append(";")
                i += 1
                return
        if c == "T":
            i += 1
            out.append("T" + var(ident(";")) + ";")
            i += 1
            return
        if c == "[":
            out.append("[")
            i += 1
            java_type()
            return
        raise ValueError(f"bad signature {sig!r} at {i}")

    def type_arg() -> None:
        nonlocal i
        if sig[i] == "*":
            out.append("*")
            i += 1
            return
        if sig[i] in "+-":
            out.append(sig[i])
            i += 1
        ref_type()

    def java_type() -> None:
        nonlocal i
        if sig[i] in "BCDFIJSZV":
            out.append(sig[i])
            i += 1
        else:
            ref_type()

    try:
        if sig[i] == "<":   # formal type parameters
            out.append("<")
            i += 1
            while sig[i] != ">":
                out.append(var(ident(":")))
                while i < n and sig[i] == ":":
                    out.append(":")
                    i += 1
                    if sig[i] != ":":
                        ref_type()
            out.append(">")
            i += 1
        if i < n and sig[i] == "(":   # method
            out.append("(")
            i += 1
            while sig[i] != ")":
                java_type()
            out.append(")")
            i += 1
            java_type()
            while i < n and sig[i] == "^":
                out.append("^")
                i += 1
                ref_type()
        else:                           # class (superclass, then interfaces) or field
            while i < n:
                ref_type()
    except IndexError as exc:
        raise ValueError(f"truncated signature {sig!r}") from exc
    return "".join(out)


# ---------------------------------------------------------------- surface model

_PRIMS = {"B": "byte", "C": "char", "D": "double", "F": "float", "I": "int", "J": "long", "S": "short",
          "Z": "boolean", "V": "void"}


def _java_types(desc: str) -> list[str]:
    out, i = [], 0
    while i < len(desc):
        dims = 0
        while desc[i] == "[":
            dims += 1
            i += 1
        if desc[i] == "L":
            j = desc.index(";", i)
            t = desc[i + 1:j].replace("/", ".")
            i = j + 1
        else:
            t = _PRIMS[desc[i]]
            i += 1
        out.append(t + "[]" * dims)
    return out


def render(name: str, descriptor: str) -> str:
    """A member key as Java would show it: ``foo(long, java.lang.String) -> java.util.List``."""
    if descriptor.startswith("("):
        params, ret = descriptor[1:].split(")", 1)
        shown = "<init>" if name == "<init>" else name
        r = "" if name == "<init>" else f" -> {_java_types(ret)[0]}"
        return f"{shown}({', '.join(_java_types(params))}){r}"
    return f"{name}: {_java_types(descriptor)[0]}"


@dataclass(frozen=True)
class Member:
    kind: str                     # "field" | "method"
    name: str
    descriptor: str
    flags: tuple[str, ...]
    signature: str | None = None
    exceptions: tuple[str, ...] = ()
    constant: object = None

    @property
    def key(self) -> str:
        return f"{self.name}{self.descriptor}" if self.kind == "method" else f"{self.name}:{self.descriptor}"

    @property
    def shown(self) -> str:
        return render(self.name, self.descriptor)


@dataclass
class TypeSurface:
    name: str
    kind: str                     # class | interface | enum | annotation
    flags: tuple[str, ...]
    superclass: str | None
    interfaces: tuple[str, ...]
    signature: str | None
    members: dict[str, Member] = field(default_factory=dict)
    outer: str | None = None      # the enclosing type of a member type


def _access(acc: int) -> str:
    return "public" if acc & ACC_PUBLIC else "protected" if acc & ACC_PROTECTED else \
        "private" if acc & ACC_PRIVATE else "package"


def _sig(attrs: dict[str, bytes], raw: RawClass) -> str | None:
    b = attrs.get("Signature")
    return normalise_signature(raw.utf8(struct.unpack(">H", b)[0])) if b else None


def _inner_flags(raw: RawClass) -> tuple[int | None, str | None]:
    """The class's own entry in its ``InnerClasses`` attribute: (flags, outer type) or (None, None)."""
    b = raw.attrs.get("InnerClasses")
    if not b:
        return None, None
    (n,) = struct.unpack_from(">H", b, 0)
    for k in range(n):
        inner, outer, _name, acc = struct.unpack_from(">HHHH", b, 2 + 8 * k)
        if inner and raw.class_name(inner) == raw.name:
            return acc, (raw.class_name(outer) if outer else None)
    return None, None


def surface_of(raw: RawClass) -> TypeSurface | None:
    """The type's surface, or None when it is not visible to API clients (private, package, local or
    anonymous)."""
    acc, outer = raw.access, None
    inner_acc, outer = _inner_flags(raw)
    if inner_acc is not None:
        if outer is None:          # local or anonymous
            return None
        acc = inner_acc
    if _access(acc) not in ("public", "protected") or acc & ACC_SYNTHETIC:
        return None
    kind = ("annotation" if acc & ACC_ANNOTATION else "interface" if acc & ACC_INTERFACE
            else "enum" if acc & ACC_ENUM else "class")
    flags = [_access(acc)]
    if kind == "class" and acc & ACC_ABSTRACT:
        flags.append("abstract")
    if kind == "class" and acc & ACC_FINAL:
        flags.append("final")
    if inner_acc is not None and acc & ACC_STATIC and kind == "class":
        flags.append("static")
    s = TypeSurface(name=raw.name, kind=kind, flags=tuple(flags),
                    superclass=None if kind in ("interface", "annotation") else raw.superclass,
                    interfaces=tuple(sorted(raw.interfaces)), signature=_sig(raw.attrs, raw), outer=outer)
    interface = kind in ("interface", "annotation")
    for f in raw.fields:
        if _access(f.access) in ("public", "protected") and not f.access & ACC_SYNTHETIC:
            fl = [_access(f.access)] + [w for bit, w in ((ACC_STATIC, "static"), (ACC_FINAL, "final"))
                                        if f.access & bit]
            const = None
            if "ConstantValue" in f.attrs:
                tag, val = raw.pool[struct.unpack(">H", f.attrs["ConstantValue"])[0]]
                const = raw.utf8(int(val)) if tag == 8 else val
            m = Member("field", f.name, f.descriptor, tuple(fl), _sig(f.attrs, raw), constant=const)
            s.members[m.key] = m
    for meth in raw.methods:
        a = meth.access
        if _access(a) not in ("public", "protected") or a & (ACC_SYNTHETIC | ACC_BRIDGE) or meth.name == "<clinit>":
            continue
        fl = [_access(a)] + [w for bit, w in ((ACC_STATIC, "static"), (ACC_ABSTRACT, "abstract"),
                                              (ACC_VARARGS, "varargs")) if a & bit]
        if a & ACC_FINAL and not interface:
            fl.append("final")
        if interface and not a & (ACC_ABSTRACT | ACC_STATIC):
            fl.append("default")
        exc: tuple[str, ...] = ()
        if "Exceptions" in meth.attrs:
            b = meth.attrs["Exceptions"]
            (n,) = struct.unpack_from(">H", b, 0)
            exc = tuple(sorted(raw.class_name(struct.unpack_from(">H", b, 2 + 2 * k)[0]) for k in range(n)))
        m = Member("method", meth.name, meth.descriptor, tuple(sorted(fl)), _sig(meth.attrs, raw), exc)
        s.members[m.key] = m
    return s


def surface_from_classes(classes: dict[str, bytes]) -> dict[str, TypeSurface]:
    """``{binary name: surface}`` of every client-visible type among ``classes`` (name -> class file
    bytes). A member type counts only when every enclosing type is visible too."""
    out: dict[str, TypeSurface] = {}
    for data in classes.values():
        try:
            s = surface_of(parse_class(data))
        except (ValueError, struct.error, IndexError, KeyError):
            continue
        if s is not None:
            out[s.name] = s
    for name in sorted(out, key=len):
        if name in out and out[name].outer is not None and out[name].outer not in out:
            del out[name]
    return out


def classes_in_jar(jar: Path | bytes) -> dict[str, bytes]:
    import io
    src = io.BytesIO(jar) if isinstance(jar, bytes) else jar
    out = {}
    with zipfile.ZipFile(src) as z:
        for n in z.namelist():
            if n.endswith(".class") and not n.startswith("META-INF/") and not n.endswith("module-info.class"):
                out[n[:-6].replace("/", ".")] = z.read(n)
    return out


def classes_in_dir(root: Path) -> dict[str, bytes]:
    root = Path(root)
    return {p.relative_to(root).as_posix()[:-6].replace("/", "."): p.read_bytes()
            for p in sorted(root.rglob("*.class")) if p.is_file() and p.name != "module-info.class"}


def top_level(name: str) -> str:
    pkg, _, simple = name.rpartition(".")
    return f"{pkg}.{simple.split('$', 1)[0]}" if pkg else simple.split("$", 1)[0]


# ---------------------------------------------------------------- comparison

_OBJECT_METHODS = {"toString()Ljava/lang/String;", "hashCode()I", "equals(Ljava/lang/Object;)Z"}


def _inherited(key: str, t: TypeSurface, surface: dict[str, TypeSurface], seen: set[str] | None = None) -> bool:
    """Whether method ``key`` reaches ``t`` from a supertype declared in ``surface`` (or ``Object``)."""
    seen = seen if seen is not None else set()
    if key in _OBJECT_METHODS and t.kind in ("class", "enum"):
        return True
    for sup in [t.superclass, *t.interfaces]:
        if not sup or sup in seen or sup not in surface:
            continue
        seen.add(sup)
        st = surface[sup]
        if key in st.members or _inherited(key, st, surface, seen):
            return True
    return False


def compare_type(want: TypeSurface, got_surface: dict[str, TypeSurface]) -> list[str]:
    """Every way the rewrite's ``want.name`` differs from the original's (empty: compatible)."""
    got = got_surface.get(want.name)
    if got is None:
        return [f"{want.name}: missing ({want.kind}, {' '.join(want.flags)})"]
    problems = []
    for attr in ("kind", "flags", "superclass", "signature"):
        if getattr(want, attr) != getattr(got, attr):
            problems.append(f"{want.name}: {attr} is {getattr(got, attr)!r}, expected {getattr(want, attr)!r}")
    missing_ifaces = sorted(set(want.interfaces) - set(got.interfaces))
    if missing_ifaces:
        problems.append(f"{want.name}: does not implement {', '.join(missing_ifaces)}")
    for key, m in sorted(want.members.items()):
        g = got.members.get(key)
        if g is None:
            if m.kind == "method" and "abstract" not in m.flags and _inherited(key, got, got_surface):
                continue
            problems.append(f"{want.name}: missing {m.kind} {' '.join(m.flags)} {m.shown}")
            continue
        for attr in ("flags", "signature", "exceptions", "constant"):
            if getattr(m, attr) != getattr(g, attr):
                problems.append(f"{want.name}: {m.shown}: {attr} is {getattr(g, attr)!r}, "
                                f"expected {getattr(m, attr)!r}")
    if want.kind in ("interface", "annotation") or "abstract" in want.flags:
        extra = sorted(k for k, g in got.members.items() if "abstract" in g.flags and k not in want.members
                       and not _inherited(k, want, {want.name: want}))
        for k in extra:   # a new abstract method breaks every client implementation
            problems.append(f"{want.name}: extra abstract method {got.members[k].shown}")
    return problems
