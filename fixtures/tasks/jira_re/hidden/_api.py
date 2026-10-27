"""The public-API tier of the jira-re hidden suite (phase JA1, docs/jira-re-design.md §7.4).

The plugin bundles a public Java API that other plugins compile against. The rewrite re-implements it from
the spec under its original names. The real library sits harness-side in ``../vendor/api/`` (extracted by
``prepare_seed.py``); the implementer never sees it. Three tiers use it:

* t05, signatures: every client-visible type of the real API exists in the rewrite with the same binary
  surface (``_classfile.compare_type``), one test per top-level type;
* t06, behaviour: the analyst's Java tests (``api/hidden/``), written against the API from the spec, run
  on the rewrite, one test per Java test method;
* t07, the visible subset: the pristine copy of the tests the seed ships in ``spec/api-tests/``
  (``api/visible/``), rerun the same way. The agent's own copy may have been edited; this one is not, so
  t07 minus the agent's own result shows edits that only made the visible tests easier.

Both Java tiers pass against the real library (``analyst/selfcheck_api.py``, recorded in
``api/selfcheck.json``).

The rewrite is compiled once per hidden run with the task's toolchain (``LRAE_RE_TOOLS``: Maven and its
read-only offline repository), on a copy of the snapshot whose ``src/test/`` is replaced by these tests,
with the scorer's own Maven invocation (not the agent's ``build.sh``). A test file that does not compile
against the rewrite (a missing type, a wrong signature) is dropped and the build retried, so it fails
alone and the rest still run.

Environment: ``LRAE_RE_TOOLS`` (the toolchain), ``LRAE_API_JARS`` (``os.pathsep``-separated jars,
overriding ``../vendor/api/``; with ``LRAE_TARGET_JAR`` and without it there is no API), ``LRAE_API_BUILD_TIMEOUT_S`` (default 900).
"""
from __future__ import annotations

import functools
import os
import re
import shutil
import signal
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import _classfile as cf

HERE = Path(__file__).resolve().parent
API_DIR = HERE / "api"
HIDDEN_TESTS = API_DIR / "hidden"
VISIBLE_TESTS = API_DIR / "visible"
VENDOR_API = HERE.parent / "vendor" / "api"
SIGNATURE_STAGE = 1      # the contract skeleton (stage 1) already declares the API
BEHAVIOUR_STAGE = 4      # every module done (stage 4)
MAX_ROUNDS = 6           # builds after dropping test files that do not compile
NO_TYPES, NO_TESTS = "<no-api>", "<no-tests>"


# ---------------------------------------------------------------- the reference

def api_jars() -> list[Path]:
    override = os.environ.get("LRAE_API_JARS", "").strip()
    if override:
        return [Path(p) for p in override.split(os.pathsep) if p]
    if os.environ.get("LRAE_TARGET_JAR", "").strip():
        return []   # another plugin than vendor/'s: its API, if any, comes with LRAE_API_JARS
    return sorted(VENDOR_API.glob("*.jar"))


@functools.lru_cache(maxsize=1)
def reference_surface() -> dict[str, cf.TypeSurface]:
    classes: dict[str, bytes] = {}
    for jar in api_jars():
        classes.update(cf.classes_in_jar(jar))
    return cf.surface_from_classes(classes)


def api_types() -> list[str]:
    """Top-level client-visible types of the real API (collection-time parameters)."""
    names = sorted({n for n, t in reference_surface().items() if t.outer is None})
    return names or [NO_TYPES]


def nested_of(top: str) -> list[cf.TypeSurface]:
    """``top`` and every visible member type inside it, outermost first."""
    ref = reference_surface()
    return [ref[n] for n in sorted(ref, key=len) if n == top or n.startswith(top + "$")]


# ---------------------------------------------------------------- the Java tests

@dataclass(frozen=True)
class JavaTest:
    cls: str        # fully qualified test class
    method: str
    path: str       # relative to the test root

    @property
    def id(self) -> str:
        return f"{self.cls}#{self.method}"


_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
_TEST_METHOD = re.compile(r"@Test\b(?:\s*@\w+(?:\([^)]*\))?)*\s+(?:public\s+|protected\s+)?void\s+(\w+)\s*\(")


def java_tests(root: Path) -> list[JavaTest]:
    """Every ``@Test`` method under ``root`` (JUnit 5 ``@Test`` only: one report entry per method)."""
    out = []
    for p in sorted(Path(root).rglob("*.java")) if Path(root).is_dir() else []:
        text = p.read_text()
        pkg = _PACKAGE.search(text)
        cls = (pkg.group(1) + "." if pkg else "") + p.stem
        out += [JavaTest(cls, m, p.relative_to(root).as_posix()) for m in _TEST_METHOD.findall(text)]
    return out


def test_ids(root: Path) -> list[str]:
    return [t.id for t in java_tests(root)] or [NO_TESTS]


# ---------------------------------------------------------------- building the rewrite

@dataclass
class Build:
    ok: bool
    reason: str | None = None
    classes: dict[str, bytes] = field(default_factory=dict)
    outcomes: dict[str, str] = field(default_factory=dict)         # Class#method -> passed|failed|error|skipped
    failures: dict[str, str] = field(default_factory=dict)         # Class#method -> first lines of the message
    uncompiled: dict[str, str] = field(default_factory=dict)       # test file (relative) -> first error
    tail: str = ""

    @functools.cached_property
    def surface(self) -> dict[str, cf.TypeSurface]:
        return cf.surface_from_classes(self.classes)


