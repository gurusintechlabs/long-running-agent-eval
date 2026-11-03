"""AI vulnerability review (plan B4, docs/behavior-design.md §7.3, D-23).

The owner's methodology prompt (``scorer/vuln_review_prompt.md``) is run as a **separate, dedicated
``claude -p`` call** per review, so the security-reviewer persona has full focus and shares no
context with the agent or the other judges:

* The cwd is a temp copy of the product code (:func:`code_copy`: no tests, no ``.git``, no harness
  files). The only tools are ``Read``, ``Grep`` and ``Glob``. The env is scrubbed, safe mode is on, the
  MCP config is empty, and the cwd's agent state dir is deleted afterwards (as for the X judge).
* The APPLICATION CONTEXT comes from the task's ``security_context.yaml``, plus the SAST findings
  already known, so the review spends its effort beyond them.
* The reply must end with a fenced ``lrae-findings`` JSON block (schema below). It is retried once;
  if it still fails the review is ``ok: false`` (null, never zero), and nothing is cached.
* Results are cached by ``sha256(code + prompt + model)``. The full markdown report is kept next to
  the cached JSON.

Spend: every call consumes subscription usage, so :class:`ClaudeReviewRunner` refuses without
``--confirm-spend``. Spend is logged as ``cost_usd``, separate from the agent's S(t).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from runner.memory import delete_state, state_dir
from scorer.metrics.d_defects import SKIP_DIRS, TEST_DIRS
from scorer.metrics.x_judge import ClaudeJudgeRunner

PROMPT_PATH = Path(__file__).resolve().parents[1] / "vuln_review_prompt.md"
SEVERITIES = ("Critical", "High", "Medium", "Low")
CONFIDENCES = ("High", "Medium", "Low")
CONTEXT_KEYS = {"APP_NAME": "name", "APP_COMPONENT": "component", "APP_LANGUAGES": "languages",
                "APP_COMMUNICATES_WITH": "communicates_with", "APP_THREAT_MODEL": "threat_model",
                "APP_AI_INTEGRATIONS": "ai_integrations"}
_BLOCK = re.compile(r"```lrae-findings\s*\n(.*?)\n```", re.S)
_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.S)


class ReviewOutputError(ValueError):
    pass


def template() -> str:
    return _COMMENT.sub("", PROMPT_PATH.read_text())


def build_prompt(context: dict, sast_findings: list[dict]) -> str:
    text = template()
    for ph, key in CONTEXT_KEYS.items():
        text = text.replace("{{" + ph + "}}", str(context.get(key) or "not stated"))
    lines = [f"- {f['tool']} {f['rule']} ({f['severity']}) {f['path']}:{f['line']}: {f.get('message', '')[:160]}"
             for f in sast_findings] or ["(none)"]
    text = text.replace("{{SAST_FINDINGS}}", "\n".join(lines))
    if "{{" in text:
        raise ValueError(f"unfilled placeholder in the review prompt: {re.findall(r'{{[A-Z_]+}}', text)}")
    return text


def extract_findings(report: str) -> dict:
    blocks = _BLOCK.findall(report or "")
    if not blocks:
        raise ReviewOutputError("no ```lrae-findings block in the reply")
    try:
        data = json.loads(blocks[-1])
    except json.JSONDecodeError as exc:
        raise ReviewOutputError(f"lrae-findings is not JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise ReviewOutputError("lrae-findings needs a findings list")
    for i, f in enumerate(data["findings"]):
        if not isinstance(f, dict) or not isinstance(f.get("id"), str):
            raise ReviewOutputError(f"findings[{i}] needs a string id")
        if f.get("severity") not in SEVERITIES or f.get("confidence") not in CONFIDENCES:
            raise ReviewOutputError(f"findings[{i}] severity/confidence out of range")
        if not isinstance(f.get("locations", []), list):
            raise ReviewOutputError(f"findings[{i}].locations must be a list")
    data.setdefault("chains", [])
    data["sound"] = bool(data.get("sound", not data["findings"]))
    return data


def summarize(data: dict) -> dict:
    """Counted for the metric: Critical/High findings reported with at least Medium confidence."""
    fs = data["findings"]
    return {"high_or_critical": sum(1 for f in fs if f["severity"] in ("Critical", "High")
                                    and f["confidence"] in ("High", "Medium")),
            "by_severity": {s: sum(1 for f in fs if f["severity"] == s) for s in SEVERITIES},
            "chains": len(data.get("chains") or [])}


BUILD_DIRS = {"target", ".m2", ".decompiled"}   # Maven output and repository, decompiled sources (jira-re)


def _excluded(rel: Path) -> bool:
    parts = rel.parts
    if any(p in SKIP_DIRS or p in TEST_DIRS or p in BUILD_DIRS or p.startswith(".git") or p == ".claude"
           for p in parts[:-1]):
        return True
    name = parts[-1]
    return name.startswith(".git") or name in ("conftest.py",) or name.startswith("test_") or name.endswith("_test.py")


def code_copy(src: Path, dest: Path) -> Path:
    """The product code the reviewer sees: everything except tests, VCS, caches and harness files."""
    src, dest = Path(src), Path(dest)
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if p.is_symlink() or not p.is_file() or _excluded(rel):
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, out)
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def _parse_envelope(stdout: str) -> tuple[str, float]:
    try:
        env = json.loads(stdout)
    except (TypeError, ValueError) as exc:
        raise ReviewOutputError(f"stdout is not JSON: {exc}") from exc
    cost = env.get("total_cost_usd") if isinstance(env, dict) else None
    cost = float(cost) if isinstance(cost, (int, float)) else 0.0
    if not isinstance(env, dict) or env.get("is_error") or not isinstance(env.get("result"), str):
        err = ReviewOutputError(f"CLI error or no result: {str(env)[:200]}")
        err.cost_usd = cost  # type: ignore[attr-defined]
        raise err
    return env["result"], cost


def review(tree: Path, *, model: str, runner, cache_dir: Path, context: dict, sast_findings: list[dict],
           retries: int = 1) -> dict:
    """Review the product code in ``tree``. Returns ``{ok, key, cached, attempts, cost_usd, findings,
    chains, sound, summary, report_path, reason}``."""
    cache_dir = Path(cache_dir)
    with tempfile.TemporaryDirectory(prefix="lrae-review-") as tmp:
        code = code_copy(tree, Path(tmp) / "code")
        prompt = build_prompt(context, sast_findings)
        key = hashlib.sha256(f"{_tree_hash(code)}\0{prompt}\0{model}".encode()).hexdigest()
        cached = cache_dir / f"{key}.json"
        if cached.exists():
            data = json.loads(cached.read_text())
            return {**data, "cached": True, "cost_usd": 0.0, "attempts": 0}
        cost, reason = 0.0, None
        for attempt in range(1, retries + 2):
            try:
                text, c = _parse_envelope(runner(prompt, model, code))
                cost += c
                data = extract_findings(text)
            except (ReviewOutputError, RuntimeError) as exc:
                cost += getattr(exc, "cost_usd", 0.0)
                reason = str(exc)[:300]
                continue
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / f"{key}.md").write_text(text)
            out = {"ok": True, "key": key, "findings": data["findings"], "chains": data["chains"],
                   "sound": data["sound"], "summary": summarize(data), "report_path": str(cache_dir / f"{key}.md"),
                   "reason": None, "model": model}
            cached.write_text(json.dumps(out))
            return {**out, "cached": False, "attempts": attempt, "cost_usd": cost}
        return {"ok": False, "key": key, "findings": None, "chains": None, "sound": None, "summary": None,
                "report_path": None, "reason": reason, "model": model, "cached": False,
                "attempts": retries + 1, "cost_usd": cost}


class ClaudeReviewRunner(ClaudeJudgeRunner):
    """The installed CLI as the reviewer: read-only tools on the code copy, nothing else. A review
    reads the whole product (verified: about 9 minutes with Haiku on the minidb v2 engine), so the
    default timeout is 45 minutes rather than the judge's 10."""

    def __init__(self, claude_bin: str | None = None, *, timeout_s: float = 2700.0, **kw):
        super().__init__(claude_bin, timeout_s=timeout_s, **kw)

    def command(self, model: str, mcp_config: Path) -> list[str]:
        return [self.claude_bin, "-p", "--model", model, "--output-format", "json",
                "--tools", "Read,Grep,Glob",
                "--safe-mode", "--setting-sources", "project,local",
                "--strict-mcp-config", "--mcp-config", str(mcp_config)]

    def __call__(self, prompt: str, model: str, cwd: Path) -> str:  # type: ignore[override]
        base = Path(tempfile.mkdtemp(prefix="lrae-reviewer-")).resolve()
        tmp = base / "tmp"
        tmp.mkdir()
        mcp = base / "empty-mcp.json"
        mcp.write_text(self.EMPTY_MCP)
        try:
            try:
                proc = subprocess.run(self.command(model, mcp), input=prompt, cwd=cwd, env=self.env(tmp),
                                      capture_output=True, text=True, timeout=self.timeout_s,
                                      start_new_session=True)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"review timed out after {self.timeout_s}s") from exc
            if not proc.stdout.strip():
                raise RuntimeError(f"reviewer produced no output (exit {proc.returncode}): {proc.stderr.strip()[:300]}")
            return proc.stdout
        finally:
            delete_state(state_dir(Path(cwd).resolve(), self.claude_home))
            shutil.rmtree(base, ignore_errors=True)


class FakeReviewer:
    """Deterministic, content-based reviewer for tests and scripted runs: reports ``shell=True`` as a
    Critical command injection and ``pickle.loads`` as a High unsafe deserialisation."""

    PATTERNS = (("shell=True", "Command injection via shell=True", "CWE-78", "Critical"),
                ("pickle.loads", "Unsafe deserialisation of request data", "CWE-502", "High"))

    def __call__(self, prompt: str, model: str, cwd: Path) -> str:
        findings = []
        for p in sorted(Path(cwd).rglob("*.py")):
            for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                for needle, title, cwe, sev in self.PATTERNS:
                    if needle in line:
                        findings.append({"id": f"VULN-{len(findings) + 1}", "title": title, "category": "2A",
                                         "cwe": cwe, "severity": sev, "confidence": "High", "chainable": False,
                                         "chain_partners": [],
                                         "locations": [{"path": p.relative_to(cwd).as_posix(), "line": n}]})
        block = {"sound": not findings, "findings": findings, "chains": []}
        text = "## Fake review\n\n```lrae-findings\n" + json.dumps(block) + "\n```\n"
        return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text,
                           "total_cost_usd": 0})
