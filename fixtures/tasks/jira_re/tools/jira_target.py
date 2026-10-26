"""Resolve the build target of the jira-re rewrite (docs/jira-re-design.md §4).

The rewrite is a real Jira Data Center plugin that must build offline, so the Jira version, the AMPS
version and the Java release have to be pinned before a run. Each comes from ``target.yaml`` when it is
set there, otherwise from the Maven ``pom.xml`` that Atlassian plugin builds embed in the jar
(``META-INF/maven/<group>/<artifact>/pom.xml``), otherwise from the defaults below (by Jira major).

The embedded pom also lists the original's dependencies. Their non-test entries are primed into the
offline repository (``prime_maven_repo.py``), so the rewrite can compile against the same APIs. The
vendor's own modules (same organisation as the plugin, usually bundled inside the jar and published
nowhere) are not: they are part of what the clean room rewrites.

A jar can embed several poms (one per module it bundles); the plugin's own is the one with
``atlassian-plugin`` packaging, else the one whose coordinates match the plugin key, else the one that
sets Jira properties.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TASK = Path(__file__).resolve().parents[1]
REPO = TASK.parents[2]
SEED = REPO / "fixtures" / "seed_jira_re"
TARGET = TASK / "target.yaml"
PLACEHOLDER = "REPLACE_WITH_PLUGIN.jar"

# By Jira major, when neither target.yaml nor the embedded pom says (community-reported pairings:
# AMPS 8.x for Jira 9, AMPS 9.x for Jira 10+ / Platform 7). Override in target.yaml when needed.
DEFAULTS = {9: {"amps": "8.17.7", "java": "11"}, 10: {"amps": "9.14.0", "java": "17"},
            11: {"amps": "9.14.0", "java": "17"}}

_PROP = re.compile(r"\$\{([^}]+)\}")


@dataclass
class Dep:
    group: str
    artifact: str
    version: str
    scope: str = "compile"
    type: str = "jar"

    @property
    def coords(self) -> str:
        return f"{self.group}:{self.artifact}:{self.version}"


@dataclass
class Target:
    jar: Path
    jira_version: str
    amps_version: str
    java_release: str
    sources: dict[str, str]                 # field -> where its value came from
    original_deps: list[Dep] = field(default_factory=list)
    skipped_deps: list[str] = field(default_factory=list)   # unresolvable versions, not primed
    plugin_key: str | None = None
    pom_name: str | None = None                              # the embedded pom used, if any
    vendor_deps: list[str] = field(default_factory=list)    # the vendor's own modules, not primed
    exclusions: list[str] = field(default_factory=list)     # group:artifact no repository serves


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _child_text(el: ET.Element | None, name: str) -> str | None:
    if el is None:
        return None
    for c in el:
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return None


def embedded_pom(jar: Path, key: str | None = None) -> tuple[str | None, ET.Element | None]:
    """The plugin's own embedded pom (see the module docstring) as ``(entry name, root)``."""
    with zipfile.ZipFile(jar) as z:
        names = sorted(n for n in z.namelist() if n.startswith("META-INF/maven/") and n.endswith("/pom.xml"))
        best: tuple[int, str, ET.Element] | None = None
        for n in names:
            try:
                root = ET.fromstring(z.read(n))
            except ET.ParseError:
                continue
            g, a = _child_text(root, "groupId") or "", _child_text(root, "artifactId") or ""
            props = pom_properties(root)
            score = (4 * (_child_text(root, "packaging") == "atlassian-plugin")
                     + 2 * (bool(key) and key in (g, f"{g}.{a}"))
                     + any(k.startswith("jira.") for k in props))
            if best is None or score > best[0]:
                best = (score, n, root)
        return (best[1], best[2]) if best else (None, None)


def pom_properties(pom: ET.Element) -> dict[str, str]:
    props: dict[str, str] = {}
    for el in pom:
        if _local(el.tag) == "properties":
            props.update({_local(p.tag): (p.text or "").strip() for p in el})
    for name in ("groupId", "artifactId", "version"):
        v = _child_text(pom, name) or _child_text(next((e for e in pom if _local(e.tag) == "parent"), None), name)
        if v:
            props[f"project.{name}"] = v
    return props


def interpolate(value: str | None, props: dict[str, str]) -> str | None:
    """Expand ``${name}`` from ``props`` (a few rounds); None if anything stays unresolved."""
    if value is None:
        return None
    for _ in range(5):
        new = _PROP.sub(lambda m: props.get(m.group(1), m.group(0)), value)
        if new == value:
            break
        value = new
    return None if _PROP.search(value) else value


def vendor_prefix(pom: ET.Element) -> str | None:
    """The vendor's organisation: the first two segments of the plugin's groupId (``com.almworks``)."""
    g = _child_text(pom, "groupId") or ""
    parts = g.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else (g or None)