_JAVAC_ERROR = re.compile(r"^\[ERROR\] (/\S+?\.java):\[(\d+),\d+\] (.*)$", re.M)


def _mvn(tools: Path, tree: Path, goals: list[str], timeout_s: float,
         tails: list[Path] = ()) -> tuple[int | None, str]:
    tail = ",".join(str(t) for t in [tools / "m2", *tails])
    cmd = [str(tools / "bin" / "mvn"), "-o", "-B", "-ntp", f"-Dmaven.repo.local={tree / '.m2' / 'repository'}",
           f"-Dmaven.repo.local.tail={tail}", "-Dmaven.test.failure.ignore=true", "-DfailIfNoTests=false",
           "-Dsurefire.failIfNoSpecifiedTests=false", "-DtrimStackTrace=true", *goals]
    proc = subprocess.Popen(cmd, cwd=tree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout_s)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        return None, out or ""


def _reports(report_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    outcomes, messages = {}, {}
    for f in sorted(report_dir.glob("TEST-*.xml")) if report_dir.is_dir() else []:
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        for case in root.iter("testcase"):
            tid = f"{case.get('classname', '')}#{case.get('name', '').split('(', 1)[0]}"
            bad = next((c for c in case if c.tag in ("failure", "error")), None)
            outcomes[tid] = (bad.tag.replace("failure", "failed") if bad is not None
                             else "skipped" if any(c.tag == "skipped" for c in case) else "passed")
            if bad is not None:
                messages[tid] = ((bad.get("message") or "") + "\n" + (bad.text or ""))[:1500].strip()
    return outcomes, messages


def build(project: Path, test_roots: list[Path], tools: Path, *, timeout_s: float = 900,
          tails: list[Path] = ()) -> Build:
    """Compile ``project`` (a Maven project: the snapshot, or the self-check's) in a temp copy whose
    ``src/test/`` holds only the Java tests under ``test_roots``, and run them when there are any.
    ``tails``: more read-only repositories after the toolchain's (the self-check's real API jar)."""
    with tempfile.TemporaryDirectory(prefix="lrae-api-") as tmp:
        tree = Path(tmp) / "tree"
        shutil.copytree(project, tree, symlinks=False, ignore=shutil.ignore_patterns(".git", "target", ".m2"))
        shutil.rmtree(tree / "src" / "test", ignore_errors=True)
        dest = tree / "src" / "test" / "java"
        dest.mkdir(parents=True)
        for root in test_roots:
            if Path(root).is_dir():
                shutil.copytree(root, dest, dirs_exist_ok=True)
        has_tests = any(dest.rglob("*.java"))
        goals = ["test"] if has_tests else ["compile"]
        res = Build(ok=False)
        for _ in range(MAX_ROUNDS):
            rc, out = _mvn(tools, tree, goals, timeout_s, list(tails))
            res.tail = out[-3000:]
            if rc is None:
                res.reason = f"the build timed out after {timeout_s:.0f}s"
                return res
            in_tests: dict[str, str] = {}
            in_main: list[str] = []
            for m in _JAVAC_ERROR.finditer(out):
                path = Path(m.group(1)).resolve()
                if path.is_relative_to(dest.resolve()):
                    in_tests.setdefault(path.relative_to(dest.resolve()).as_posix(), f"line {m.group(2)}: {m.group(3)}")
                else:
                    in_main.append(f"{path.name}:{m.group(2)}: {m.group(3)}")
            if rc != 0 and in_main:
                res.reason = f"the rewrite does not compile: {in_main[0]}"
                return res
            if rc != 0 and in_tests:
                for rel, msg in in_tests.items():
                    res.uncompiled[rel] = msg
                    (dest / rel).unlink(missing_ok=True)
                if not any(dest.rglob("*.java")):
                    goals = ["compile"]
                continue
            if rc != 0:
                res.reason = f"the build failed (exit {rc}), not on a compile error"
                return res
            break
        else:
            res.reason = f"test files still fail to compile after {MAX_ROUNDS} rounds"
            return res
        res.ok = True
        res.classes = cf.classes_in_dir(tree / "target" / "classes") if (tree / "target" / "classes").is_dir() else {}
        res.outcomes, res.failures = _reports(tree / "target" / "surefire-reports")
        return res


# ---------------------------------------------------------------- the hidden run's build (one per session)

def toolchain() -> Path | None:
    raw = os.environ.get("LRAE_RE_TOOLS", "").strip()
    return Path(raw).expanduser() if raw else None


@functools.lru_cache(maxsize=1)
def session_build(with_tests: bool) -> Build:
    from _support import WS
    tools = toolchain()
    if tools is None or not (tools / "bin" / "mvn").exists():
        return Build(ok=False, reason="no toolchain: LRAE_RE_TOOLS must name the task's tools dir (scorer.yaml)")
    timeout = float(os.environ.get("LRAE_API_BUILD_TIMEOUT_S", "900"))
    roots = [HIDDEN_TESTS, VISIBLE_TESTS] if with_tests else []
    return build(WS, roots, tools, timeout_s=timeout)


def outcome_message(b: Build, test: JavaTest) -> str | None:
    """None when ``test`` passed in ``b``; otherwise why it did not."""
    if not b.ok:
        return b.reason
    if test.path in b.uncompiled:
        return f"{test.path} does not compile against the rewrite: {b.uncompiled[test.path]}"
    got = b.outcomes.get(test.id)
    if got == "passed":
        return None
    if got is None:
        return f"{test.id} did not run"
    return f"{test.id} {got}: {b.failures.get(test.id, '')}"
