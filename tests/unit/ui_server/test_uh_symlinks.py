"""UH-5: nothing under a run directory is read through a symlink, on ANY GET route.

Differential: for every scenario the same run is built twice, once with the artifact removed and once with
it replaced by a symlink to hostile external content. Every GET route must answer identically, and the
external canary must appear nowhere.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.unit.analysis.synth import make_run
from tests.unit.ui_server.conftest import AUTH, BASE, PORT, TOKEN
from ui_server import safefs
from ui_server.app import create_app
from ui_server.settings import Settings

CANARY = "CANARY-EXTERNAL-7f3a9c"
REPO = Path(__file__).resolve().parents[3]


def _git(cwd: Path, *a: str) -> str:
    env = {"PATH": os.environ["PATH"], "HOME": str(cwd), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@x", "GIT_COMMITTER_NAME": "a",
           "GIT_COMMITTER_EMAIL": "a@x", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
           "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}
    return subprocess.run(["git", *a], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()


def make_bare(path: Path, msg: str) -> str:
    work = path.parent / (path.name + "-work")
    work.mkdir(parents=True)
    _git(work, "init", "-q", "-b", "main")
    (work / "f.txt").write_text(f"{msg}\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", msg)
    sha = _git(work, "rev-parse", "HEAD")
    _git(work.parent, "clone", "-q", "--bare", str(work), str(path))
    return sha


def build_run(base: Path, hostile: bool) -> tuple[Path, str, str]:
    """A finished run with every artifact kind; returns (runs_dir, rid, head sha). The hostile external
    tree lives in base/ext with the same names as the run's artifacts, full of the canary."""
    runs = base / "runs"
    runs.mkdir()
    rid = make_run(runs, experiment="exp-one", repeat=0, n_cp=2, agent_runs=[(750.0, 10, 0, 0, 0)])
    rd = runs / rid
    sha = make_bare(rd / "mirror.git", "real work")
    mf = json.loads((rd / "manifest.json").read_text())
    orch = rd / "events" / "orchestrator.jsonl"
    lines = [json.loads(ln) for ln in orch.read_text().splitlines()]
    for ln in lines:
        if ln.get("type") == "checkpoint":
            ln["payload"]["head_sha"] = sha
    orch.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    (rd / "scorer").mkdir()
    (rd / "scorer" / "score-t1.log").write_text("real scorer log\n")
    (rd / "snapshots" / "t1").mkdir(parents=True)
    (rd / "snapshots" / "t1" / "meta.json").write_text(json.dumps({"k": 1}))
    (rd / "review-items.json").write_text(json.dumps({"items": []}))
    (rd / "review-draft.json").write_text(json.dumps({"items": []}))
    if hostile:
        ext = base / "ext"
        ext.mkdir()
        (ext / "events").mkdir()
        for f in (rd / "events").glob("*.jsonl"):
            out = []
            for ln in f.read_text().splitlines():
                ev = json.loads(ln)
                ev["payload"] = {**(ev.get("payload") or {}), "text": CANARY, "msg": CANARY, "k": 1}
                out.append(json.dumps(ev))
            (ext / "events" / f.name).write_text("\n".join(out) + "\n")
        (ext / "manifest.json").write_text(json.dumps({**mf, "experiment_id": CANARY, "model": CANARY}))
        (ext / "scorer").mkdir()
        (ext / "scorer" / "score-t1.log").write_text(CANARY + "\n")
        (ext / "snapshots" / "t1").mkdir(parents=True)
        (ext / "snapshots" / "t1" / "meta.json").write_text(json.dumps({"k": 1, "canary": CANARY}))
        (ext / "review-items.json").write_text(json.dumps({"items": [{"id": CANARY}], "canary": CANARY}))
        (ext / "review-draft.json").write_text(json.dumps({"items": [{"id": CANARY}], "canary": CANARY}))
        make_bare(ext / "mirror.git", CANARY)
        (ext / "mirror.git" / "info").mkdir(exist_ok=True)
    return runs, rid, sha


SCENARIOS = {
    "events_dir": ["events"],
    "event_files": ["events/orchestrator.jsonl", "events/scorer.jsonl", "events/agent_stream.jsonl"],
    "manifest": ["manifest.json"],
    "scorer_dir": ["scorer"],
    "scorer_log_file": ["scorer/score-t1.log"],
    "snapshots_dir": ["snapshots"],
    "mirror_dir": ["mirror.git"],
    "review_files": ["review-items.json", "review-draft.json"],
}


