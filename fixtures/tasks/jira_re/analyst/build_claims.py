#!/usr/bin/env python3
"""Write the seed's ``spec/claims.jsonl`` and the harness-side ``analyst/claims-evidence.jsonl`` (phase JC1).

    .venv/bin/python fixtures/tasks/jira_re/analyst/build_claims.py [--check]

The analyst writes claims as notes, ``analyst/claim-notes/*.json`` (harness-side), read in file-name order:

    {"claims": [{"key": "ids-parse-rejects-garbage",            # the analyst's stable name for the claim
                 "module": null, "api": "com.acme.api.Ids",      # exactly one: a module key, or a top-level API type
                 "behaviour": "...", "confidence": "high|medium|low",
                 "status": "active|retracted",                   # optional, default active
                 "evidence": ["com.acme.api.Ids#parse"]}],       # classes or Class#method, in the jar, its
                                                                 # internal libraries or the API jar
     "tests": {"cleanroom.apitests.IdsTest#parses": ["ids-parse-rejects-garbage"]}}   # optional

``tests`` maps Java tests of the hidden API tier to the claims they rest on, by key; the build writes it, by
id, to ``analyst/api-test-claims.json`` (which ``check_spec.py`` reads).

Claim ids are permanent (design §4: wrong claims are retracted, never deleted). ``analyst/claim-ids.json`` maps
every key ever built to its id; a new key gets the next free id, and a key that disappears from the notes fails
the build (mark the claim ``retracted`` instead). The implementer's ``claims.jsonl`` carries neither keys nor
evidence; the evidence file carries both. A behaviour that says "(as the original does)" states a suspected bug of
the original: its row gets ``"suspected_bug": true``, so the implementer checks it (phase JC2). Unknown modules or API types, evidence that does not resolve, and
internal class names in a behaviour (dotted, or a CamelCase simple name) fail the build. ``--check`` exits 1
when either output or the id registry is stale.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK / "hidden"))
sys.path.insert(0, str(HERE))

from check_spec import CAMEL  # noqa: E402  (the leak scan's CamelCase names, shared)

NOTES_DIR = HERE / "claim-notes"
IDS = HERE / "claim-ids.json"
EVIDENCE = HERE / "claims-evidence.jsonl"
FIELDS = {"key", "module", "api", "behaviour", "confidence", "status", "evidence"}
CONFIDENCE = ("high", "low", "medium")
STATUS = ("active", "retracted")
SUSPECT = re.compile(r"as the original does", re.I)   # the analyst's marker for a suspected bug of the original
FQCN = re.compile(r"\b(?:[a-z_][a-z0-9_]*\.)+[A-Z][A-Za-z0-9_$]*(?:\.[A-Z][A-Za-z0-9_$]*)*")


@dataclass
class Built:
    claims: str             # spec/claims.jsonl
    evidence: str           # analyst/claims-evidence.jsonl
    ids: dict[str, str]     # analyst/claim-ids.json
    tests: str = "{}\n"     # analyst/api-test-claims.json


def load_notes(folder: Path) -> list[dict]:
    out: list[dict] = []
    for f in sorted(folder.glob("*.json")):
        out += json.loads(f.read_text()).get("claims") or []
    return out


def load_tests(folder: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in sorted(folder.glob("*.json")):
        for t, keys in (json.loads(f.read_text()).get("tests") or {}).items():
            if t in out:
                raise ValueError(f"{t} is mapped in two notes files")
            out[t] = keys
    return out


def _problems(c: dict, *, modules: set[str], api_types: set[str], resolve: Callable[[str], bool],
              internal: set[str], internal_simple: set[str], allowed: set[str]) -> list[str]:
    k = c["key"]
    p = [f"{k}: unknown field {f}" for f in sorted(set(c) - FIELDS)]
    if not (isinstance(c.get("behaviour"), str) and c["behaviour"].strip()):
        p.append(f"{k}: behaviour must be non-empty")
    if c.get("confidence") not in CONFIDENCE:
        p.append(f"{k}: confidence must be one of {list(CONFIDENCE)}")
    if c.get("status", "active") not in STATUS:
        p.append(f"{k}: status must be one of {list(STATUS)}")
    module, api = c.get("module"), c.get("api")
    if module is not None and api is not None:
        p.append(f"{k}: names both a module and an API type")
    elif module is None and api is None:
        p.append(f"{k}: names neither a module nor an API type")
    elif module is not None and module not in modules:
        p.append(f"{k}: module {module!r} is not in the original descriptor")
    elif api is not None and api not in api_types:
        p.append(f"{k}: API type {api!r} is not a public top-level API type")
    refs = c.get("evidence")
    if not (isinstance(refs, list) and refs):
        p.append(f"{k}: no evidence")
    else:
        p += [f"{k}: evidence {r} is not in the jar" for r in refs if not resolve(r)]
    text = str(c.get("behaviour") or "")
    for n in sorted(set(FQCN.findall(text)) - allowed):
        if n in internal or n.replace(".", "$") in internal:
            p.append(f"{k}: names internal class {n}")
    ok = {a.rsplit(".", 1)[-1].rsplit("$", 1)[-1] for a in allowed}
    p += [f"{k}: names internal class {n}" for n in sorted(set(CAMEL.findall(text)) & internal_simple - ok)]
    return p


def build(claims: list[dict], ids: dict[str, str], *, modules: set[str], api_types: set[str],
          resolve: Callable[[str], bool], internal: set[str] = frozenset(), internal_simple: set[str] = frozenset(),
          allowed: set[str] = frozenset(), tests: dict[str, list[str]] | None = None) -> Built:
    """The outputs and the updated id registry from the notes' ``claims`` and ``tests`` and the registry ``ids``."""
    problems: list[str] = []
    seen: set[str] = set()
    for c in claims:
        k = c.get("key")
        if not (isinstance(k, str) and k.strip()):
            problems.append(f"claim without a key: {json.dumps(c)[:80]}")
            continue
        if k in seen:
            problems.append(f"key {k!r} is used twice")
        seen.add(k)
        problems += _problems(c, modules=modules, api_types=api_types, resolve=resolve, internal=internal,
                              internal_simple=internal_simple, allowed=allowed)
    problems += [f"{cid} ({k}) was dropped from the notes; mark it retracted instead"
                 for k, cid in sorted(ids.items(), key=lambda kv: kv[1]) if k not in seen]
    for t, keys in sorted((tests or {}).items()):
        problems += [f"{t} cites unknown claim key {k!r}" for k in keys if k not in seen]
    if problems:
        raise ValueError("bad claims:\n  " + "\n  ".join(problems))

    ids = dict(ids)
    nxt = max((int(v[2:]) for v in ids.values()), default=0) + 1
    for c in claims:
        if c["key"] not in ids:
            ids[c["key"]] = f"C-{nxt:04d}"
            nxt += 1
    rows, evidence = [], []
    for c in sorted(claims, key=lambda c: ids[c["key"]]):
        row = {"id": ids[c["key"]], "module": c.get("module")}
        if c.get("api") is not None:
            row["api"] = c["api"]
        row.update(behaviour=c["behaviour"].strip(), confidence=c["confidence"], status=c.get("status", "active"))
        if SUSPECT.search(c["behaviour"]):
            row["suspected_bug"] = True
        rows.append(json.dumps(row, ensure_ascii=False))
        evidence.append(json.dumps({"id": row["id"], "key": c["key"], "evidence": c["evidence"]}, ensure_ascii=False))
    mapping = {t: sorted(ids[k] for k in keys) for t, keys in sorted((tests or {}).items())}
    return Built("\n".join(rows) + "\n", "\n".join(evidence) + "\n",
                 dict(sorted(ids.items(), key=lambda kv: kv[1])), json.dumps(mapping, indent=1) + "\n")


