#!/usr/bin/env python3
"""Check the analyst's specification once, harness-side (docs/jira-re-design.md §7.2).

    .venv/bin/python fixtures/tasks/jira_re/analyst/check_spec.py

The analyst (Claude, in a development session) writes the spec into the seed's ``spec/``. The agent under
test only implements it, so these checks are not part of P(t); they replace the old t00/t01 and run on
the analyst's files before a run:

* ``spec/inventory.json`` lists every module of the original ``atlassian-plugin.xml`` with its type;
* ``spec/claims.jsonl`` is well formed and gives every module at least one active claim;
* every claim has evidence in ``analyst/claims-evidence.jsonl`` (harness-side), and every reference
  exists in the jar; the implementer's ``claims.jsonl`` carries no evidence;
* no file in ``spec/`` names a class of the jar by its fully qualified name, unless
  ``analyst/contract-classes.txt`` lists it as part of the external contract (clean-room hygiene);
* ``analyst/spec-changes-1.md`` (the stage-5 change request) is written.

Exit 1 when anything is wrong; the report lists every problem.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK / "hidden"))

from _support import NON_MODULES, reference  # noqa: E402  (the hidden suite's reference, from the jar alone)

SEED_SPEC = TASK.parents[1] / "seed_jira_re" / "spec"
CLAIM_ID = re.compile(r"^C-\d{4}$")
CONFIDENCE = {"high", "medium", "low"}
STATUS = {"active", "retracted"}
FQCN = re.compile(r"\b(?:[a-z_][a-z0-9_]*\.)+[A-Z][A-Za-z0-9_$]*(?:\.[A-Z][A-Za-z0-9_$]*)*")


@dataclass
class Report:
    modules: int = 0
    inventoried: int = 0
    claimed: int = 0
    claims: int = 0
    problems: list[str] = field(default_factory=list)


def _json(path: Path, problems: list[str]):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        problems.append(f"{path.name}: cannot read: {exc}")
        return None


def _jsonl(path: Path, problems: list[str]) -> list[dict]:
    if not path.is_file():
        problems.append(f"{path.name} is missing")
        return []
    rows = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if line.strip():
            try:
                row = json.loads(line)
            except ValueError as exc:
                problems.append(f"{path.name}:{n}: not JSON: {exc}")
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                problems.append(f"{path.name}:{n}: not an object")
    return rows


def contract_classes(path: Path) -> set[str]:
    """One class per line; ``#`` starts a comment (the reason it is contract)."""
    if not path.is_file():
        return set()
    return {ln.split("#", 1)[0].strip() for ln in path.read_text().splitlines() if ln.split("#", 1)[0].strip()}


def check(*, jar: Path, spec_dir: Path = SEED_SPEC, analyst_dir: Path = HERE) -> Report:
    ref = reference(jar)
    rep = Report(modules=len(ref.modules))
    p = rep.problems
    want = {m.key: m.element for m in ref.modules}

    inv = _json(spec_dir / "inventory.json", p) if (spec_dir / "inventory.json").is_file() else None
    if inv is None and not (spec_dir / "inventory.json").is_file():
        p.append("inventory.json is missing")
    if isinstance(inv, dict) and isinstance(inv.get("modules"), list):
        got = {m.get("key"): m for m in inv["modules"] if isinstance(m, dict)}
        for key, element in want.items():
            m = got.get(key)
            if m is None:
                p.append(f"inventory.json: module {key!r} is missing")
                continue
            rep.inventoried += 1
            if m.get("type") != element:
                p.append(f"inventory.json: module {key!r} has type {m.get('type')!r}; the original's is {element!r}")
            if not (isinstance(m.get("purpose"), str) and m["purpose"].strip()):
                p.append(f"inventory.json: module {key!r} has no purpose")
        for key in sorted(set(got) - set(want), key=str):
            p.append(f"inventory.json: module {key!r} is not in the original descriptor")
    elif inv is not None:
        p.append("inventory.json: 'modules' must be a list")

    claims = _jsonl(spec_dir / "claims.jsonl", p)
    rep.claims = len(claims)
    ids = [c.get("id") for c in claims]
    for dup in sorted({i for i in ids if ids.count(i) > 1}, key=str):
        p.append(f"claims.jsonl: id {dup!r} is used more than once")
    for c in claims:
        cid = c.get("id")
        if not (isinstance(cid, str) and CLAIM_ID.match(cid)):
            p.append(f"claims.jsonl: bad id {cid!r} (want C-0001)")
        if not (isinstance(c.get("behaviour"), str) and c["behaviour"].strip()):
            p.append(f"claims.jsonl: {cid}: behaviour must be non-empty")
        if c.get("confidence") not in CONFIDENCE:
            p.append(f"claims.jsonl: {cid}: confidence must be one of {sorted(CONFIDENCE)}")
        if c.get("status", "active") not in STATUS:
            p.append(f"claims.jsonl: {cid}: status must be one of {sorted(STATUS)}")
        if c.get("module") is not None and c.get("module") not in want:
            p.append(f"claims.jsonl: {cid}: module {c.get('module')!r} is not in the original descriptor")
        if "evidence" in c:
            p.append(f"claims.jsonl: {cid}: carries evidence; it belongs in analyst/claims-evidence.jsonl only")
    active = {c.get("module") for c in claims if c.get("status", "active") == "active"}
    for key in want:
        if key in active:
            rep.claimed += 1
        else:
            p.append(f"claims.jsonl: no active claim describes module {key!r}")

    evidence = {e.get("id"): e.get("evidence") for e in _jsonl(analyst_dir / "claims-evidence.jsonl", p)}
    for c in claims:
        cid = c.get("id")
        refs = evidence.get(cid)
        if not (isinstance(refs, list) and refs):
            p.append(f"claims-evidence.jsonl: {cid}: no evidence")
            continue
        for r in refs:
            if not ref.resolve(r):
                p.append(f"claims-evidence.jsonl: {cid}: {r} is not in the jar")

    allowed = contract_classes(analyst_dir / "contract-classes.txt")
    for f in sorted(x for x in spec_dir.rglob("*") if x.is_file()):
        leaked = sorted({n for n in FQCN.findall(f.read_text(errors="replace"))
                         if n not in allowed and ref.resolve(n)})
        for n in leaked:
            p.append(f"{f.relative_to(spec_dir)}: names internal class {n} (not in contract-classes.txt)")

    changes = analyst_dir / "spec-changes-1.md"
    if not changes.is_file():
        p.append("spec-changes-1.md is missing")
    elif "PLACEHOLDER" in changes.read_text():
        p.append("spec-changes-1.md is still the placeholder")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jar", type=Path, help="default: the one jar in fixtures/tasks/jira_re/vendor/")
    ap.add_argument("--max", type=int, default=40, help="problems to print (default 40)")
    args = ap.parse_args()
    jar = args.jar
    if jar is None:
        jars = sorted((TASK / "vendor").glob("*.jar"))
        if len(jars) != 1:
            raise SystemExit(f"{TASK / 'vendor'} must hold exactly one jar; found {len(jars)}")
        jar = jars[0]
    rep = check(jar=jar)
    print(f"modules {rep.modules}: inventoried {rep.inventoried}, with an active claim {rep.claimed}; "
          f"claims {rep.claims}; problems {len(rep.problems)}")
    for line in rep.problems[:args.max]:
        print(f"  {line}")
    if len(rep.problems) > args.max:
        print(f"  ... {len(rep.problems) - args.max} more")
    return 1 if rep.problems else 0


if __name__ == "__main__":
    sys.exit(main())
