"""Pre-flight probe: one cheap real turn that proves L-3 (clean config) and L-5 (telemetry).

Starts ``claude -p "Reply with the single word OK."`` in a throwaway directory with the same
flags and scrubbed environment as a real run, then checks the ``init`` message (no MCP servers,
plugins, skills or unexpected tools) and that OTLP records reached the run's receiver. Costs a
few cents of subscription usage; its spend is logged separately from run cost (spec §5.1).
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from runner import memory, preflight, procs
from runner.preflight import Check
from runner.runtimes.base import TurnContext
from telemetry.events import redact

PROBE_PROMPT = "Reply with the single word OK."


@dataclass
class ProbeResult:
    checks: list[Check]
    lines: list[str] = field(default_factory=list)
    cost_usd: float | None = None


def run_probe(*, runtime, env: dict[str, str], receiver, probe_dir: Path, art: Path, settings_path: Path,
              claude_home: Path, timeout_s: float = 180, otel_wait_s: float = 5.0) -> ProbeResult:
    probe_dir = Path(probe_dir)
    probe_dir.mkdir(parents=True, exist_ok=True)
    before = receiver.stats["records"]
    ctx = TurnContext(prompt=PROBE_PROMPT, session_id=str(uuid.uuid4()), first_turn=True,
                      workspace=probe_dir, art=art, settings_path=settings_path,
                      otel_endpoint=receiver.endpoint, run_start_epoch=time.time(),
                      state_dir=probe_dir)
    lines: list[str] = []
    checks: list[Check] = []
    try:
        proc = procs.spawn(runtime.build_command(ctx), cwd=probe_dir, env=env, stdout=-1, stderr=-3,
                           text=True, sweep_root=probe_dir)
        deadline = time.monotonic() + timeout_s
        import threading

        def drain():
            for line in proc.popen.stdout:
                lines.append(line.rstrip("\n"))

        t = threading.Thread(target=drain, daemon=True)
        t.start()
        while proc.alive() and time.monotonic() < deadline:
            time.sleep(0.1)
        timed_out = proc.alive()
        if timed_out:
            proc.terminate(grace_s=5)
        t.join(timeout=5)
        rc = proc.popen.returncode

        init = preflight.find_init(lines)
        if init is None:
            checks.append(Check("probe: init message", False, f"no init message in stream (rc={rc})"))
        else:
            (art / "probe-init.json").write_text(json.dumps(redact(init), indent=1, sort_keys=True))
            checks.extend(preflight.evaluate_init(init, getattr(runtime, "allowed_tools", None)))
        result = next((json.loads(x) for x in reversed(lines) if x.startswith("{") and '"result"' in x), None)
        ok = bool(result) and not result.get("is_error") and rc == 0 and not timed_out
        detail = ""
        if not ok:
            reason = "timed out" if timed_out else f"rc={rc}"
            said = str((result or {}).get("result") or "").strip()  # e.g. the API's own error text
            detail = f"{reason}: {said[:300]}" if said else reason
        checks.append(Check("probe: agent replied", ok, detail))
        end = time.monotonic() + otel_wait_s
        while receiver.stats["records"] <= before and time.monotonic() < end:
            time.sleep(0.1)
        checks.append(Check("L-5 telemetry reaches receiver", receiver.stats["records"] > before,
                            "no OTLP records arrived from the CLI"))
        cost = result.get("total_cost_usd") if isinstance(result, dict) else None
        return ProbeResult(checks, lines, cost)
    finally:
        procs.sweep(probe_dir)
        memory.delete_state(memory.state_dir(probe_dir, claude_home))
        shutil.rmtree(probe_dir, ignore_errors=True)
