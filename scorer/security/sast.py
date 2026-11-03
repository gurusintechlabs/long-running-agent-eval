"""Security SAST with fingerprinted findings (plan B4, docs/behavior-design.md §7.2, D-23).

Tools, all run by the scorer on a temp copy of the snapshot's product code in the spec's
``scoring.security.languages`` (:func:`collect_product_files`: non-test, non-vendor Python, and for Java the
sources outside tests, build output and hidden dirs):

* ``bandit``: from the scorer venv; ``--ignore-nosec``; bandit's own severity. Python files only.
* ``semgrep-ce``: ``semgrep scan --oss-only`` with the semgrep-rules repo pinned at a commit
  (``tools/semgrep-rules-<sha>``). Reproducible.
* ``semgrep-pro``: ``semgrep scan --pro`` with registry configs, run locally with the owner's login.
  Registry rules change over time, so it is marked ``reproducible: false``. If it cannot run (not
  logged in), it is skipped with a reason.

ruff's ``S`` rules mirror bandit's one for one (``S602`` is ``B602``) without bandit's severity, so
they are left out: counting both would report every finding twice. Only semgrep rules whose
``metadata.category`` is ``security`` count (the rest is lint). ``--metrics=off`` always; the scorer
never calls ``semgrep ci``.

A finding's **fingerprint** is ``sha1(tool, rule, path, whitespace-normalised source line)``, so it
survives the code moving to another line. ``compare`` gives new and fixed findings between two scans.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from scorer import sandbox
from scorer.metrics.d_defects import SKIP_DIRS, TEST_DIRS, VENDOR_DIRS, collect_files

SEVERITIES = ("high", "medium", "low")
_BANDIT_SEV = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
_SEMGREP_SEV = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
TIMEOUT_S = 300
JAVA_SKIP_DIRS = SKIP_DIRS | TEST_DIRS | VENDOR_DIRS | {"target", "out"}
JAVA_TEST_NAMES = ("Test.java", "Tests.java", "IT.java")   # surefire's and failsafe's naming conventions


@dataclass(frozen=True)
class Finding:
    tool: str
    rule: str
    severity: str
    path: str
    line: int
    message: str
    fingerprint: str


def fingerprint(tool: str, rule: str, path: str, text: str) -> str:
    norm = " ".join(str(text).split())
    return hashlib.sha1(f"{tool}\0{rule}\0{path}\0{norm}".encode()).hexdigest()


def _line(root: Path, rel: str, n: int) -> str:
    try:
        lines = (root / rel).read_text(errors="replace").splitlines()
        return lines[n - 1] if 0 < n <= len(lines) else ""
    except OSError:
        return ""


def _rel(root: Path, path: str) -> str:
    p = Path(path)
    try:
        return (p if p.is_absolute() else (root / p)).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def parse_bandit(doc: dict, root: Path) -> list[Finding]:
    out = []
    for r in doc.get("results") or []:
        rel = _rel(root, r["filename"])
        n = int(r.get("line_number") or 0)
        out.append(Finding("bandit", r["test_id"], _BANDIT_SEV.get(r.get("issue_severity"), "low"), rel, n,
                           str(r.get("issue_text", ""))[:300], fingerprint("bandit", r["test_id"], rel, _line(root, rel, n))))
    return out


def parse_semgrep(doc: dict, root: Path, *, tool: str) -> list[Finding]:
    out = []
    for r in doc.get("results") or []:
        extra = r.get("extra") or {}
        if (extra.get("metadata") or {}).get("category") != "security":
            continue
        rel = _rel(root, r["path"])
        n = int((r.get("start") or {}).get("line") or 0)
        out.append(Finding(tool, r["check_id"], _SEMGREP_SEV.get(extra.get("severity"), "low"), rel, n,
                           str(extra.get("message", ""))[:300], fingerprint(tool, r["check_id"], rel, _line(root, rel, n))))
    return out


def _java_files(root: Path) -> list[Path]:
    """Product Java: Maven's test sources (``src/test``), test classes elsewhere (by name, e.g. jira-re's visible
    API tests in ``spec/``), build output (``target/``), vendored code and hidden dirs are left out. Hidden dirs
    hold copies of the code: the agent's subagent worktrees (``.claude/worktrees/``, thousands of files in the
    JR1 pilot), decompiled sources and Maven's ``.m2``."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in JAVA_SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if name.endswith(".java") and not name.endswith(JAVA_TEST_NAMES) and p.is_file() and not p.is_symlink():
                out.append(p.relative_to(root))
    return out


def collect_product_files(root: Path, languages: list[str] = ("python",)) -> list[Path]:
    """The files SAST scans, relative to ``root``."""
    root = Path(root)
    return [*(collect_files(root) if "python" in languages else []),
            *(_java_files(root) if "java" in languages else [])]


# Pro's inter-file analysis takes one directory target, so the non-product files are excluded instead.
PRO_EXCLUDES = ("tests", "test", "testing", "test_*.py", "*_test.py", "conftest.py", "vendor", "vendored",
                "third_party", "_vendor", ".venv", "venv", "build", "dist", "__pycache__")


