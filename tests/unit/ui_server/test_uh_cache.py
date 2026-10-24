"""UH: manifests and logs are parsed once per (inode, size, mtime), and a change shows up."""
from __future__ import annotations

import json
import os
import time

from tests.unit.analysis.synth import make_run
from ui_server import store


def test_unchanged_runs_are_not_reparsed(client, runs_dir, monkeypatch):
    for i in range(30):
        make_run(runs_dir, experiment=f"exp-{i}", repeat=0, n_cp=2)
    assert client.get("/api/runs").status_code == 200       # warm
    calls = {"json": 0, "jsonl": 0}
    rj, rl = store._parse_json, store._parse_jsonl
    monkeypatch.setattr(store, "_parse_json", lambda b: (calls.__setitem__("json", calls["json"] + 1), rj(b))[1])
    monkeypatch.setattr(store, "_parse_jsonl", lambda b: (calls.__setitem__("jsonl", calls["jsonl"] + 1), rl(b))[1])
    t0 = time.monotonic()
    r = client.get("/api/runs")
    assert r.status_code == 200 and len(r.json()["runs"]) == 30
    assert calls == {"json": 0, "jsonl": 0}
    assert time.monotonic() - t0 < 2


def test_a_changed_manifest_is_seen_at_once(runs_dir):
    rid = make_run(runs_dir, experiment="exp-c", repeat=0, n_cp=1)
    p = runs_dir / rid / "manifest.json"
    assert store.read_json(p)["experiment_id"] == "exp-c"
    m = json.loads(p.read_text())
    m["experiment_id"] = "exp-changed"        # same size is possible: mtime still moves
    p.write_text(json.dumps(m))
    os.utime(p, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
    assert store.read_json(p)["experiment_id"] == "exp-changed"


def test_a_file_replaced_by_a_symlink_is_not_served_from_cache(client, runs_dir, tmp_path):
    rid = make_run(runs_dir, experiment="exp-l", repeat=0, n_cp=1)
    p = runs_dir / rid / "manifest.json"
    assert store.read_json(p) is not None
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"run_id": rid, "experiment_id": "EXTERNAL"}))
    p.unlink()
    p.symlink_to(other)
    assert store.read_json(p) is None
