"""UH: a spec the UI validates or launches cannot make it hash or read arbitrary directories."""
from __future__ import annotations

import time

import pytest
import yaml

from tests.unit.ui_server.test_control import build_rig, preview
from tests.unit.ui_server.test_specs_api import _example_data, api, repo  # noqa: F401  (fixtures)


@pytest.mark.parametrize("field,value", [
    ("hidden_tests", "/usr"), ("hidden_tests", "../../../../../../"), ("prompt_file", "/etc/hosts"),
    ("constraints_file", "~/.ssh/config"), ("seed_requirements_lock", "../../../../../etc/passwd"),
])
def test_validate_refuses_path_fields_outside_the_repo(api, field, value):  # noqa: F811
    data = _example_data("pilot")
    data["task"][field] = value
    t0 = time.monotonic()
    r = api.post("/api/specs/validate", json={"data": data})
    assert r.status_code == 200 and r.json()["valid"] is False
    assert any("inside the repository" in e["message"] for e in r.json()["errors"]), r.text
    assert time.monotonic() - t0 < 2


def test_launch_preview_refuses_it_too(tmp_path):
    rig = build_rig(tmp_path)
    raw = yaml.safe_load(rig.spec.read_text())
    raw["task"]["hidden_tests"] = "/usr"
    rig.spec.write_text(yaml.safe_dump(raw))
    t0 = time.monotonic()
    r = rig.c.post("/api/launch/preview", json={"spec_path": rig.rel})
    assert r.status_code == 422 and "inside the repository" in r.text and time.monotonic() - t0 < 2
    assert rig.spawner.calls == []


def test_examples_still_validate(api):  # noqa: F811
    r = api.post("/api/specs/validate", json={"data": _example_data("pilot")})
    assert r.json()["valid"] is True


def test_existing_specs_inside_the_repo_still_preview(tmp_path):
    rig = build_rig(tmp_path)
    assert preview(rig).status_code == 200
