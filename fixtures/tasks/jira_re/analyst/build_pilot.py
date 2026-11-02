#!/usr/bin/env python3
"""Generate the pilot's scope from the finished spec (owner decision 2026-11-01, docs/jira-re-design.md §8).

    .venv/bin/python fixtures/tasks/jira_re/analyst/build_pilot.py [--check]

The scope is the modules of ``GROUPS`` plus ``EXTRA_MODULES``, and the API claims the API tests are mapped to
(``api-test-claims.json``), so the independent API tests stay meaningful. Writes ``hidden/pilot.json`` for the
hidden suite, and ``spec/PILOT.md`` and ``spec/pilot-claims.jsonl`` for the implementer. ``--check`` exits 1 when
any of them is stale.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
SPEC = TASK.parents[1] / "seed_jira_re" / "spec"
HIDDEN = TASK / "hidden" / "pilot.json"
GROUPS = ("core-model", "persistence", "permissions-security")   # what the rest of the plugin stands on
EXTRA_MODULES = ("structure-info",)                              # a small UI, so the pilot tests the browser path

INTRO = """# The pilot's scope

This project is a pilot: it covers only part of the specification, listed here. `spec/` describes the whole
plugin, and at about 5 MB it is far too large to read at once. Read this file, then `pilot-claims.jsonl`, and
search the other files for what you need.

- **In scope:** the {modules} modules below and their claims, and the {api} API claims at the end, which are
  {claims} claims in all. They are all in `pilot-claims.jsonl`, copied unchanged from `claims.jsonl`.
- **Still whole:** the skeleton of stage 1. Every module of `inventory.json` is declared and every type of the
  public Java API exists with its exact signatures, in scope or not.
- **Out of scope:** the behaviour of every other module and API type. Where a module in scope needs one of those,
  give it the smallest stub that lets you build and test, and leave that module `not_started` in
  `analysis/rewrite_map.json`. Do not implement it.
- **A claim that depends on something out of scope** is still in scope: test it against a stand-in for that part.

## Modules

| group | module | type | claims |
|---|---|---|---|
"""


def outputs() -> dict[Path, str]:
    claims = [json.loads(x) for x in (SPEC / "claims.jsonl").read_text().splitlines() if x.strip()]
    inv = json.loads((SPEC / "inventory.json").read_text())
    modules = [m for m in (inv if isinstance(inv, list) else inv["modules"])
               if m.get("group") in GROUPS or m["key"] in EXTRA_MODULES]
    keys = {m["key"] for m in modules}
    mapped = {c for ids in json.loads((HERE / "api-test-claims.json").read_text()).values() for c in ids}
    active = [c for c in claims if c["status"] == "active"]
    scope = [c for c in active if c.get("module") in keys or (c.get("api") and c["id"] in mapped)]
    api = [c["id"] for c in scope if c.get("api")]
    per = collections.Counter(c.get("module") for c in scope)
    modules.sort(key=lambda m: (m["key"] in EXTRA_MODULES, m.get("group") or "", m["key"]))
    md = INTRO.format(modules=len(modules), api=len(api), claims=len(scope))
    md += "".join(f"| {m.get('group')} | `{m['key']}` | {m['type']} | {per[m['key']]} |\n" for m in modules)
    md += "\n## API claims\n\n" + ", ".join(api) + "\n"
    return {HIDDEN: json.dumps({"modules": sorted(keys), "api_claims": api}, indent=1) + "\n",
            SPEC / "PILOT.md": md,
            SPEC / "pilot-claims.jsonl": "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in scope)}


def stale() -> list[str]:
    return [p.name for p, text in outputs().items() if not p.is_file() or p.read_text() != text]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if a generated file is stale")
    args = ap.parse_args()
    if args.check:
        out = stale()
        print(f"out of date: {out}" if out else "up to date")
        return 1 if out else 0
    for path, text in outputs().items():
        path.write_text(text)
    pilot = json.loads(HIDDEN.read_text())
    print(f"wrote the pilot: {len(pilot['modules'])} modules, {len(pilot['api_claims'])} API claims")
    return 0


if __name__ == "__main__":
    sys.exit(main())