def pom_dependencies(pom: ET.Element, props: dict[str, str]) -> tuple[list[Dep], list[str]]:
    deps, skipped = [], []
    for sec in pom:
        if _local(sec.tag) != "dependencies":
            continue
        for d in sec:
            g, a = _child_text(d, "groupId"), _child_text(d, "artifactId")
            v = interpolate(_child_text(d, "version"), props)
            scope = _child_text(d, "scope") or "compile"
            typ = _child_text(d, "type") or "jar"
            if not g or not a or scope == "test":
                continue
            if not v:
                skipped.append(f"{g}:{a} (version {_child_text(d, 'version')!r} not resolvable here)")
                continue
            deps.append(Dep(g, a, v, scope, typ))
    return deps, skipped


def plugin_key(jar: Path) -> str | None:
    with zipfile.ZipFile(jar) as z:
        if "atlassian-plugin.xml" not in z.namelist():
            return None
        return ET.fromstring(z.read("atlassian-plugin.xml")).get("key")


def load(target_file: Path = TARGET, seed: Path = SEED) -> Target:
    cfg = yaml.safe_load(target_file.read_text()) or {}
    name = str(cfg.get("jar") or "")
    if not name or name == PLACEHOLDER or "/" in name:
        raise SystemExit(f"set 'jar:' in {target_file} to the jar's file name")
    jar = seed / "vendor" / name
    if not jar.is_file():
        raise SystemExit(f"{jar} does not exist")

    key = plugin_key(jar)
    pom_name, pom = embedded_pom(jar, key)
    props = pom_properties(pom) if pom is not None else {}
    sources: dict[str, str] = {}

    def pick(key: str, pom_keys: tuple[str, ...]) -> str | None:
        v = str(cfg.get(key) or "auto")
        if v != "auto":
            sources[key] = "target.yaml"
            return v
        for k in pom_keys:
            got = interpolate(props.get(k), props)
            if got:
                sources[key] = f"embedded pom ({k})"
                return got
        return None

    jira = pick("jira_version", ("jira.version", "jira.compile.version", "jira.data.version", "product.version"))
    if not jira:
        raise SystemExit("cannot tell the plugin's Jira version: the jar has no embedded pom with jira.version. "
                         f"Set 'jira_version:' in {target_file} (e.g. 10.3.26).")
    major = int(jira.split(".", 1)[0])
    default = DEFAULTS.get(major) or DEFAULTS[max(DEFAULTS)]
    amps = pick("amps_version", ("amps.version",))
    if not amps:
        amps, sources["amps_version"] = default["amps"], f"default for Jira {major}"
    java = pick("java_release", ("maven.compiler.release", "maven.compiler.target", "java.version", "jdkLevel"))
    if not java:
        java, sources["java_release"] = default["java"], f"default for Jira {major}"
    java = java.removeprefix("1.") if java.startswith("1.") else java

    deps, skipped = pom_dependencies(pom, props) if pom is not None else ([], [])
    vendor = vendor_prefix(pom) if pom is not None else None
    own = [d for d in deps if vendor and (d.group == vendor or d.group.startswith(vendor + "."))]
    return Target(jar=jar, jira_version=jira, amps_version=amps, java_release=java, sources=sources,
                  original_deps=[d for d in deps if d not in own], skipped_deps=skipped, plugin_key=key,
                  pom_name=pom_name, vendor_deps=[d.coords for d in own],
                  exclusions=sorted({str(x) for x in cfg.get("maven_exclusions") or []}))


def render_seed_pom(text: str, t: Target) -> str:
    """Pin the three version properties of the seed's pom.xml (each line carries a pinned marker)."""
    for prop, value in (("jira.version", t.jira_version), ("amps.version", t.amps_version),
                        ("maven.compiler.release", t.java_release)):
        pat = re.compile(rf"(<{re.escape(prop)}>)[^<]*(</{re.escape(prop)}>)")
        if not pat.search(text):
            raise SystemExit(f"seed pom.xml has no <{prop}> property")
        text = pat.sub(lambda m, v=value: f"{m.group(1)}{v}{m.group(2)}", text, count=1)
    return _render_exclusions(text, t.exclusions)


_EXCL = re.compile(r"(<!-- pinned exclusions:.*?-->\s*<exclusions>)(.*?)(\n(\s*)</exclusions>)", re.S)


def exclusions_xml(exclusions: list[str], indent: str) -> str:
    out = ""
    for ga in exclusions:
        g, a = ga.split(":", 1)
        out += (f"\n{indent}    <exclusion>\n{indent}        <groupId>{g}</groupId>\n"
                f"{indent}        <artifactId>{a}</artifactId>\n{indent}    </exclusion>")
    return out


def _render_exclusions(text: str, exclusions: list[str]) -> str:
    """Pin ``exclusions`` (``group:artifact``) into the marked ``<exclusions>`` of the seed's jira-api."""
    m = _EXCL.search(text)
    if not m:
        raise SystemExit("seed pom.xml has no pinned <exclusions> block on jira-api")
    return text[:m.start(2)] + exclusions_xml(exclusions, m.group(4)) + text[m.end(2):]
