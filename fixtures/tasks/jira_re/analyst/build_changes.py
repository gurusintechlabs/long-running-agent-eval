#!/usr/bin/env python3
"""Generate the stage-5 change request from ``analyst/changes-1.json`` (owner decision 2026-11-02).

    .venv/bin/python fixtures/tasks/jira_re/analyst/build_changes.py [--check]

Writes ``analyst/spec-changes-1.md`` (committed as ``spec/CHANGES-1.md`` at stage 5) and ``hidden/changes-1.json``
for hidden t09. A change replaces active pilot claims of the same module with new claims, given in full. New ids
start at C-9001, well above what ``build_claims.py`` hands out; they stay out of ``claims.jsonl`` and
``claim-ids.json``, since the implementer must not see them before stage 5. A new claim's evidence is that of the
claim it replaces (``claims-evidence.jsonl``). ``--check`` exits 1 when an output is stale or an entry is invalid.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
SPEC = TASK.parents[1] / "seed_jira_re" / "spec"
SOURCE = HERE / "changes-1.json"
MD = HERE / "spec-changes-1.md"
HIDDEN = TASK / "hidden" / "changes-1.json"
FIRST_ID = 9001

INTRO = """# Specification corrections: change request 1

These corrections were decided by the product owner after the analyst's review of the suspected bugs. Each change
replaces claims of `spec/claims.jsonl`. A replaced claim stops being contract, and the new claim, given here in full,
takes its place under a permanent id of its own.

- The behaviour below deliberately differs from the original.
- Where this file differs from `SPEC.md`, `API.md` or `claims.jsonl`, this file wins.
- Claims not named here are unchanged. That includes every other claim with `"suspected_bug": true`: they stay contract,
  as stated.
- No REST path, payload, stored format or public signature changes.
"""


def load() -> dict:
    return json.loads(SOURCE.read_text())


def _new_claims(doc: dict) -> list[dict]:
    return [c for change in doc["changes"] for c in change["claims"]]


def _spec_claims() -> dict[str, dict]:
    rows = (json.loads(x) for x in (SPEC / "claims.jsonl").read_text().splitlines() if x.strip())
    return {c["id"]: c for c in rows}


def _pilot_modules() -> set[str]:
    return set(json.loads((TASK / "hidden" / "pilot.json").read_text())["modules"])


def problems(doc: dict, *, claims: dict[str, dict] | None = None, pilot: set[str] | None = None) -> list[str]:
    claims = _spec_claims() if claims is None else claims
    pilot = _pilot_modules() if pilot is None else pilot
    found, seen = [], set()
    for c in _new_claims(doc):
        cid = c["id"]
        if not re.fullmatch(r"C-\d{4}", cid) or int(cid[2:]) < FIRST_ID:
            found.append(f"{cid}: new ids start at C-{FIRST_ID}")
        if cid in seen or cid in claims:
            found.append(f"{cid}: id used twice")
        seen.add(cid)
        if not c.get("behaviour", "").strip():
            found.append(f"{cid}: no behaviour")
        if c["module"] not in pilot:
            found.append(f"{cid}: module {c['module']} is not in the pilot")
        for old in c["replaces"]:
            target = claims.get(old)
            if old in seen:
                found.append(f"{old}: replaced twice")
            seen.add(old)
            if target is None:
                found.append(f"{cid}: replaces unknown claim {old}")
                continue
            if target.get("status") != "active":
                found.append(f"{cid}: {old} is not active")
            if target.get("module") != c["module"]:
                found.append(f"{cid}: {old} belongs to {target.get('module')}, not {c['module']}")
    return found


def render(doc: dict) -> str:
    out = [INTRO]
    for n, change in enumerate(doc["changes"], 1):
        out.append(f"## Change {n}: {change['title']}\n\n{change['why']}\n")
        for c in change["claims"]:
            out.append(f"### {c['id']} (`{c['module']}`), replaces {', '.join(c['replaces'])}\n\n{c['behaviour']}\n")
    return "\n".join(out)


def manifest(doc: dict) -> str:
    claims = _new_claims(doc)
    return json.dumps({"replaced": {old: c["id"] for c in claims for old in c["replaces"]},
                       "modules": {c["id"]: c["module"] for c in claims}}, indent=1) + "\n"


def outputs(doc: dict) -> dict[Path, str]:
    return {MD: render(doc), HIDDEN: manifest(doc)}


def stale() -> list[str]:
    return [p.name for p, text in outputs(load()).items() if not p.is_file() or p.read_text() != text]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if an output is stale or an entry is invalid")
    args = ap.parse_args()
    doc = load()
    found = problems(doc)
    for line in found:
        print(line)
    if args.check:
        out = stale()
        print(f"out of date: {out}" if out else "up to date")
        return 1 if out or found else 0
    if found:
        return 1
    for path, text in outputs(doc).items():
        path.write_text(text)
    print(f"wrote the change request: {len(doc['changes'])} changes, {len(_new_claims(doc))} claims")
    return 0


if __name__ == "__main__":
    sys.exit(main())
