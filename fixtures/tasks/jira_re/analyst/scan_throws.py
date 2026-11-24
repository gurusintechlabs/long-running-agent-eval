#!/usr/bin/env python3
"""Find `throw`s the decompiler dropped (phase JC2; analyst-side, reads analyst-work/ only).

    .venv/bin/python fixtures/tasks/jira_re/analyst/scan_throws.py CLASSES SOURCES [--prefix com/acme]

CLASSES is a directory of class files or a jar; SOURCES the decompiled tree for it (Vineflower, `.java` or
`.kt`). For every top-level class, the exceptions its bytecode constructs and throws (`new T … invokespecial
T.<init>; athrow`, inner classes and lambdas included) are counted by simple name and compared with the
`throw` statements in its source. A class whose bytecode throws more of a type than its source shows is
printed: the decompiled error path there is not to be trusted, so read it with `javap -c -p`. Exceptions
built by a method call (`throw Errors.X.withMessage(...)`, JC5) are counted the same way, by the method's
name, as `name()`. Rethrows, assertions and compiler-made throws (pattern switches, Kotlin `when` and
intrinsics) are not counted. JC1 found four such drops in the public API (docs/phase-JC1-summary.md).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

SYNTHETIC = {"java/lang/AssertionError", "java/lang/MatchException", "java/lang/IncompatibleClassChangeError",
             "java/lang/NoSuchFieldError", "kotlin/NoWhenBranchMatchedException",
             "kotlin/KotlinNothingValueException"}
_HEADER = re.compile(r"^(?:[a-z]+ )*(?:class|interface|enum|@interface|record) ([\w.$]+)")
_INSN = re.compile(r"^\s*\d+: (\w+)(.*)$")
_NEW = re.compile(r"// class ([\w/$]+)")
_INIT = re.compile(r'// Method ([\w/$]+)\."<init>"')
_CALL = re.compile(r"// (?:Interface)?Method (?:([\w/$]+)\.)?\"?([\w$<>]+)\"?:")
_SRC_THROW = re.compile(r"\bthrow\s+(?:new\s+)?((?:[\w$]+\.)*[A-Z][\w$]*)\s*\(")


@dataclass(frozen=True)
class Missing:
    cls: str                  # top-level class, dotted
    exception: str            # simple name
    bytecode: int
    source: int | None        # None: no source file found


def _top(name: str) -> str:
    return name.split("$", 1)[0]


def bytecode_throws(javap: str) -> dict[str, Counter]:
    """Constructed-and-thrown exceptions per top-level class (dotted), from `javap -c -p` output."""
    out: dict[str, Counter] = defaultdict(Counter)
    cls = None
    pending: list[str] = []
    last = None                              # the type constructed by the previous instruction, if any
    called = None                            # the method whose result is on the stack, if any
    for line in javap.splitlines():
        h = _HEADER.match(line)
        if h:
            cls, pending, last, called = _top(h.group(1)), [], None, None
            continue
        m = _INSN.match(line)
        if not m or cls is None:
            continue
        op, rest = m.groups()
        built, last = last, None
        result, called = called, None
        if op == "checkcast":
            called = result
        elif op.startswith("invoke") and (c := _CALL.search(rest)) and c.group(2) != "<init>":
            synthetic = (c.group(1) or "").startswith("kotlin/") or c.group(2).startswith("access$")
            called = None if synthetic else c.group(2)
        if op == "new" and (n := _NEW.search(rest)):
            pending.append(n.group(1))
        elif op == "invokespecial" and (i := _INIT.search(rest)) and pending and pending[-1] == i.group(1):
            last = pending.pop()
        elif op == "athrow" and built and built not in SYNTHETIC:
            out[cls][built.rsplit("/", 1)[-1]] += 1
        elif op == "athrow" and result:
            out[cls][result + "()"] += 1
    return {k: v for k, v in out.items() if v}


def source_throws(text: str) -> Counter:
    """`throw new T(…)` (Java) and `throw T(…)` (Kotlin) per simple name of T."""
    return Counter(re.split(r"[.$]", t)[-1] for t in _SRC_THROW.findall(text))


def _source(root: Path, cls: str) -> Path | None:
    stem = root / cls.replace(".", "/")
    for ext in (".java", ".kt"):
        if (p := stem.with_name(stem.name + ext)).is_file():
            return p
    return None


def compare(found: dict[str, Counter], sources: Path) -> list[Missing]:
    out = []
    for cls in sorted(found):
        p = _source(sources, cls)
        text = p.read_text(errors="replace") if p else ""
        have = source_throws(text)
        for t in found[cls]:
            if t.endswith("()"):
                have[t] = len(re.findall(r"\bthrow\b[^;{}]{0,300}?\b" + re.escape(t[:-2]) + r"\s*\(", text))
        want = Counter()
        for t, n in found[cls].items():
            want[t.rsplit("$", 1)[-1]] += n
        for t, n in sorted(want.items()):
            if p is None or have[t] < n:
                out.append(Missing(cls, t, n, have[t] if p else None))
    return out


def _class_names(classes: Path, prefix: str) -> tuple[list[str], str]:
    """Binary class names under ``classes`` (dir or jar) whose path starts with ``prefix``, and the classpath."""
    if classes.is_dir():
        names = [str(p.relative_to(classes).with_suffix("")) for p in classes.rglob("*.class")]
    else:
        with zipfile.ZipFile(classes) as z:
            names = [n[:-6] for n in z.namelist() if n.endswith(".class")]
    names = [n.replace(os.sep, "/") for n in names if n.startswith(prefix) and "META-INF" not in n]
    return sorted(n.replace("/", ".") for n in names), str(classes)


def javap_text(classes: Path, prefix: str, javap: str) -> str:
    names, cp = _class_names(classes, prefix)
    chunks = []
    for i in range(0, len(names), 200):
        r = subprocess.run([javap, "-c", "-p", "-cp", cp, *names[i:i + 200]], capture_output=True, text=True)
        chunks.append(r.stdout)
    return "\n".join(chunks)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("classes", type=Path, help="directory of class files, or a jar")
    ap.add_argument("sources", type=Path, help="the decompiled source tree for it")
    ap.add_argument("--prefix", default="", help="only classes whose path starts with this (e.g. com/acme)")
    ap.add_argument("--javap", default=str(Path(os.environ.get("LRAE_RE_TOOLS", Path.home() / "lrae-tools/re"))
                                           / "bin" / "javap"))
    args = ap.parse_args()
    found = bytecode_throws(javap_text(args.classes, args.prefix, args.javap))
    missing = compare(found, args.sources)
    for m in missing:
        where = "no source" if m.source is None else f"source {m.source}"
        print(f"{m.cls}: {m.exception} thrown {m.bytecode}x in bytecode, {where}")
    total = sum(sum(c.values()) for c in found.values())
    print(f"{total} constructed throws in {len(found)} classes; {len(missing)} short in the source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
