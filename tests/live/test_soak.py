"""Platform-limit probe (design risk "verify first"): keep the real CLI busy-but-cheap for hours.

Records login expiry, usage-limit stops, API errors, disconnects and sleep gaps. Writes
runs/soak-<timestamp>.json. Spends subscription usage; run once, overnight, with approval:
    LRAE_SOAK_MIN=180 LRAE_CONFIRM_SPEND=1 .venv/bin/python -m pytest tests/live/test_soak.py --run-api -s
"""
import json
import os
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from runner import memory
from runner.workdir import build_agent_env
from spec.loader import REPO_ROOT

pytestmark = pytest.mark.api

PROMPT = "Reply with exactly the word OK and nothing else."
GAP_S = int(os.environ.get("LRAE_SOAK_GAP_S", "300"))


def test_soak():
    minutes = float(os.environ.get("LRAE_SOAK_MIN", "180"))
    model = os.environ.get("LRAE_SOAK_MODEL", "claude-opus-5-5")
    work = Path.home() / "lrae-work" / f"soak-{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True)
    env = build_agent_env(host_env=dict(os.environ), tmpdir=work, path_dirs=["/usr/local/bin"],
                          otel_endpoint="http://127.0.0.1:9", protocol="http/json", export_interval_ms=60000,
                          resource_attrs={"lrae.run_id": "soak"})
    for k in [k for k in env if k.startswith("OTEL_") or k == "CLAUDE_CODE_ENABLE_TELEMETRY"]:
        del env[k]  # no telemetry sink for the soak
    session = str(uuid.uuid4())
    report = {"started": datetime.now(UTC).isoformat(), "minutes": minutes, "model": model, "turns": []}
    start = time.monotonic()
    last_wall, last_mono = time.time(), time.monotonic()
    try:
        n = 0
        while time.monotonic() - start < minutes * 60:
            sleep_gap = (time.time() - last_wall) - (time.monotonic() - last_mono)
            cmd = ["claude", "-p", PROMPT, "--model", model, "--output-format", "json",
                   "--setting-sources", "project,local", "--dangerously-skip-permissions"]
            cmd += ["--session-id", session] if n == 0 else ["--resume", session]
            t0 = time.monotonic()
            out = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=600)
            report["turns"].append({"n": n, "elapsed_min": round((t0 - start) / 60, 2), "rc": out.returncode,
                                    "seconds": round(time.monotonic() - t0, 1), "wall_vs_mono_gap_s": round(sleep_gap, 1),
                                    "stderr": out.stderr[-300:], "stdout_tail": out.stdout[-300:]})
            n += 1
            last_wall, last_mono = time.time(), time.monotonic()
            time.sleep(GAP_S)
    finally:
        report["ended"] = datetime.now(UTC).isoformat()
        out_path = REPO_ROOT / "runs" / f"soak-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        out_path.parent.mkdir(exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2))
        memory.delete_state(memory.state_dir(work))
        subprocess.run(["rm", "-rf", str(work)])
    failures = [t for t in report["turns"] if t["rc"] != 0]
    print(f"soak: {len(report['turns'])} turns, {len(failures)} failures; report at {out_path}")