def semgrep_command(semgrep_bin: str, configs: list[str], targets: list[Path], *, pro: bool) -> list[str]:
    """CE scans the product files; Pro scans the tree directory (``targets == [tree]``) with
    :data:`PRO_EXCLUDES`."""
    cmd = [semgrep_bin, "scan", "--pro" if pro else "--oss-only", "--metrics=off", "--disable-version-check",
           "--quiet", "--json"]
    for c in configs:
        cmd += ["--config", str(c)]
    if pro:
        for x in PRO_EXCLUDES:
            cmd += ["--exclude", x]
    return cmd + [str(t) for t in targets]


def apply_ignore(findings: list[Finding], ignore: list[dict]) -> list[Finding]:
    """Scorer-owned suppressions: ``[{rule, paths: [globs]}]`` (a rule id or its last dotted part)."""
    def ignored(f: Finding) -> bool:
        for rule in ignore or []:
            rid = str(rule.get("rule", ""))
            if rid in (f.rule, f.rule.split(".")[-1]) and any(
                    fnmatch.fnmatch(f.path, g) for g in rule.get("paths") or ["**"]):
                return True
        return False
    return [f for f in findings if not ignored(f)]


def compare(prev_fingerprints: set[str], findings: list[Finding]) -> dict:
    cur = {f.fingerprint for f in findings}
    return {"new": [f for f in findings if f.fingerprint not in prev_fingerprints],
            "fixed": sorted(prev_fingerprints - cur)}


def counts(findings: list[Finding]) -> dict[str, int]:
    return {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}


def _version(cmd: list[str], env: dict, cwd: Path) -> str | None:
    r = sandbox.run(cmd, cwd=cwd, env=env, timeout_s=60, label="version")
    m = re.search(r"\d+\.\d+(\.\d+)?", (r.stdout or "") + (r.stderr or ""))
    return m.group(0) if m else None


def scan(tree: Path, *, python: Path, semgrep_bin: str | None = None, ce_configs: list[str] = (),
         pro_configs: list[str] = (), ignore: list[dict] = (), languages: list[str] = ("python",)) -> dict:
    """Scan ``tree`` (already a temp copy). Returns ``{"findings": [dict], "tools": {name: status}}``,
    where a status is ``{ok, reason, version, reproducible, n}``."""
    tree = Path(tree)
    files = [tree / f for f in collect_product_files(tree, languages)]
    py_files = [f for f in files if f.suffix == ".py"]
    tools: dict[str, dict] = {}
    findings: list[Finding] = []
    with sandbox.scratch_dir() as scratch:
        env = sandbox.scrubbed_env(python, scratch)

        def record(name: str, ok: bool, reason: str | None, version: str | None, reproducible: bool, found):
            tools[name] = {"ok": ok, "reason": reason, "version": version, "reproducible": reproducible,
                           "n": len(found)}
            findings.extend(found)

        if py_files:
            r = sandbox.run([str(python), "-m", "bandit", "-q", "--ignore-nosec", "-f", "json",
                             *[str(f) for f in py_files]], cwd=tree, env=env, timeout_s=TIMEOUT_S, label="bandit")
            try:
                found = parse_bandit(json.loads(r.stdout), tree)
                record("bandit", True, None, _version([str(python), "-m", "bandit", "--version"], env, tree), True, found)
            except (ValueError, KeyError) as exc:
                record("bandit", False, f"unparseable output: {exc}; {(r.stderr or '')[-200:]}", None, True, [])
        else:
            record("bandit", True, "no python files", None, True, [])

        for name, configs, pro in (("semgrep-ce", list(ce_configs), False), ("semgrep-pro", list(pro_configs), True)):
            if not configs:
                continue
            if not semgrep_bin:
                record(name, False, "semgrep not installed", None, not pro, [])
                continue
            if not files:
                record(name, True, f"no {' or '.join(languages)} files", None, not pro, [])
                continue
            # Pro needs the owner's login (~/.semgrep); CE runs with the scratch HOME.
            senv = dict(env, HOME=os.path.expanduser("~")) if pro else env
            r = sandbox.run(semgrep_command(semgrep_bin, configs, [tree] if pro else files, pro=pro), cwd=tree, env=senv,
                            timeout_s=TIMEOUT_S, label=name)
            try:
                doc = json.loads(r.stdout)
                if r.returncode not in (0, 1) and not doc.get("results"):
                    raise ValueError(f"exit {r.returncode}")
                record(name, True, None, _version([semgrep_bin, "--version"], senv, tree), not pro,
                       parse_semgrep(doc, tree, tool=name))
            except (ValueError, KeyError, TypeError) as exc:
                msg = " ".join(((r.stderr or "") + (r.stdout or "")).split())[-300:]
                record(name, False, f"{exc}: {msg}" if msg else str(exc), None, not pro, [])
    kept = apply_ignore(findings, list(ignore))
    return {"findings": [asdict(f) for f in kept], "tools": tools, "ignored": len(findings) - len(kept)}