def get_routes(app) -> list[str]:
    out = []
    for r in app.routes:
        if "GET" in (getattr(r, "methods", None) or ()) and r.path.startswith("/api/") \
                and "{rest:path}" not in r.path and "{name}" not in r.path:
            out.append(r.path)
    return sorted(out)


def fill(path: str, rid: str) -> list[str]:
    p = path.replace("{rid}", rid).replace("{k}", "1")
    extras = {
        "/events": ["?limit=500", "?limit=500&sources=orchestrator,scorer,agent_stream", "?cursor=orchestrator:0"],
        "/events/at": ["?t=100", "?t_s=600"],
        "/events/locate": ["?t=100"],
        "/feed": ["?limit=500", "?from=start&limit=500"],
        "/stream": ["?from=start&follow=false", "?from=tail&follow=false"],
        "/transcript": ["?limit=500"],
        "/review/history": ["?run=" + rid],
        "/diff": ["", "?max_bytes=100000"],
    }
    for suffix, qs in extras.items():
        if p.endswith(suffix):
            return [p + q for q in qs]
    return [p]


def snapshot_world(base: Path, scenario: str, linked: bool):
    runs, rid, sha = build_run(base, hostile=linked)
    rd = runs / rid
    for rel in SCENARIOS[scenario]:
        target = rd / rel
        if linked:
            ext = base / "ext" / rel
            if not ext.exists():
                raise AssertionError(f"no hostile twin for {rel}")
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
            target.symlink_to(ext)
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    settings = Settings(repo_root=REPO, runs_dir=runs, token=TOKEN, port=PORT, web_dist=base / "nodist")
    app = create_app(settings)
    out = {}
    with TestClient(app, base_url=BASE) as c:
        c.headers.update(AUTH)
        for route in get_routes(app):
            if route.startswith(("/api/specs", "/api/rules", "/api/feed-schema", "/api/health", "/api/control")):
                continue
            for url in fill(route, rid):
                r = c.get(url)
                out[url] = (r.status_code, r.text)
    return out, rid


def normalise(text: str, rid: str) -> str:
    text = re.sub(r'"reason":"[^"]*mirror\.git[^"]*"', '"reason":"MIRROR"', text)   # wording differs by design
    return re.sub(r'"(server_time|as_of|now|t|elapsed_s|generated_at|mtime|store_epoch|newest_log_epoch)":\s*[-0-9.e+]+',
                  r'"\1":0', text)


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_symlinked_artifact_answers_like_a_missing_one(tmp_path, scenario):
    a = tmp_path / "absent"
    b = tmp_path / "linked"
    a.mkdir()
    b.mkdir()
    absent, rid = snapshot_world(a, scenario, linked=False)
    linked, rid2 = snapshot_world(b, scenario, linked=True)
    assert rid == rid2 and absent.keys() == linked.keys()
    assert len(absent) > 25
    leaks = [u for u, (_s, t) in linked.items() if CANARY in t]
    assert not leaks, f"external content served by {leaks}"
    diff = [u for u in absent if (absent[u][0], normalise(absent[u][1], rid)) !=
            (linked[u][0], normalise(linked[u][1], rid))]
    assert not diff, f"symlinked {scenario} changed the answer of {diff}"


def test_safefs_primitives(tmp_path):
    root = tmp_path / "runs"
    (root / "r1" / "events").mkdir(parents=True)
    ext = tmp_path / "ext"
    ext.mkdir()
    (ext / "x.jsonl").write_text("secret\n")
    (root / "r1" / "events" / "ok.jsonl").write_text("ok\n")
    (root / "r1" / "events" / "link.jsonl").symlink_to(ext / "x.jsonl")
    (root / "r1" / "ev2").symlink_to(ext)
    safefs.register_root(root)
    assert safefs.read_text(root / "r1" / "events" / "ok.jsonl") == "ok\n"
    assert safefs.read_text(root / "r1" / "events" / "link.jsonl") is None
    assert safefs.read_text(root / "r1" / "ev2" / "x.jsonl") is None
    assert safefs.listdir(root / "r1" / "ev2") == []
    assert safefs.listdir(root / "r1" / "events") == ["ok.jsonl", "link.jsonl"] or \
        sorted(safefs.listdir(root / "r1" / "events")) == ["link.jsonl", "ok.jsonl"]
    assert not safefs.no_symlinks_below(root / "r1" / "ev2")
    assert safefs.no_symlinks_below(root / "r1" / "events" / "ok.jsonl")
