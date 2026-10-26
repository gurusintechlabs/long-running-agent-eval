"""Fixtures for the UI server tests: synthetic ``runs/`` dirs and a TestClient bound to 127.0.0.1."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from analysis.ingest import ingest
from tests.unit.analysis.synth import hazard, make_run

TOKEN = "test-token-0123456789"
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
AUTH = {"X-LRAE-Token": TOKEN}


def _set_manifest(runs_dir: Path, rid: str, **kw) -> None:
    p = runs_dir / rid / "manifest.json"
    m = json.loads(p.read_text())
    m.update(kw)
    p.write_text(json.dumps(m))


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "runs"
    d.mkdir()
    return d


@pytest.fixture
def settings(tmp_path: Path, runs_dir: Path):
    from ui_server.settings import Settings
    return Settings(repo_root=Path(__file__).resolve().parents[3], runs_dir=runs_dir,
                    token=TOKEN, port=PORT, web_dist=tmp_path / "no-dist")


@pytest.fixture
def client(settings):
    from fastapi.testclient import TestClient

    from ui_server.app import create_app
    with TestClient(create_app(settings), base_url=BASE) as c:
        c.headers.update(AUTH)
        yield c


@pytest.fixture
def two_runs(runs_dir: Path):
    """One ingested run with a hazard, and one finished run that is not in the store."""
    a = make_run(runs_dir, experiment="exp-one", repeat=0, n_cp=3, hazards=[hazard()],
                 state="BUDGET_EXHAUSTED")
    _set_manifest(runs_dir, a, model="claude-opus-5-5", claude_code_version="2.1.301",
                  seed_commit="s" * 40,
                  end={"state": "BUDGET_EXHAUSTED", "end_epoch": 1_800_001_800.0, "error": None,
                       "checkpoints": 3, "cost_usd": 4.5, "tokens": 1234})
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    b = make_run(runs_dir, experiment="exp-two", repeat=0, n_cp=2)
    return a, b


@pytest.fixture
def live_run(runs_dir: Path):
    rid = make_run(runs_dir, experiment="exp-live", repeat=0, n_cp=2, with_end=False)
    _set_manifest(runs_dir, rid, harness_pid=os.getpid())
    # a run in progress has not reached a final state yet
    orch = runs_dir / rid / "events" / "orchestrator.jsonl"
    lines = [ln for ln in orch.read_text().splitlines() if '"type": "state"' not in ln]
    lines.append(json.dumps({"ts": "x", "mono_ns": 1, "run_id": rid, "source": "orchestrator",
                             "type": "state", "seq": 99, "payload": {"from": "CHECKPOINTING", "to": "RUNNING"}}))
    orch.write_text("\n".join(lines) + "\n")
    return rid
