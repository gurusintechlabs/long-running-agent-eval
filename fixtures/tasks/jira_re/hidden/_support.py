"""Shared helpers of the jira-re hidden suite (docs/jira-re-design.md §6).

The suite knows nothing about what the plugin does. Its reference is built from the jar alone, in pure
Python (no JDK needed by the scorer):

* every class in the jar, and the methods each one declares (parsed from the class files);
* the modules of ``atlassian-plugin.xml`` (element, ``key``, ``class``).

Tests are parametrised over that reference, so P(t) at a checkpoint is the share of the plugin the
agent's artefacts cover, and the grounding tests fail on any evidence reference that does not exist in
the jar. Behaviour tests (does the rewrite do what the plugin does) are a later tier, written after the
pilot (§6.3).

Environment (from ``scorer.yaml``):
  LRAE_WORKSPACE  the snapshot copy under test
  LRAE_STAGE      the stage in force; unset = the final stage
"""
from __future__ import annotations

import functools
import json
import os
import struct
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

FINAL_STAGE = 6
WS = Path(os.environ.get("LRAE_WORKSPACE", ".")).resolve()

# Descriptor elements that are metadata, not functional modules.
NON_MODULES = {"plugin-info", "resource", "component-import", "web-resource-transformer",
               "plugin-name", "description", "version", "vendor", "param", "permissions"}


def current_stage() -> int:
    raw = os.environ.get("LRAE_STAGE", "").strip()
    return int(raw) if raw else FINAL_STAGE


def stage(introduced: int, retired: int | None = None):
    """Active for ``introduced <= stage < retired`` (``retired=None``: forever)."""
    if not 0 <= introduced <= FINAL_STAGE or (retired is not None and not introduced < retired <= FINAL_STAGE):
        raise ValueError(f"bad stage window [{introduced}, {retired})")
    s = current_stage()
    active = introduced <= s and (retired is None or s < retired)
    return pytest.mark.skipif(not active, reason=f"stage window [{introduced}, {retired}) not active at {s}")


# ---------------------------------------------------------------- class files

_CP_SIZES = {3: 4, 4: 4, 5: 8, 6: 8, 7: 2, 8: 2, 9: 4, 10: 4, 11: 4, 12: 4, 15: 3, 16: 2, 17: 4, 18: 4,
             19: 2, 20: 2}


