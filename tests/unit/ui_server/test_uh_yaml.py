"""UH-6: a YAML alias bomb is refused everywhere a spec is read, quickly and without memory growth."""
from __future__ import annotations

import resource
import threading
import time

import pytest
import yaml

from tests.unit.ui_server.test_control import build_rig, preview
from tests.unit.ui_server.test_specs_api import api, repo  # noqa: F401  (fixtures)
from ui_server import safeyaml


def bomb_text(levels: int = 12, fan: int = 10) -> str:
    lines = ["a0: &a0 [" + ", ".join(["x"] * fan) + "]"]
    for i in range(1, levels):
        lines.append(f"a{i}: &a{i} [" + ", ".join([f"*a{i - 1}"] * fan) + "]")
    return "\n".join(lines) + "\n"


def spec_with_bomb(base: str) -> str:
    return base + bomb_text()


def run_bounded(fn, seconds: float = 5.0):
    """Run ``fn`` in a daemon thread; fail (instead of hanging the suite) when it does not return."""
    box: dict = {}

    def target():
        try:
            box["v"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["e"] = exc

    t = threading.Thread(target=target, daemon=True)
    t0 = time.monotonic()
    rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    t.start()
    t.join(seconds)
    assert not t.is_alive(), f"still running after {seconds}s: the alias bomb is being expanded"
    box["elapsed"] = time.monotonic() - t0
    box["rss_mb"] = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - rss0) / (
        1 if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss < 10**9 else 1024) / 1024  # macOS: bytes
    if "e" in box:
        raise box["e"]
    return box


def test_loader_rejects_aliases_and_caps():
    with pytest.raises(yaml.YAMLError, match="alias"):
        safeyaml.load(bomb_text())
    with pytest.raises(yaml.YAMLError, match="alias"):
        safeyaml.load("a: &x {k: 1}\nb:\n  <<: *x\n")
    with pytest.raises(yaml.YAMLError, match="nodes"):
        safeyaml.load("[" + ",".join(["1"] * (safeyaml.MAX_NODES + 5)) + "]")
    with pytest.raises(yaml.YAMLError, match="deeper"):
        safeyaml.load("[" * 200 + "]" * 200)
    assert safeyaml.load("a: [1, 2]\nb: {c: d}\n") == {"a": [1, 2], "b": {"c": "d"}}


def test_validate_and_save_text_with_a_bomb(api):  # noqa: F811
    def go():
        r1 = api.post("/api/specs/validate", json={"yaml": spec_with_bomb("spec_version: 1\n")})
        r2 = api.post("/api/specs/save", json={"name": "bomb", "yaml": spec_with_bomb("spec_version: 1\n")})
        return r1, r2

    box = run_bounded(go)
    r1, r2 = box["v"]
    assert r1.status_code in (400, 413) and "alias" in r1.text
    assert r2.status_code in (400, 413)
    assert box["elapsed"] < 1.0 and box["rss_mb"] < 150


def test_hostile_draft_on_disk_is_listed_invalid_not_hung(api, repo):  # noqa: F811
    (repo / "spec" / "drafts").mkdir()
    (repo / "spec" / "drafts" / "bomb.yaml").write_text(spec_with_bomb("spec_version: 1\nexperiment_id: x\n"))
    box = run_bounded(lambda: api.get("/api/specs"))
    r = box["v"]
    assert r.status_code == 200 and box["elapsed"] < 1.0 and box["rss_mb"] < 150
    row = next(s for s in r.json()["specs"] if s["name"] == "bomb")
    assert row["valid"] is False and "alias" in row["errors"][0]["message"]
    assert next(s for s in r.json()["specs"] if s["name"] == "pilot")["valid"] is True
    g = run_bounded(lambda: api.get("/api/specs/bomb")["v"] if False else api.get("/api/specs/bomb"))["v"]
    assert g.status_code == 200 and g.json()["valid"] is False
    d = run_bounded(lambda: api.post("/api/specs/bomb/duplicate", json={}))["v"]
    assert d.status_code in (400, 413, 422)


def test_oversized_draft_is_refused_without_reading_it_all(api, repo):  # noqa: F811
    (repo / "spec" / "drafts").mkdir()
    (repo / "spec" / "drafts" / "big.yaml").write_text("k: " + "x" * (safeyaml.MAX_BYTES + 10) + "\n")
    r = api.get("/api/specs")
    row = next(s for s in r.json()["specs"] if s["name"] == "big")
    assert row["valid"] is False


def test_launch_preview_of_a_bomb_draft(tmp_path):
    rig = build_rig(tmp_path)
    (rig.r["repo"] / "spec" / "drafts").mkdir()
    (rig.r["repo"] / "spec" / "drafts" / "bomb.yaml").write_text(rig.spec.read_text() + bomb_text())
    box = run_bounded(lambda: rig.c.post("/api/launch/preview", json={"draft": "bomb.yaml"}))
    r = box["v"]
    assert r.status_code == 422 and r.json()["detail"]["code"] == "spec_invalid" and box["elapsed"] < 1.0
    assert rig.spawner.calls == []


def test_bomb_in_a_referenced_yaml_file_is_refused(tmp_path):
    rig = build_rig(tmp_path)
    (rig.r["assets"] / "constraints.yaml").write_text("constraints: []\n" + bomb_text())
    box = run_bounded(lambda: rig.c.post("/api/launch/preview", json={"spec_path": rig.rel}))
    assert box["v"].status_code == 422
    (rig.r["assets"] / "constraints.yaml").write_text("constraints: []\n")
    assert preview(rig).status_code == 200
