"""P(t): hidden acceptance pass rate on the snapshot working tree (docs/spec.md §8.2, D-8).

The scorer starts the agent's app from a temp copy of the snapshot with the scorer venv python, in
its own process group on a free loopback port, then runs the scorer-owned black-box tests in a
separate pytest process (``--noconftest``, own ini and rootdir; the agent's tree is never
collected). The process group is killed afterwards. If the app does not come up, every hidden test
counts as failed and the reason is returned.

Tasks without a server (``scorer.yaml`` has no ``app_cmd``, e.g. minidb) skip the app: the hidden
tests drive the agent's program themselves, in subprocesses, through ``test_env`` placeholders
``{ws}`` (the temp copy of the snapshot) and ``{python}`` (the scorer venv interpreter).
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from scorer import sandbox
from scorer.metrics.r_regression import PER_TEST_TIMEOUT_S, SuiteResult, run_pytest_json

SUITE_TIMEOUT_S = 300
_TIER_RE = re.compile(r"test_t(\d+)_")


def tier_of(nodeid: str) -> int | str:
    """Tier of a hidden test: the number in ``test_t(\\d+)_*.py``, else the file stem.

    A ``@pytest.mark.tier(n)`` override is not read: the JSON report is written with
    ``keywords`` omitted (and keywords hold only the marker name, not its argument), so the
    marker value is not recoverable from the report.
    """
    stem = Path(nodeid.split("::", 1)[0]).stem
    m = _TIER_RE.match(stem)
    return int(m.group(1)) if m else stem


def load_config(hidden: Path) -> dict:
    cfg = yaml.safe_load((Path(hidden) / "scorer.yaml").read_text()) or {}
    if "app_cmd" in cfg and "ready_path" not in cfg:
        raise ValueError(f"{hidden}/scorer.yaml has app_cmd but no ready_path")
    for key in ("suite_timeout_s", "per_test_timeout_s"):
        if key in cfg and not (isinstance(cfg[key], (int, float)) and not isinstance(cfg[key], bool)
                               and cfg[key] > 0):
            raise ValueError(f"{hidden}/scorer.yaml: {key} must be a positive number")
    return cfg


def per_test_timeout(cfg: dict) -> float:
    """pytest-timeout per test: ``scorer.yaml`` ``per_test_timeout_s`` (tests with large fixtures need
    more), else ``PER_TEST_TIMEOUT_S`` (spec §8.2)."""
    return float(cfg.get("per_test_timeout_s", PER_TEST_TIMEOUT_S))


def suite_timeout(cfg: dict) -> float:
    """Wall-clock limit of one hidden pytest run: ``scorer.yaml`` ``suite_timeout_s`` (tasks whose
    tests build large indexes need more), else ``SUITE_TIMEOUT_S``."""
    return float(cfg.get("suite_timeout_s", SUITE_TIMEOUT_S))


def _fmt(value: str, port: int, db: Path, ws: Path | None = None, python: Path | None = None) -> str:
    out = str(value).replace("{port}", str(port)).replace("{db}", str(db))
    if ws is not None:
        out = out.replace("{ws}", str(ws))
    if python is not None:
        out = out.replace("{python}", str(python))
    return out


def _wait_ready(url: str, proc, timeout_s: float) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_s
    last = "no response"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False, f"app exited with code {proc.returncode}"
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status < 500:
                    return True, ""
                last = f"HTTP {r.status}"
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return True, ""
            last = f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = str(exc)[:200]
        time.sleep(0.15)
    return False, f"not ready after {timeout_s:.0f}s ({last})"


def collect_ids(python: Path, hidden: Path, env: dict[str, str], cwd: Path,
                report: Path) -> list[str]:
    """Node ids of the hidden tests (from a collect-only JSON report), without running them."""
    cmd = [str(python), "-I", "-m", "pytest", "-c", str(hidden / "pytest.ini"),
           f"--rootdir={hidden}", "--noconftest", "-p", "no:cacheprovider", "--collect-only",
           "--json-report", f"--json-report-file={report}", str(hidden)]
    sandbox.run(cmd, cwd=cwd, env=env, timeout_s=60, label="collect")
    try:
        doc = json.loads(report.read_text())
    except (OSError, ValueError):
        return []
    ids = []
    for c in doc.get("collectors") or []:
        for item in c.get("result") or []:
            if item.get("type") == "Function":
                ids.append(item["nodeid"])
    return ids


def score_hidden(snapshot_ws: Path, hidden: Path, python: Path, *,
                 forbid: list[Path] | None = None, stage: int | None = None,
                 timing: bool = True) -> dict:
    """Return ``{"value", "detail"}`` for the P metric.

    Timing tests (``scorer.yaml`` ``timing_k``, a pytest ``-k`` expression) assert wall-clock limits.
    With ``timing=False`` (per-commit scoring, which runs several suites in parallel) they are
    deselected, so they neither pass nor fail. At checkpoints a failing timing test is rerun once and
    the rerun's outcome counts (the agent shares the machine), recorded in ``detail.timing_reruns``.

    ``stage`` (staged tasks, interfaces.md §9) is passed to the hidden pytest run as
    ``LRAE_STAGE``; tests not active at that stage come back ``skipped`` and are excluded from the
    denominator: value = passed / (total - skipped).
    """
    hidden = Path(hidden).resolve()
    cfg = load_config(hidden)
    with sandbox.temp_copy(snapshot_ws, forbid=forbid, name="app") as app_dir:
        scratch = app_dir.parent
        home = scratch / "home"
        home.mkdir()
        port, db = sandbox.free_port(), scratch / "app.db"
        url = f"http://127.0.0.1:{port}"
        has_app = "app_cmd" in cfg
        cmd = [_fmt(a, port, db, app_dir, python) for a in cfg.get("app_cmd") or []]
        if cmd and cmd[0] in ("python", "python3"):
            cmd[0] = str(python)
        app_env = sandbox.scrubbed_env(python, home, {
            k: _fmt(v, port, db, app_dir, python) for k, v in (cfg.get("env") or {}).items()})
        log = scratch / "app.log"
        log.write_bytes(b"")
        detail: dict = {"port": port, "app_cmd": cmd} if has_app else {"app_cmd": None}
        with open(log, "wb") as logfh:
            proc = sandbox.start(cmd, cwd=app_dir, env=app_env, stdout=logfh,
                                 label="app-under-test") if has_app else None
            try:
                ok, why = (_wait_ready(url + cfg["ready_path"], proc,
                                       float(cfg.get("startup_timeout_s", 20)))
                           if has_app else (True, ""))
                suite = SuiteResult()
                if ok:
                    t_env = {k: _fmt(v, port, db, app_dir, python)
                             for k, v in (cfg.get("test_env") or {}).items()}
                    t_env.setdefault("LRAE_APP_URL", url)
                    t_env.setdefault("LRAE_APP_DB", str(db))
                    if stage is not None:
                        t_env["LRAE_STAGE"] = str(int(stage))
                    base = ["-c", str(hidden / "pytest.ini"), f"--rootdir={hidden}", "--noconftest"]
                    timing_k = cfg.get("timing_k")
                    sel = ["-k", f"not ({timing_k})"] if (timing_k and not timing) else []
                    h_env = sandbox.scrubbed_env(python, home, t_env)
                    suite = run_pytest_json(
                        python, [*base, *sel, str(hidden)], cwd=hidden, env=h_env,
                        report=scratch / "hidden.json", timeout_s=suite_timeout(cfg), label="hidden",
                        per_test_timeout_s=per_test_timeout(cfg))
                    if timing and timing_k and not suite.reason:
                        failed = sorted(t for t, o in suite.outcomes.items() if o in ("failed", "error"))
                        if failed:
                            again = run_pytest_json(
                                python, [*base, "-k", timing_k, *failed], cwd=hidden, env=h_env,
                                report=scratch / "hidden-rerun.json", timeout_s=suite_timeout(cfg),
                                label="hidden-rerun", per_test_timeout_s=per_test_timeout(cfg))
                            detail["timing_reruns"] = dict(sorted(again.outcomes.items()))
                            suite.outcomes.update(again.outcomes)
            finally:
                if proc is not None:
                    sandbox.stop(proc)
        outcomes = dict(suite.outcomes)
        reason = None
        if not ok:
            reason = f"app_start_failed: {why}"
            detail["app_log_tail"] = log.read_text(errors="replace")[-1500:]
        elif suite.reason:
            reason = suite.reason
            detail["suite_tail"] = suite.tail
        if reason:
            env = sandbox.scrubbed_env(python, home, {"LRAE_APP_URL": url, "LRAE_APP_DB": str(db)})
            for tid in collect_ids(python, hidden, env, hidden, scratch / "collect.json"):
                if tid not in outcomes or not ok:
                    outcomes[tid] = "failed"
            detail["reason"] = reason
        total = len(outcomes)
        skipped = sum(1 for v in outcomes.values() if v == "skipped")
        active = total - skipped
        passed = sum(1 for v in outcomes.values() if v == "passed")
        if active == 0:
            detail["reason"] = detail.get("reason") or (
                "no_hidden_tests_ran" if total == 0 else "no_active_hidden_tests")
        detail.update(total=total, passed=passed, active=active, skipped=skipped, stage=stage,
                      outcomes=outcomes, tiers={t: tier_of(t) for t in sorted(outcomes)})
        return {"value": (passed / active) if active else 0.0, "detail": detail}
