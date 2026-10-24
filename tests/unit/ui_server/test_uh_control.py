"""UH: control endpoints refuse a runs dir the CLI does not use; paths outside the spec hash are bound."""
from __future__ import annotations

import yaml

from tests.unit.ui_server import control_support as cs
from tests.unit.ui_server.conftest import PORT, TOKEN
from tests.unit.ui_server.test_control import build_rig, launch, preview
from ui_server.settings import Settings

CONTROL_POSTS = [
    ("/api/launch/preview", {"spec_path": "spec/examples/ctl-test.yaml"}),
    ("/api/launch", {"nonce": "x"}),
    ("/api/runs/r1/stop", None),
    ("/api/runs/r1/kill", {"confirm": "r1"}),
    ("/api/runs/r1/resume/preview", {"from": "t1"}),
    ("/api/runs/r1/resume", {"from": "t1", "nonce": "x"}),
    ("/api/runs/r1/score", None),
    ("/api/clean", None),
]


def other_runs_rig(tmp_path):
    r = cs.make_repo(tmp_path)
    elsewhere = tmp_path / "elsewhere-runs"
    elsewhere.mkdir()
    settings = Settings(repo_root=r["repo"], runs_dir=elsewhere, token=TOKEN, port=PORT, web_dist=tmp_path / "nodist")
    spawner = cs.FakeSpawner()

    def edit(ctl):
        ctl.cfg.spawner = spawner
        ctl.cfg.code_root = cs.CODE_ROOT

    app, c = cs.make_client(settings, edit)
    return r, app, c, spawner


def test_control_is_disabled_when_the_runs_dir_is_not_the_clis(tmp_path):
    r, _app, c, spawner = other_runs_rig(tmp_path)
    for path, body in CONTROL_POSTS:
        resp = c.post(path, json=body)
        assert resp.status_code == 409 and resp.json()["detail"]["code"] == "control_disabled", (path, resp.text)
    st = c.get("/api/control/state").json()
    assert st["control_enabled"] is False and st["launch_allowed"] is False and "runs" in st["control_disabled_reason"]
    assert spawner.calls == []


def test_control_is_enabled_for_the_repos_own_runs_dir(tmp_path):
    rig = build_rig(tmp_path)
    st = rig.c.get("/api/control/state").json()
    assert st["control_enabled"] is True and st["control_disabled_reason"] is None


def test_work_dir_or_seed_repo_change_after_preview_invalidates_the_nonce(tmp_path):
    for field, value in (("isolation.work_dir", "elsewhere"), ("task.seed_repo", "seed2")):
        sub = tmp_path / field
        sub.mkdir()
        rig = build_rig(sub)
        n = preview(rig).json()["confirmation_nonce"]
        raw = yaml.safe_load(rig.spec.read_text())
        a, b = field.split(".")
        raw[a][b] = str(sub / value)
        (sub / value).mkdir(exist_ok=True)
        rig.spec.write_text(yaml.safe_dump(raw))
        r = launch(rig, n)
        assert r.status_code in (409, 400), (field, r.text)
        assert rig.spawner.calls == []
