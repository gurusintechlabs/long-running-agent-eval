#!/usr/bin/env python3
"""Self-check of the public-API tier: its Java tests pass against the real API (phase JA1, design §7.4).

    .venv/bin/python fixtures/tasks/jira_re/analyst/selfcheck_api.py

Run once whenever ``hidden/api/`` or the API jar changes. It builds a Maven project that is the seed with
the real API library (``vendor/api/``, served from a scratch read-only repository) and the API's own
dependencies added, runs every hidden and visible API test on it with the same code the hidden tier uses
(``hidden/_api.build``), and records the result in ``hidden/api/selfcheck.json``: the jar and test-source
digests, and each test's outcome. A unit test refuses a record that is stale or not all green, so the
tests cannot change without a re-check. Needs the toolchain (``LRAE_RE_TOOLS``, default
``~/lrae-tools/re``) and no network. Exit 1 unless every test passed.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK / "hidden"))
sys.path.insert(0, str(TASK / "tools"))

import _api  # noqa: E402
import jira_target  # noqa: E402
import prime_maven_repo  # noqa: E402

RECORD = _api.API_DIR / "selfcheck.json"
GROUP, ARTIFACT, VERSION = "lrae.selfcheck", "public-api", "0"


def tests_digest() -> str:
    """SHA-256 over every file under ``hidden/api/hidden`` and ``hidden/api/visible`` (path and content)."""
    h = hashlib.sha256()
    for root in (_api.HIDDEN_TESTS, _api.VISIBLE_TESTS):
        for p in sorted(root.rglob("*")):
            if p.is_file():
                h.update(p.relative_to(_api.API_DIR).as_posix().encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def jar_digests(jars: list[Path]) -> dict[str, str]:
    return {j.name: hashlib.sha256(j.read_bytes()).hexdigest() for j in jars}


def _scratch_repo(root: Path, jars: list[Path]) -> list[jira_target.Dep]:
    """The real API jars as artifacts of a throw-away repository (one artifact per jar)."""
    deps = []
    for n, jar in enumerate(jars):
        art = f"{ARTIFACT}-{n}"
        d = root / GROUP.replace(".", "/") / art / VERSION
        d.mkdir(parents=True)
        shutil.copyfile(jar, d / f"{art}-{VERSION}.jar")
        (d / f"{art}-{VERSION}.pom").write_text(
            f"<project><modelVersion>4.0.0</modelVersion><groupId>{GROUP}</groupId><artifactId>{art}</artifactId>"
            f"<version>{VERSION}</version></project>\n")
        deps.append(jira_target.Dep(GROUP, art, VERSION, "provided"))
    return deps


def main() -> int:
    tools = Path(os.environ.get("LRAE_RE_TOOLS") or Path.home() / "lrae-tools" / "re").expanduser()
    jars = _api.api_jars()
    if not jars:
        raise SystemExit(f"no API jar in {_api.VENDOR_API}: run prepare_seed.py first")
    t = jira_target.load()
    tests = _api.java_tests(_api.HIDDEN_TESTS) + _api.java_tests(_api.VISIBLE_TESTS)
    with tempfile.TemporaryDirectory(prefix="lrae-selfcheck-") as tmp:
        repo = Path(tmp) / "repo"
        api_deps = _scratch_repo(repo, jars)
        project = Path(tmp) / "project"
        shutil.copytree(jira_target.SEED, project, ignore=shutil.ignore_patterns("spec", "analysis", ".git"))
        seed_pom = (project / "pom.xml").read_text()
        deps = api_deps + jira_target.public_api_dependencies(t)
        (project / "pom.xml").write_text(prime_maven_repo.priming_pom(seed_pom, deps, t.exclusions))
        b = _api.build(project, [_api.HIDDEN_TESTS, _api.VISIBLE_TESTS], tools, tails=[repo])
    outcomes = {x.id: (_api.outcome_message(b, x) or "passed") for x in tests}
    passed = sum(v == "passed" for v in outcomes.values())
    record = {"api_jars": jar_digests(jars), "tests_sha256": tests_digest(), "tests": len(tests), "passed": passed,
              "ok": bool(b.ok and tests and passed == len(tests)), "build_reason": b.reason,
              "outcomes": dict(sorted(outcomes.items()))}
    RECORD.write_text(json.dumps(record, indent=1) + "\n")
    print(f"{passed} of {len(tests)} API tests pass against the real API"
          + ("" if b.ok else f"; build: {b.reason}\n{b.tail[-2000:]}"))
    for tid, why in record["outcomes"].items():
        if why != "passed":
            print(f"  {tid}: {why[:400]}")
    print(f"recorded {RECORD}")
    return 0 if record["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
