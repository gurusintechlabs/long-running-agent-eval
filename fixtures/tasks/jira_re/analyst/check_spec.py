#!/usr/bin/env python3
"""Check the analyst's specification once, harness-side (docs/jira-re-design.md §7.2).

    .venv/bin/python fixtures/tasks/jira_re/analyst/check_spec.py

The analyst (Claude, in a development session) writes the spec into the seed's ``spec/``. The agent under
test only implements it, so these checks are not part of P(t); they replace the old t00/t01 and run on
the analyst's files before a run:

* ``spec/inventory.json`` lists every module of the original ``atlassian-plugin.xml`` with its type;
* ``spec/claims.jsonl`` is well formed and gives every module at least one active claim;
* every claim has evidence in ``analyst/claims-evidence.jsonl`` (harness-side), and every reference
  exists in the jar or in its internal libraries; the implementer's ``claims.jsonl`` carries no evidence;
* no file in ``spec/`` names a class of the jar by its fully qualified name, unless
  ``analyst/contract-classes.txt`` lists it as part of the external contract (clean-room hygiene), nor
  by a CamelCase simple name (a word the contract needs, such as a URL alias, may be listed alone there);
  the vendor's internal libraries bundled in the jar (``internal_libs`` in target.yaml) count as its classes;
* ``analyst/spec-changes-1.md`` (the stage-5 change request) is written;
* the public Java API (phase JA1, design §7.4): ``spec/SPEC.md`` names every public top-level type of the
  real API (``vendor/api/``), whose names are contract and may appear anywhere in ``spec/``; no non-public
  API class is named (dotted, or in JVM form ``com/acme/Foo``, as generated signature tests write them); and every Java test of the hidden API tier (``hidden/api/``) is backed by an active
  claim, in ``analyst/api-test-claims.json`` (``{"Class#method": ["C-0001", ...]}``), so the tier only
  measures behaviour the spec states.

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

import _api  # noqa: E402  (the hidden API tier: its reference jars and Java tests)
import _classfile as cf  # noqa: E402
import _contract as ct  # noqa: E402  (REST endpoints and the AO schema, from the class files)
from _support import NON_MODULES, reference  # noqa: E402  (the hidden suite's reference, from the jar alone)

SEED_SPEC = TASK.parents[1] / "seed_jira_re" / "spec"
CLAIM_ID = re.compile(r"^C-\d{4}$")
CONFIDENCE = {"high", "medium", "low"}
STATUS = {"active", "retracted"}
JVM_NAME = re.compile(r"(?<![\w$/])L?((?:[a-z_][a-z0-9_]*/)+[A-Z][A-Za-z0-9_$]*)")   # com/acme/Foo, as in Lcom/acme/Foo;
CAMEL = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b")                        # RuleEngine, not Folder
FQCN = re.compile(r"\b(?:[a-z_][a-z0-9_]*\.)+[A-Z][A-Za-z0-9_$]*(?:\.[A-Z][A-Za-z0-9_$]*)*")


@dataclass
class Report:
    modules: int = 0
    inventoried: int = 0
    claimed: int = 0
    claims: int = 0
    api_types: int = 0
    api_specified: int = 0
    api_tests: int = 0
    api_tests_claimed: int = 0
    endpoints: int = 0
    endpoints_described: int = 0
    ao_columns: int = 0
    ao_columns_specified: int = 0
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


def internal_libs() -> list[str]:
    """``internal_libs`` globs from fixtures/tasks/jira_re/target.yaml."""
    import yaml
    return list(yaml.safe_load((TASK / "target.yaml").read_text()).get("internal_libs") or [])


def _internal_simple_names(classes, allowed: set[str]) -> set[str]:
    """CamelCase simple names (two humps or more, so plain words like ``Folder`` pass) of the jar's classes,
    minus those of contract classes and public API types, and words listed alone in contract-classes.txt."""
    def simple(n: str) -> str:
        return n.rsplit(".", 1)[-1].rsplit("$", 1)[-1]
    ok = {simple(n) for n in allowed}
    return {s for s in map(simple, classes) if CAMEL.fullmatch(s)} - ok


def jira_version() -> str:
    """The pinned Jira version, from the seed's pom.xml."""
    pom = (SEED_SPEC.parent / "pom.xml").read_text()
    return re.search(r"<jira\.version>([^<]+)</jira\.version>", pom).group(1)


def _section(md: str, token: str) -> str | None:
    """The text under the first heading that names ``token`` in backticks, up to the next heading."""
    lines = md.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("#") and f"`{token}`" in ln:
            body = []
            for nxt in lines[i + 1:]:
                if nxt.startswith("#"):
                    break
                body.append(nxt)
            return "\n".join(body)
    return None


