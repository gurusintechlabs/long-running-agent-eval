"""Platform interruptions censor runs (docs/spec.md §7.4, D-7; docs/plan.md Phase 2)."""
import json
import time

import pytest

from runner.orchestrator import Run, RunState

from .test_guardrail_cases import guard_events, run, setup

pytestmark = pytest.mark.local


def api_error(i):
    return {"at": 0.3 + 0.1 * i, "do": "emit_otel", "event": "claude_code.api_error",
            "attrs": {"error": "500 Internal Server Error", "status_code": "500", "model": "scripted"}}


def test_repeated_api_errors_interrupt_the_run(env):
    loaded = setup(env, [*(api_error(i) for i in range(3)), {"do": "sleep", "seconds": 30}])
    _, res = run(env, loaded)
    assert res.state == RunState.INTERRUPTED, res.error
    intr = guard_events(res, "platform.interruption")
    assert intr and intr[0]["payload"]["kind"] == "api_error"
    manifest = json.loads(res.paths.manifest.read_text())
    assert manifest["end"]["censored_reason"] == "api_error"
    assert not guard_events(res, "guardrail.kill"), "an interruption is not a policy kill"


def test_usage_limit_result_interrupts(env):
    result = {"type": "result", "subtype": "error_during_execution", "is_error": True,
              "result": "Claude AI usage limit reached|1760000000", "total_cost_usd": 0}
    loaded = setup(env, [{"at": 0.3, "do": "emit_stream_event", "event": result},
                         {"do": "sleep", "seconds": 30}])
    _, res = run(env, loaded)
    assert res.state == RunState.INTERRUPTED, res.error
    assert guard_events(res, "platform.interruption")[0]["payload"]["kind"] == "usage_limit"
    manifest = json.loads(res.paths.manifest.read_text())
    assert manifest["end"]["censored_reason"] == "usage_limit"


def test_clock_gap_is_detected(env):
    """A wall-clock jump without monotonic progress means the machine slept."""
    loaded = setup(env, [{"do": "sleep", "seconds": 30}])
    jump = {"at": None}

    def wall():
        now = time.time()
        if jump["at"] is None:
            jump["at"] = time.monotonic() + 1.0
        return now + (120.0 if time.monotonic() > jump["at"] else 0.0)

    r = Run(loaded, "A", 0, repo_root=env["repo_root"], claude_home=env["claude_home"],
            host_home=env["home"], caffeinate=False, guard_opts={"wall": wall})
    res = r.execute()
    intr = guard_events(res, "platform.interruption")
    assert intr and intr[0]["payload"]["kind"] == "clock_gap"
    assert res.state == RunState.INTERRUPTED