def class_methods(data: bytes) -> set[str]:
    """Names of the methods a class file declares (constructors appear as ``<init>``)."""
    if data[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("not a class file")
    pos = 8
    (count,) = struct.unpack_from(">H", data, pos)
    pos += 2
    utf8: dict[int, str] = {}
    i = 1
    while i < count:
        tag = data[pos]
        pos += 1
        if tag == 1:
            (n,) = struct.unpack_from(">H", data, pos)
            utf8[i] = data[pos + 2:pos + 2 + n].decode("utf-8", "replace")
            pos += 2 + n
        elif tag in _CP_SIZES:
            pos += _CP_SIZES[tag]
            if tag in (5, 6):  # long and double take two slots
                i += 1
        else:
            raise ValueError(f"unknown constant pool tag {tag}")
        i += 1
    pos += 6  # access_flags, this_class, super_class
    (n_if,) = struct.unpack_from(">H", data, pos)
    pos += 2 + 2 * n_if

    def members(p: int) -> tuple[list[str], int]:
        (n,) = struct.unpack_from(">H", data, p)
        p += 2
        names = []
        for _ in range(n):
            _, name_idx, _, n_attr = struct.unpack_from(">HHHH", data, p)
            names.append(utf8.get(name_idx, ""))
            p += 8
            for _ in range(n_attr):
                (length,) = struct.unpack_from(">I", data, p + 2)
                p += 6 + length
        return names, p

    _, pos = members(pos)        # fields
    methods, _ = members(pos)
    return set(methods)


# ---------------------------------------------------------------- reference inventory

@dataclass
class Module:
    key: str
    element: str
    cls: str | None


@dataclass
class Reference:
    all_classes: dict[str, set[str]] = field(default_factory=dict)   # fq name ($ for inner) -> methods
    modules: list[Module] = field(default_factory=list)
    descriptor_found: bool = False

    @property
    def classes(self) -> list[str]:
        return sorted(c for c in self.all_classes if "$" not in c.rsplit(".", 1)[-1])

    def resolve(self, ref: str) -> bool:
        """``fq.Class`` or ``fq.Class#method``; inner classes as ``Outer$Inner`` or ``Outer.Inner``."""
        if not isinstance(ref, str) or not ref.strip():
            return False
        cls, _, method = ref.strip().partition("#")
        method = method.split("(", 1)[0].strip()
        candidates = [cls]
        parts = cls.split(".")
        for k in range(len(parts) - 1, 0, -1):  # Outer.Inner -> Outer$Inner
            candidates.append(".".join(parts[:k]) + "$" + "$".join(parts[k:]))
        for c in candidates:
            if c in self.all_classes:
                if not method:
                    return True
                if method in self.all_classes[c] or (method == c.rsplit(".", 1)[-1].rsplit("$", 1)[-1]
                                                     and "<init>" in self.all_classes[c]):
                    return True
        return False


def reference(jar: Path) -> Reference:
    ref = Reference()
    with zipfile.ZipFile(jar) as z:
        for info in z.infolist():
            n = info.filename
            if not n.endswith(".class") or n.startswith("META-INF/") or n.endswith("module-info.class"):
                continue
            name = n[:-6].replace("/", ".")
            try:
                ref.all_classes[name] = class_methods(z.read(info))
            except (ValueError, struct.error, IndexError):
                ref.all_classes[name] = set()
        if "atlassian-plugin.xml" in z.namelist():
            ref.descriptor_found = True
            root = ET.fromstring(z.read("atlassian-plugin.xml"))
            for el in root:
                tag = el.tag.split("}", 1)[-1] if isinstance(el.tag, str) else ""
                key = el.get("key")
                if tag and key and tag not in NON_MODULES:
                    ref.modules.append(Module(key=key, element=tag, cls=el.get("class")))
    return ref


def target_jar() -> Path | None:
    jars = sorted((WS / "vendor").glob("*.jar"))
    return jars[0] if len(jars) == 1 else None


@functools.lru_cache(maxsize=1)
def workspace_reference() -> Reference | None:
    jar = target_jar()
    return reference(jar) if jar else None


def module_keys() -> list[str]:
    """Collection-time parameters; a placeholder id keeps the test visible when there is nothing to list."""
    ref = workspace_reference()
    return [m.key for m in ref.modules] if ref and ref.modules else ["<no-modules>"]


# ---------------------------------------------------------------- the agent's artefacts

class ArtefactError(AssertionError):
    pass


def load_json(rel: str):
    p = WS / rel
    if not p.is_file():
        raise ArtefactError(f"{rel} is missing")
    try:
        return json.loads(p.read_text())
    except ValueError as exc:
        raise ArtefactError(f"{rel} is not valid JSON: {exc}") from exc


def load_jsonl(rel: str) -> list[dict]:
    p = WS / rel
    if not p.is_file():
        raise ArtefactError(f"{rel} is missing")
    rows = []
    for n, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ArtefactError(f"{rel}:{n} is not valid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ArtefactError(f"{rel}:{n} is not an object")
        rows.append(row)
    return rows


def active_claims() -> list[dict]:
    return [c for c in load_jsonl("analysis/claims.jsonl") if c.get("status", "active") == "active"]


def need_reference() -> Reference:
    ref = workspace_reference()
    if ref is None:
        pytest.fail("vendor/ must hold exactly one jar (the plugin under study)")
    return ref


def need_module(key: str) -> Module:
    ref = need_reference()
    if key == "<no-modules>":
        pytest.skip("the jar has no atlassian-plugin.xml modules")
    return next(m for m in ref.modules if m.key == key)