def sources() -> dict:
    """``build``'s keyword arguments for the real plugin: modules, API types, evidence resolver, leak sets."""
    import _api
    import _classfile as cf
    from _support import reference
    from check_spec import _internal_simple_names, contract_classes, internal_libs
    jars = sorted((TASK / "vendor").glob("*.jar"))
    if len(jars) != 1:
        raise SystemExit(f"{TASK / 'vendor'} must hold exactly one jar; found {len(jars)}")
    api: dict[str, bytes] = {}
    for j in _api.api_jars():
        api.update(cf.classes_in_jar(j))
    surface = cf.surface_from_classes(api)
    public_api = {n.replace("$", ".") for n in surface} | set(surface)
    ref = reference(jars[0], internal_libs())
    evidence_ref = reference(jars[0], internal_libs(), extra_jars=_api.api_jars())
    allowed = contract_classes(HERE / "contract-classes.txt") | public_api
    internal = (set(ref.all_classes) | set(api)) - set(surface)
    return dict(modules={m.key for m in ref.modules}, api_types={cf.top_level(n) for n in surface},
                resolve=evidence_ref.resolve, internal={n.replace("$", ".") for n in internal} | internal,
                internal_simple=_internal_simple_names(internal, allowed),
                allowed=allowed)


def main() -> int:
    from check_spec import SEED_SPEC
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the outputs or claim-ids.json are stale")
    ap.add_argument("--validate", type=Path, metavar="NOTES.json",
                    help="check one notes file on its own and write nothing (for helpers working in parallel)")
    args = ap.parse_args()
    ids = json.loads(IDS.read_text()) if IDS.is_file() else {}
    try:
        if args.validate:
            data = json.loads(args.validate.read_text())
            out = build(data.get("claims") or [], {}, tests=data.get("tests") or {}, **sources())
            print(f"ok: {out.claims.count(chr(10))} claims, {len(data.get('tests') or {})} tests mapped")
            return 0
        out = build(load_notes(NOTES_DIR), ids, tests=load_tests(NOTES_DIR), **sources())
    except ValueError as exc:
        print(exc)
        return 1
    files = {SEED_SPEC / "claims.jsonl": out.claims, EVIDENCE: out.evidence,
             IDS: json.dumps(out.ids, indent=1) + "\n", HERE / "api-test-claims.json": out.tests}
    n = out.claims.count("\n")
    if args.check:
        stale = [p.name for p, text in files.items() if not p.is_file() or p.read_text() != text]
        print(f"stale: {', '.join(stale)}" if stale else f"up to date: {n} claims")
        return 1 if stale else 0
    for p, text in files.items():
        p.write_text(text)
    print(f"wrote {n} claims ({len(out.ids) - len(ids)} new)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