def check_contract(rep: Report, *, jar: Path, libs: list[str], spec_md: str, jira: str, modules) -> None:
    """SPEC.md's contract section (phase JS2): every module in the module table with its type, every REST
    endpoint of the pinned Jira under a heading of its own with a description, every AO table and column."""
    p = rep.problems
    for m in modules:
        if not re.search(rf"^\|\s*`{re.escape(m.key)}`\s*\|\s*`{re.escape(m.element)}`\s*\|", spec_md, re.M):
            p.append(f"SPEC.md: module {m.key!r} ({m.element}) is not in the module table")
    classes = ct.jar_classes(jar, libs)
    root = ct.descriptor(jar)
    if root is None:
        return
    for _key, base, packages in ct.rest_modules(root, jira):
        for e in ct.rest_endpoints(classes, packages, base):
            rep.endpoints += 1
            body = _section(spec_md, ct.endpoint_id(e))
            if body is None:
                p.append(f"SPEC.md: REST endpoint {ct.endpoint_id(e)} is not specified")
            elif not body.strip() or ct.PENDING in body:
                p.append(f"SPEC.md: REST endpoint {ct.endpoint_id(e)} is not described yet")
            else:
                rep.endpoints_described += 1
    heading = ""
    for ln in spec_md.splitlines():
        if ln.startswith("#"):
            heading = ln.strip()
        elif ct.PENDING in ln and not re.fullmatch(r"#+ `[A-Z]+ /\S*`", heading):    # endpoints: reported above
            p.append(f"SPEC.md: a description is pending under {heading!r}")
    for el in root.iter("ao"):
        entities = [x.text.strip() for x in el.findall("entity") if x.text]
        for t in ct.ao_tables(classes, entities, el.get("namespace", "")):
            body = _section(spec_md, t.name)
            rep.ao_columns += len(t.columns)
            if body is None:
                p.append(f"SPEC.md: AO table {t.name} is not specified")
                continue
            for c in t.columns:
                if f"`{c.name}`" in body:
                    rep.ao_columns_specified += 1
                else:
                    p.append(f"SPEC.md: AO column {t.name}.{c.name} is not specified")


def check(*, jar: Path, spec_dir: Path = SEED_SPEC, analyst_dir: Path = HERE, api_jars: list[Path] = (),
          api_tests: list[str] = (), libs: list[str] = (), jira: str | None = None) -> Report:
    ref = reference(jar, libs)
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

    api_classes: dict[str, bytes] = {}
    for j in api_jars:
        api_classes.update(cf.classes_in_jar(j))
    surface = cf.surface_from_classes(api_classes)
    public_api = {n.replace("$", ".") for n in surface} | set(surface)
    api_internal = {n.replace("$", ".") for n in api_classes if n not in surface}
    allowed = contract_classes(analyst_dir / "contract-classes.txt") | public_api
    internal_simple = _internal_simple_names(ref.all_classes, allowed)
    for f in sorted(x for x in spec_dir.rglob("*") if x.is_file()):
        text = f.read_text(errors="replace")
        named = (set(FQCN.findall(text)) | {n.replace("/", ".") for n in JVM_NAME.findall(text)}) - allowed
        for n in sorted(x for x in named if ref.resolve(x)):
            p.append(f"{f.relative_to(spec_dir)}: names internal class {n} (not in contract-classes.txt)")
        for n in sorted(set(CAMEL.findall(text)) & internal_simple):
            p.append(f"{f.relative_to(spec_dir)}: names internal class {n} by its simple name")
        for n in sorted(x for x in named if x.replace("$", ".") in api_internal):
            p.append(f"{f.relative_to(spec_dir)}: names internal (non-public) API class {n}")

    spec_md = (spec_dir / "SPEC.md").read_text(errors="replace") if (spec_dir / "SPEC.md").is_file() else ""
    check_contract(rep, jar=jar, libs=libs, spec_md=spec_md, jira=jira or jira_version(), modules=ref.modules)
    named_in_spec = set(FQCN.findall(spec_md))
    tops = sorted(n for n, t in surface.items() if t.outer is None)
    rep.api_types = len(tops)
    for t in tops:
        if t in named_in_spec:
            rep.api_specified += 1
        else:
            p.append(f"SPEC.md: public API type {t} is not specified")

    rep.api_tests = len(api_tests)
    mapping_path = analyst_dir / "api-test-claims.json"
    mapping = (_json(mapping_path, p) if mapping_path.is_file() else {}) if api_tests else {}
    mapping = mapping if isinstance(mapping, dict) else {}
    active_ids = {c.get("id") for c in claims if c.get("status", "active") == "active"}
    for tid in api_tests:
        cids = mapping.get(tid)
        if not (isinstance(cids, list) and cids):
            p.append(f"api-test-claims.json: API test {tid} is backed by no claim")
            continue
        bad = [c for c in cids if c not in active_ids]
        if bad:
            p.append(f"api-test-claims.json: API test {tid} cites {', '.join(map(str, bad))}, not active claims")
        else:
            rep.api_tests_claimed += 1
    for tid in sorted(set(mapping) - set(api_tests)):
        p.append(f"api-test-claims.json: {tid} is not an API test (renamed or removed?)")

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
    tests = [t.id for t in _api.java_tests(_api.HIDDEN_TESTS) + _api.java_tests(_api.VISIBLE_TESTS)]
    rep = check(jar=jar, api_jars=_api.api_jars(), api_tests=tests, libs=internal_libs())
    print(f"modules {rep.modules}: inventoried {rep.inventoried}, with an active claim {rep.claimed}; "
          f"claims {rep.claims}; public API types {rep.api_types}: specified {rep.api_specified}; "
          f"API tests {rep.api_tests}: backed by claims {rep.api_tests_claimed}; "
          f"REST endpoints {rep.endpoints}: described {rep.endpoints_described}; "
          f"AO columns {rep.ao_columns}: specified {rep.ao_columns_specified}; problems {len(rep.problems)}")
    for line in rep.problems[:args.max]:
        print(f"  {line}")
    if len(rep.problems) > args.max:
        print(f"  ... {len(rep.problems) - args.max} more")
    return 1 if rep.problems else 0


if __name__ == "__main__":
    sys.exit(main())
