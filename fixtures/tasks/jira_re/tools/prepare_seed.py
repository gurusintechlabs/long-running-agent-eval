#!/usr/bin/env python3
"""Pin the jira-re seed to the plugin jar (docs/jira-re-design.md §4).

    .venv/bin/python fixtures/tasks/jira_re/tools/prepare_seed.py [--check]

Reads ``fixtures/tasks/jira_re/target.yaml``, checks that the named jar is the only jar in
``fixtures/tasks/jira_re/vendor/``, records its SHA-256 in ``target.yaml``, pins the seed's ``pom.xml``
to the resolved Jira, AMPS and Java versions (``jira_target.py``), checks that the seed's ``CLAUDE.md``
equals the task's (D-15a), extracts the bundled public API libraries named in ``target.yaml``
(``public_api``) to ``vendor/api/`` for the hidden API tier (phase JA1) and the vendor's internal libraries
(``internal_libs``) to ``vendor/lib/`` for the copy-similarity reference (JS1), copies the visible API tests
(``hidden/api/visible/``) into the seed's ``spec/api-tests/``, builds the seed repo in a temp dir (``runner.seed``, the same procedure the
harness uses) and writes the resulting commit SHA into ``spec/examples/jira-re.yaml``.
Prints a short summary of the jar (classes, ``atlassian-plugin.xml`` modules). ``--check`` changes
nothing and exits 1 if anything is out of date.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "fixtures" / "tasks" / "jira_re" / "hidden"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import jira_target  # noqa: E402
import yaml  # noqa: E402

from runner.seed import build_seed_repo  # noqa: E402

TASK = REPO / "fixtures" / "tasks" / "jira_re"
SEED = REPO / "fixtures" / "seed_jira_re"
SPEC = REPO / "spec" / "examples" / "jira-re.yaml"
TARGET = TASK / "target.yaml"
PLACEHOLDER = "REPLACE_WITH_PLUGIN.jar"
VISIBLE_API_TESTS = TASK / "hidden" / "api" / "visible"
SEED_API_TESTS = SEED / "spec" / "api-tests"


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()} \
        if root.is_dir() else {}


def sync_visible_api_tests(*, check: bool = False) -> bool:
    """Make the seed's ``spec/api-tests/`` a byte copy of ``hidden/api/visible/``; with ``check``, only
    report whether it already is."""
    want = _tree(VISIBLE_API_TESTS)
    if _tree(SEED_API_TESTS) == want:
        return True
    if not check:
        shutil.rmtree(SEED_API_TESTS, ignore_errors=True)
        for rel, data in want.items():
            (SEED_API_TESTS / rel).parent.mkdir(parents=True, exist_ok=True)
            (SEED_API_TESTS / rel).write_bytes(data)
    return False


def _sub_line(text: str, key: str, value: str) -> str:
    """Replace the value of the first ``key:`` line, keeping indentation and any trailing comment."""
    pat = re.compile(rf"^(\s*{re.escape(key)}:\s*)(\"[^\"]*\"|\S+)(.*)$", re.M)
    if not pat.search(text):
        raise SystemExit(f"no '{key}:' line found")
    return pat.sub(lambda m: f"{m.group(1)}{value}{m.group(3)}", text, count=1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 if out of date")
    args = ap.parse_args()

    target = yaml.safe_load(TARGET.read_text())
    name = str(target.get("jar") or "")
    if not name or name == PLACEHOLDER or "/" in name:
        raise SystemExit(f"set 'jar:' in {TARGET.relative_to(REPO)} to the jar's file name")
    vendor = jira_target.VENDOR
    jars = sorted(p.name for p in vendor.glob("*.jar"))
    if jars != [name]:
        raise SystemExit(f"{vendor.relative_to(REPO)}/ must hold exactly {name}; found {jars or 'no jars'}")
    jar = vendor / name
    sha = hashlib.sha256(jar.read_bytes()).hexdigest()

    t = jira_target.load(TARGET, vendor)
    pom_path = SEED / "pom.xml"
    old_pom = pom_path.read_text()
    new_pom = jira_target.render_seed_pom(old_pom, t)

    if (SEED / "CLAUDE.md").read_bytes() != (TASK / "CLAUDE.md").read_bytes():
        raise SystemExit("fixtures/seed_jira_re/CLAUDE.md must equal fixtures/tasks/jira_re/CLAUDE.md (D-15a)")

    tests_current = sync_visible_api_tests(check=True)
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "src"   # the seed as it will be once pom.xml is pinned (--check writes nothing)
        shutil.copytree(SEED, staged)
        (staged / "pom.xml").write_text(new_pom)
        shutil.rmtree(staged / "spec" / "api-tests", ignore_errors=True)
        if VISIBLE_API_TESTS.is_dir():
            shutil.copytree(VISIBLE_API_TESTS, staged / "spec" / "api-tests")
        seed_sha = build_seed_repo(staged, Path(tmp) / "seed")

    from _support import (
        reference,  # the hidden suite's reference inventory, built from the jar alone
    )
    ref = reference(jar)
    print(f"jar:      {name}  ({jar.stat().st_size:,} bytes)")
    print(f"sha256:   {sha}")
    print(f"classes:  {len(ref.classes)} top-level, {len(ref.all_classes)} incl. inner")
    print(f"modules:  {len(ref.modules)} in atlassian-plugin.xml" if ref.descriptor_found
          else "modules:  no atlassian-plugin.xml found (module-level hidden tests will skip)")
    print(f"plugin:   key {t.plugin_key or '(no atlassian-plugin.xml)'}")
    for key in ("jira_version", "amps_version", "java_release"):
        print(f"{key + ':':<14}{getattr(t, key)}  ({t.sources[key]})")
    print(f"original non-test dependencies: {len(t.original_deps)} (primed by prime_maven_repo.py)")
    api_current = jira_target.extract_public_api(t, vendor / "api", check=True)
    print(f"public API: {', '.join(t.public_api) or '(none)'}"
          + ("" if api_current else "  (vendor/api/ out of date)"))
    libs_current = jira_target.extract_internal_libs(t, vendor / "lib", check=True)
    print(f"internal libraries: {len(t.internal_libs)}" + ("" if libs_current else "  (vendor/lib/ out of date)"))
    print(f"visible API tests: {len(_tree(VISIBLE_API_TESTS))} file(s)"
          + ("" if tests_current else "  (spec/api-tests/ out of date)"))
    print(f"seed SHA: {seed_sha}")

    new_target = _sub_line(TARGET.read_text(), "sha256", f'"{sha}"')
    new_spec = _sub_line(SPEC.read_text(), "seed_commit", f'"{seed_sha}"')
    stale = (new_target != TARGET.read_text() or new_spec != SPEC.read_text() or new_pom != old_pom
             or not api_current or not libs_current or not tests_current)
    if args.check:
        print("out of date: run without --check" if stale else "up to date")
        return 1 if stale else 0
    TARGET.write_text(new_target)
    SPEC.write_text(new_spec)
    pom_path.write_text(new_pom)
    jira_target.extract_public_api(t, vendor / "api")
    jira_target.extract_internal_libs(t, vendor / "lib")
    sync_visible_api_tests()
    print("updated target.yaml, the seed's pom.xml, vendor/api/, vendor/lib/ and the spec's seed_commit" if stale else "already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
