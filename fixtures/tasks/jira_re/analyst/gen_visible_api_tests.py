#!/usr/bin/env python3
"""Generate the visible signature sample of the public-API tier (phase JA1, docs/jira-re-design.md §7.4).

    .venv/bin/python fixtures/tasks/jira_re/analyst/gen_visible_api_tests.py [--check]

Writes ``hidden/api/visible/cleanroom/apitests/ApiSignatureSampleTest.java``: for each type in ``SAMPLE``,
one JUnit test that checks, by reflection, that the rewrite declares the type with the original's kind,
access, modifiers, superclass and interfaces, and every public or protected member with the original's
erased descriptor and modifiers (the same surface ``hidden/_classfile.py`` compares; generic signatures and
constant values are checked by the hidden tier only). The names are contract (spec/SPEC.md); the strings
come from the real API jar in ``vendor/api/``. Reflection only, so the file compiles before the API exists.

``prepare_seed.py`` copies ``hidden/api/visible/`` into the seed's ``spec/api-tests/``. ``--check`` writes
nothing and exits 1 if the file is out of date.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HIDDEN = HERE.parent / "hidden"
sys.path.insert(0, str(HIDDEN))

import _api  # noqa: E402

OUT = _api.VISIBLE_TESTS / "cleanroom" / "apitests" / "ApiSignatureSampleTest.java"
PREFIX = "com.almworks.jira.structure.api."
SAMPLE = ["item.ItemIdentity", "item.ItemIdentity$LongIdentity", "item.ItemIdentity$StringIdentity",
          "forest.raw.Forest", "util.ComparableTuple", "error.StructureException", "row.StructureRow"]

HEADER = '''package cleanroom.apitests;

import static org.junit.jupiter.api.Assertions.assertTrue;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Member;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;
import org.junit.jupiter.api.Test;

/**
 * The exact signatures of a sample of public API types, as spec/SPEC.md lists them (generated). The
 * replacement is measured against every public type. Copy this directory into src/test/java; these tests
 * must pass unchanged.
 *
 * Member lines read: kind, modifiers (sorted), then name and JVM descriptor (fields: name:type).
 */
class ApiSignatureSampleTest {

    private static String desc(Class<?> c) {
        if (c.isArray()) {
            return "[" + desc(c.getComponentType());
        }
        if (c.isPrimitive()) {
            return c == void.class ? "V" : c == boolean.class ? "Z" : c == byte.class ? "B" : c == char.class ? "C"
                    : c == short.class ? "S" : c == int.class ? "I" : c == long.class ? "J" : c == float.class ? "F" : "D";
        }
        return "L" + c.getName().replace('.', '/') + ";";
    }

    private static String params(Class<?>[] types) {
        StringBuilder b = new StringBuilder("(");
        for (Class<?> t : types) {
            b.append(desc(t));
        }
        return b.append(")").toString();
    }

    private static String access(int m) {
        return Modifier.isPublic(m) ? "public" : Modifier.isProtected(m) ? "protected" : null;
    }

    private static String line(String kind, Set<String> flags, String key) {
        return kind + " " + String.join(" ", flags) + " " + key;
    }

    private static Set<String> surface(Class<?> c) {
        Set<String> out = new TreeSet<>();
        boolean iface = c.isInterface();
        String kind = c.isAnnotation() ? "annotation" : iface ? "interface" : c.isEnum() ? "enum" : "class";
        Set<String> tf = new TreeSet<>();
        tf.add(String.valueOf(access(c.getModifiers())));
        if (kind.equals("class") && Modifier.isAbstract(c.getModifiers())) {
            tf.add("abstract");
        }
        if (kind.equals("class") && Modifier.isFinal(c.getModifiers())) {
            tf.add("final");
        }
        if (kind.equals("class") && c.getEnclosingClass() != null && Modifier.isStatic(c.getModifiers())) {
            tf.add("static");
        }
        out.add(line("type", tf, kind));
        if (!iface && c.getSuperclass() != null) {
            out.add("extends " + c.getSuperclass().getName());
        }
        for (Class<?> i : c.getInterfaces()) {
            out.add("implements " + i.getName());
        }
        for (Field f : c.getDeclaredFields()) {
            int m = f.getModifiers();
            if (f.isSynthetic() || access(m) == null) {
                continue;
            }
            Set<String> fl = new TreeSet<>();
            fl.add(access(m));
            if (Modifier.isStatic(m)) {
                fl.add("static");
            }
            if (Modifier.isFinal(m)) {
                fl.add("final");
            }
            out.add(line("field", fl, f.getName() + ":" + desc(f.getType())));
        }
        List<Member> callables = new ArrayList<>(Arrays.asList(c.getDeclaredMethods()));
        callables.addAll(Arrays.asList(c.getDeclaredConstructors()));
        for (Member x : callables) {
            int m = x.getModifiers();
            boolean ctor = x instanceof Constructor;
            if (x.isSynthetic() || (!ctor && ((Method) x).isBridge()) || access(m) == null) {
                continue;
            }
            Set<String> fl = new TreeSet<>();
            fl.add(access(m));
            if (Modifier.isStatic(m)) {
                fl.add("static");
            }
            if (Modifier.isAbstract(m)) {
                fl.add("abstract");
            }
            if (ctor ? ((Constructor<?>) x).isVarArgs() : ((Method) x).isVarArgs()) {
                fl.add("varargs");
            }
            if (Modifier.isFinal(m) && !iface) {
                fl.add("final");
            }
            if (iface && !Modifier.isAbstract(m) && !Modifier.isStatic(m)) {
                fl.add("default");
            }
            String key = ctor ? "<init>" + params(((Constructor<?>) x).getParameterTypes()) + "V"
                    : x.getName() + params(((Method) x).getParameterTypes()) + desc(((Method) x).getReturnType());
            out.add(line("method", fl, key));
        }
        return out;
    }

    private static void assertSurface(String type, String... expected) {
        Class<?> c;
        try {
            c = Class.forName(type, false, ApiSignatureSampleTest.class.getClassLoader());
        } catch (ClassNotFoundException e) {
            throw new AssertionError(type + " does not exist");
        }
        Set<String> got = surface(c);
        List<String> missing = new ArrayList<>();
        for (String e : expected) {
            if (!got.contains(e)) {
                missing.add(e);
            }
        }
        assertTrue(missing.isEmpty(), type + ": missing or different:\\n  " + String.join("\\n  ", missing));
    }
'''


def _java_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def expected_lines(t) -> list[str]:
    out = [f"type {' '.join(sorted(t.flags))} {t.kind}"]
    if t.superclass:
        out.append(f"extends {t.superclass}")
    out += [f"implements {i}" for i in t.interfaces]
    out += [f"{m.kind} {' '.join(sorted(m.flags))} {m.key}" for m in t.members.values()]
    return sorted(out)


def render() -> str:
    ref = _api.reference_surface()
    if not ref:
        raise SystemExit(f"no public API jar in {_api.VENDOR_API} (run prepare_seed.py)")
    parts = [HEADER]
    for name in SAMPLE:
        fq = PREFIX + name
        if fq not in ref:
            raise SystemExit(f"{fq} is not a public type of the API")
        simple = name.rsplit(".", 1)[-1].replace("$", "")
        lines = ",\n".join(f"                {_java_string(x)}" for x in expected_lines(ref[fq]))
        parts.append(f"""
    @Test
    void {simple[0].lower() + simple[1:]}() {{
        assertSurface({_java_string(fq)},
{lines});
    }}
""")
    parts.append("}\n")
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = render()
    current = OUT.is_file() and OUT.read_text() == text
    if args.check:
        print("up to date" if current else f"out of date: {OUT}")
        return 0 if current else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {OUT} ({len(SAMPLE)} types)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
