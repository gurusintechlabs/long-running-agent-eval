#!/usr/bin/env python3
"""Write the seed's ``spec/inventory.json`` (and the module index of ``spec/INVENTORY.md``) from the original
descriptor plus the analyst's notes.

    .venv/bin/python fixtures/tasks/jira_re/analyst/build_inventory.py [--check]

Two inputs, so later sessions can correct a purpose without retyping the contract:

* the original ``atlassian-plugin.xml`` (inside the jar in ``vendor/``): key, type, display name and the
  externally visible attributes of every module, taken from the declaration that applies to the pinned
  Jira version (``<restrict>`` ranges);
* ``analyst/inventory-notes.json`` (harness-side, written by the analyst): per module key a ``purpose``,
  ``group``, ``related`` keys and ``confidence``; ``contract`` facts checked in the code that the descriptor
  does not carry (merged into the module's contract, e.g. Active Objects table names); ``contract_notes``
  that may name classes and so stay out of ``spec/``; and the ``groups`` legend.

Clean-room hygiene: a descriptor value (or display name) that names a class of the jar, dotted or by its
CamelCase simple name, is dropped unless ``analyst/contract-classes.txt`` lists it. ``--check`` exits 1 when the written file is stale.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK / "hidden"))
sys.path.insert(0, str(HERE))

from _contract import _ancestry, applies, jar_classes  # noqa: E402,F401  (shared with build_contract and check_spec)
from _support import NON_MODULES, reference  # noqa: E402
from check_spec import (CAMEL, SEED_SPEC, _internal_simple_names, contract_classes, internal_libs,  # noqa: E402
                        product_name_phrases, with_product_word)

# module attributes that are internal or carried elsewhere
SKIP_ATTRS = {"key", "class", "name", "i18n-name-key"}
# child elements whose text is externally visible (URLs, contexts, other modules' keys, exported services)
TEXT_CHILDREN = {"url-pattern": "url_patterns", "context": "contexts", "dependency": "dependencies",
                 "interface": "exports", "fname": "fname", "valid-customfield-type": "valid_customfield_types"}


def action_commands(classes: dict[str, bytes], name: str) -> list[str]:
    """Webwork runs `<alias>!x.jspa` through any public no-argument `doX()` returning a String, whether or not
    the descriptor declares a `<command>` and wherever in the class hierarchy it sits. `doExecute` is the plain
    URL, not a command."""
    found = {m.name[2].lower() + m.name[3:] for raw in _ancestry(classes, name) for m in raw.methods
             if m.access & 0x0001 and m.descriptor == "()Ljava/lang/String;"
             and re.fullmatch(r"do[A-Z]\w*", m.name) and m.name != "doExecute"}
    return sorted(found)


def contract_of(el: ET.Element, labels: dict[str, str], hidden, classes: dict[str, bytes] | None = None) -> dict:
    """The externally visible parts of one module declaration; ``hidden(value)`` drops internal names."""
    c: dict = {}
    for a, v in el.attrib.items():
        if a not in SKIP_ATTRS and not hidden(v):
            c[a.replace("-", "_")] = v
    for child in el.iter():
        field = TEXT_CHILDREN.get(child.tag)
        text = (child.text or "").strip()
        if field and text and not hidden(text):
            if field == "exports" and el.get("public") != "true":
                continue
            c.setdefault(field, [])
            if text not in c[field]:
                c[field].append(text)
        if child.tag == "label":
            k = child.get("key")
            if k in labels:
                c["label"] = labels[k]
    actions = []
    for a in el.iter("action"):
        if a.get("alias"):
            declared = [cmd.get("name") for cmd in a.findall("command") if cmd.get("name")]
            found = action_commands(classes or {}, a.get("name"))
            actions.append({"alias": a.get("alias"), "commands": declared + [c for c in found if c not in declared]})
    if actions:
        c["actions"] = actions
    if el.findall("restrict"):
        c["declared_per_jira_range"] = True
    return c


def build(jar: Path, notes: dict, contract: set[str], jira: str, labels: dict[str, str],
          libs: list[str] = ()) -> dict:
    ref = reference(jar, libs)
    internal = _internal_simple_names(ref.all_classes, contract)
    brand = product_name_phrases(HERE / "product-name-phrases.txt")
    classes = jar_classes(jar, libs)

    def hidden(v: str) -> bool:
        return (any(ref.resolve(n) for n in re.findall(r"[\w$.]+", v) if "." in n and n not in contract)
                or bool(set(CAMEL.findall(v)) & internal))

    with zipfile.ZipFile(jar) as z:
        root = ET.fromstring(z.read("atlassian-plugin.xml"))
    decls: dict[str, ET.Element] = {}
    for el in root:
        k = el.get("key")
        if not k or el.tag in NON_MODULES:
            continue
        if k not in decls or (applies(el, jira) and not applies(decls[k], jira)):
            decls[k] = el
    info = root.find("plugin-info")
    modules = []
    for m in ref.modules:
        el = decls[m.key]
        n = notes.get("modules", {}).get(m.key, {})
        cls = el.get("class") if el.get("class") in contract else None
        for child in ("condition-class", "validator-class"):
            t = (el.findtext(child) or "").strip()
            if t in contract:
                cls = t
        name = None if m.element == "component" else el.get("name")   # components' names are internal labels
        modules.append({
            "key": m.key, "type": m.element,
            "name": None if name is None or hidden(name) else with_product_word(name, brand), "class": cls,
            "group": n.get("group"), "purpose": n.get("purpose"), "related": n.get("related", []),
            "confidence": n.get("confidence"),
            "contract": json.loads(with_product_word(json.dumps({**contract_of(el, labels, hidden, classes),
                                                                 **n.get("contract", {})}), brand)),
        })
    return {
        "plugin": {"key": root.get("key"), "name": root.get("name"),
                   "plugins_version": root.get("plugins-version"),
                   "version": (info.findtext("version") or "").strip() if info is not None else None,
                   "jira_version": jira, "modules": len(modules)},
        "groups": notes.get("groups", {}),
        "modules": modules,
    }


INDEX = re.compile(r"(<!-- index:start -->\n).*?(<!-- index:end -->)", re.S)


def splice_index(md: str, inv: dict) -> str:
    """Replace the module index of INVENTORY.md (between its markers) with one list per group, in the
    order of the groups legend, keys sorted."""
    if not INDEX.search(md):
        raise ValueError("INVENTORY.md has no <!-- index:start --> ... <!-- index:end --> markers")
    lines = []
    for g, legend in inv["groups"].items():
        mods = sorted((m for m in inv["modules"] if m.get("group") == g), key=lambda m: m["key"])
        if mods:
            lines += [f"**{g}** ({len(mods)}): {legend}.", "",
                      ", ".join(f"`{m['key']}` ({m['type']})" for m in mods), ""]
    return INDEX.sub(lambda m: m.group(1) + "\n".join(lines) + m.group(2), md, count=1)


def i18n_labels(jar: Path) -> dict[str, str]:
    with zipfile.ZipFile(jar) as z:
        names = [n for n in z.namelist() if n.endswith("StructureMessages.properties") or
                 re.fullmatch(r"i18n/[^/_]+\.properties", n)]
        out: dict[str, str] = {}
        for n in names:
            for line in z.read(n).decode("latin-1").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    out.setdefault(k.strip(), v.strip())
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if spec/inventory.json is stale")
    args = ap.parse_args()
    jars = sorted((TASK / "vendor").glob("*.jar"))
    if len(jars) != 1:
        raise SystemExit(f"{TASK / 'vendor'} must hold exactly one jar; found {len(jars)}")
    pom = (TASK.parents[1] / "seed_jira_re" / "pom.xml").read_text()
    jira = re.search(r"<jira\.version>([^<]+)</jira\.version>", pom).group(1)
    notes = json.loads((HERE / "inventory-notes.json").read_text())
    inv = build(jars[0], notes, contract_classes(HERE / "contract-classes.txt"), jira, i18n_labels(jars[0]),
                internal_libs())
    want = {SEED_SPEC / "inventory.json": json.dumps(inv, indent=1, ensure_ascii=False) + "\n",
            SEED_SPEC / "INVENTORY.md": splice_index((SEED_SPEC / "INVENTORY.md").read_text(), inv)}
    if args.check:
        stale = [p.name for p, text in want.items() if not p.is_file() or p.read_text() != text]
        print(f"stale: {', '.join(stale)}" if stale else "up to date")
        return 1 if stale else 0
    for p, text in want.items():
        p.write_text(text)
    out = SEED_SPEC / "inventory.json"
    missing = [m["key"] for m in inv["modules"] if not m["purpose"]]
    print(f"wrote {out}: {len(inv['modules'])} modules, {len(missing)} without a purpose")
    return 0


if __name__ == "__main__":
    sys.exit(main())
