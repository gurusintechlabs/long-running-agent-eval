"""Spec editor API (phase U6): listing, form schema, validation, drafts-only saves, round trips."""
from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from spec.loader import load_spec
from tests.unit.ui_server.conftest import AUTH, BASE, PORT, TOKEN
from ui_server import spec_store as ss
from ui_server.spec_ui import WIDGETS, build_form_schema, iter_fields

REAL_REPO = Path(__file__).resolve().parents[3]
EXAMPLES = sorted((REAL_REPO / "spec" / "examples").glob("*.yaml"))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo-shaped tmp dir: real examples copied, everything they reference symlinked, so hashes are real
    but drafts never touch the working tree."""
    r = tmp_path / "repo"
    (r / "spec").mkdir(parents=True)
    shutil.copytree(REAL_REPO / "spec" / "examples", r / "spec" / "examples")
    for d in ("fixtures", "guardrails", "scorer", "runner"):
        (r / d).symlink_to(REAL_REPO / d, target_is_directory=True)
    return r


@pytest.fixture
def api(repo: Path, tmp_path: Path):
    from ui_server.app import create_app
    from ui_server.settings import Settings
    s = Settings(repo_root=repo, runs_dir=tmp_path / "runs", token=TOKEN, port=PORT, web_dist=tmp_path / "nodist")
    with TestClient(create_app(s), base_url=BASE) as c:
        c.headers.update(AUTH)
        yield c


def _example_data(name: str = "pilot") -> dict:
    return yaml.safe_load((REAL_REPO / "spec" / "examples" / f"{name}.yaml").read_text())


def test_imports_worktree_copy():
    import ui_server
    assert Path(ui_server.__file__).resolve().is_relative_to(REAL_REPO)


# --- listing --------------------------------------------------------------------------------------------

def test_list_has_examples_read_only(api, repo):
    body = api.get("/api/specs").json()
    names = {s["name"]: s for s in body["specs"]}
    assert {p.stem for p in EXAMPLES} <= set(names)
    pilot = names["pilot"]
    assert pilot["source"] == "example" and pilot["editable"] is False
    assert pilot["path"] == "spec/examples/pilot.yaml"
    assert pilot["valid"] and len(pilot["spec_hash"]) == 64
    assert pilot["runtime"] == "claude_code" and pilot["model"] == "claude-opus-5-5"
    assert pilot["experiment_id"] == "pilot-export-csv"
    assert not (repo / "spec" / "drafts").exists()  # created on demand only


def test_list_flags_invalid_draft(api, repo):
    d = repo / "spec" / "drafts"
    d.mkdir()
    (d / "broken.yaml").write_text("spec_version: 1\nexperiment_id: BAD ID\n")
    (d / "notyaml.yaml").write_text(": : :\n- [")
    (d / "Bad Name.yaml").write_text("x: 1")
    items = {s["name"]: s for s in api.get("/api/specs").json()["specs"]}
    assert items["broken"]["valid"] is False and items["broken"]["spec_hash"] is None
    assert items["notyaml"]["valid"] is False
    assert "Bad Name" not in items


# --- schema ------------------------------------------------------------------------------------------------

def test_schema_shape(api):
    s = api.get("/api/specs/schema").json()
    assert s["version"] == 1 and s["json_schema"]["title"] == "Spec"
    assert [f["path"] for f in s["fields"]][:3] == ["spec_version", "experiment_id", "task"]
    flat = {f["path"]: f for f in iter_fields(s["fields"])}
    assert flat["run.duration_min"]["unit"] == "minutes" and flat["run.duration_min"]["exclusive_min"] == 0
    assert flat["agent.runtime"]["options"] == ["claude_code", "scripted"]
    assert flat["task.class"]["key"] == "class"                      # alias, not the python name
    assert flat["task.honey"]["widget"] == "object_list" and "task.honey.*.template" in flat
    assert flat["budget.per_run_usd"]["unit"] == "USD"
    assert flat["scoring.thresholds.repeat_work_ratio"]["default"] == 0.30
    assert flat["scoring.behavior.stall_min_s"]["advanced"] is True
    assert flat["agent.model"]["required_if"] == {"path": "agent.runtime", "equals": "claude_code"}
    assert any("real money" in n["text"] for n in s["cross_field_notes"])
    assert {f["section"] for f in flat.values()} <= {x["id"] for x in s["sections"]}


def test_every_schema_field_is_renderable_and_metadata_not_stale():
    s = build_form_schema()
    flat = {f["path"]: f for f in iter_fields(s["fields"])}
    from spec.schema import Spec
    # every model field of the tree is present (nothing silently dropped)
    top = {fi.alias or n for n, fi in Spec.model_fields.items()}
    assert top == {f["path"] for f in s["fields"]}
    for p, f in flat.items():
        assert f["widget"] in WIDGETS, p
        assert f["label"], p
        assert f["kind"], p
    from ui_server.spec_ui import FIELD_UI
    assert set(FIELD_UI) <= set(flat), f"metadata for fields that no longer exist: {set(FIELD_UI) - set(flat)}"


def test_new_exotic_field_falls_back_to_generic_widget(monkeypatch):
    """A field added to the schema without metadata still renders (generic widget, flagged as fallback)."""
    from pydantic import create_model

    from spec import schema as sch
    from ui_server import spec_ui
    new = create_model("Spec", __base__=sch.Spec, brand_new=(dict[str, int], {}), other=(float | None, None))
    monkeypatch.setattr(spec_ui, "Spec", new)
    flat = {f["path"]: f for f in iter_fields(spec_ui.build_form_schema()["fields"])}
    assert flat["brand_new"]["widget"] == "json" and flat["brand_new"]["fallback"] is True
    assert flat["other"]["widget"] == "number" and flat["other"]["nullable"] is True
    assert flat["brand_new"]["label"] == "Brand new"


def test_current_schema_has_no_fallback_fields():
    # informational guard: fields have explicit labels/help today. A new field may use the fallback, but then
    # add a FIELD_UI entry; this test lists what is missing.
    missing = [f["path"] for f in iter_fields(build_form_schema()["fields"]) if f["fallback"]]
    assert missing == []


# --- get / validate ----------------------------------------------------------------------------------------

def test_get_example_returns_data_and_yaml(api):
    r = api.get("/api/specs/pilot").json()
    assert r["source"] == "example" and r["data"]["task"]["class"] == "L1"
    assert r["yaml"].startswith("# Pilot") and r["valid"]
    assert r["run_ids"] == [f"pilot-export-csv-A-r00-{r['spec_hash'][:8]}", f"pilot-export-csv-A-r01-{r['spec_hash'][:8]}"]


def test_get_unknown_and_bad_names(api):
    assert api.get("/api/specs/nope").status_code == 404
    assert api.get("/api/specs/..%2Fpilot").status_code == 404
    assert api.get("/api/specs/pilot?source=other").status_code == 422


def test_validate_ok_matches_cli(api, repo):
    r = api.post("/api/specs/validate", json={"data": _example_data()}).json()
    assert r["valid"] and r["errors"] == []
    expected = load_spec(REAL_REPO / "spec" / "examples" / "pilot.yaml", repo_root=REAL_REPO)
    assert r["spec_hash"] == expected.spec_hash
    assert r["run_ids"] == [expected.run_id("A", 0), expected.run_id("A", 1)]
    assert any(w["path"] == "agent.runtime" and "real money" in w["message"] for w in r["warnings"])
    assert r["summary"]["checkpoints"] == 6


def test_validate_yaml_input_equals_data_input(api):
    text = (REAL_REPO / "spec" / "examples" / "pilot.yaml").read_text()
    a = api.post("/api/specs/validate", json={"yaml": text}).json()
    b = api.post("/api/specs/validate", json={"data": _example_data()}).json()
    assert a["spec_hash"] == b["spec_hash"]


def test_validate_errors_are_field_addressed(api):
    d = _example_data()
    d["task"]["seed_commit"] = "abc"
    d["run"]["checkpoint_interval_min"] = 7
    d["budget"]["per_run_usd"] = -1
    d["agent"]["model"] = "opus"
    d["task"]["honey"] = [{"id": "h", "path": "../x", "where": "nowhere", "template": "no token"}]
    d["extra_key"] = 1
    r = api.post("/api/specs/validate", json={"data": d}).json()
    assert r["valid"] is False and r["spec_hash"] is None and r["run_ids"] == []
    by = {e["path"]: e["message"] for e in r["errors"]}
    assert "40-char" in by["task.seed_commit"]
    assert "divide" in by["run.checkpoint_interval_min"]
    assert "budget.per_run_usd" in by
    assert "full model ID" in by["agent.model"]
    assert "task.honey" in by or "task.honey.0.path" in by
    assert "task.honey.0.where" in by and "task.honey.0.template" in by
    assert "extra_key" in by
    assert all(not m.startswith("Value error") for m in by.values())


def test_validate_missing_file_is_addressed(api):
    d = _example_data()
    d["task"]["hidden_tests"] = "../../fixtures/no/such/dir"
    r = api.post("/api/specs/validate", json={"data": d}).json()
    assert not r["valid"]
    assert r["errors"][0]["path"] == "task.hidden_tests"
    assert str(REAL_REPO) not in r["errors"][0]["message"] or "<repo>" in r["errors"][0]["message"]


def test_validate_scripted_rules_and_nulls(api):
    d = _example_data("pilot-scripted")
    d["agent"]["model"] = None            # form sends nulls for unset optional fields
    d["task"]["stages_file"] = ""
    r = api.post("/api/specs/validate", json={"data": d}).json()
    assert r["valid"], r["errors"]
    d["agent"]["script"] = ""
    d["agent"]["script"] = None
    r = api.post("/api/specs/validate", json={"data": d}).json()
    assert not r["valid"] and r["errors"][0]["path"] == "agent.script" and r["errors"][0]["group"] == "agent"


def test_validate_requires_exactly_one_input(api):
    assert api.post("/api/specs/validate", json={}).status_code == 400
    assert api.post("/api/specs/validate", json={"data": {}, "yaml": "a: 1"}).status_code == 400


def test_validate_bad_yaml_and_non_mapping(api):
    assert api.post("/api/specs/validate", json={"yaml": "a: [1,"}).status_code == 400
    r = api.post("/api/specs/validate", json={"yaml": "- 1\n- 2"}).json()
    assert not r["valid"] and "mapping" in r["errors"][0]["message"]


def test_yaml_is_safe_loaded(api):
    r = api.post("/api/specs/validate", json={"yaml": "x: !!python/object/apply:os.system ['echo hi']"})
    assert r.status_code == 400


def test_oversize_yaml_rejected(api):
    assert api.post("/api/specs/validate", json={"yaml": "a: " + "x" * ss.MAX_YAML_BYTES}).status_code == 413


def test_validate_does_not_write(api, repo):
    api.post("/api/specs/validate", json={"data": _example_data()})
    assert not (repo / "spec" / "drafts").exists()


def test_duplicate_experiment_id_warns(api, repo):
    r = api.post("/api/specs/validate", json={"data": _example_data()}).json()
    assert any(w["path"] == "experiment_id" and "pilot" in w["message"] for w in r["warnings"])


def test_high_budget_warns(api):
    d = _example_data()
    d["budget"] = {"per_run_usd": 60, "experiment_usd": 500}
    r = api.post("/api/specs/validate", json={"data": d}).json()
    paths = {w["path"] for w in r["warnings"]}
    assert {"budget.per_run_usd", "budget.experiment_usd"} <= paths


# --- save / duplicate / delete -------------------------------------------------------------------------------

def test_save_creates_draft_with_hash_and_path(api, repo):
    d = _example_data()
    d["experiment_id"] = "saved-one"
    r = api.post("/api/specs/save", json={"name": "my-draft", "data": d})
    assert r.status_code == 200
    j = r.json()
    assert j["saved"] and j["path"] == "spec/drafts/my-draft.yaml" and j["source"] == "draft"
    f = repo / "spec" / "drafts" / "my-draft.yaml"
    assert load_spec(f, repo_root=repo).spec_hash == j["spec_hash"]
    assert not list((repo / "spec" / "drafts").glob(".tmp-*"))
    assert f.read_text().startswith("# Saved by the LRAE UI")
    got = api.get("/api/specs/my-draft").json()
    assert got["source"] == "draft" and got["editable"] and got["spec_hash"] == j["spec_hash"]


def test_save_is_deterministic_and_schema_ordered(api, repo):
    d = _example_data()
    shuffled = {k: d[k] for k in reversed(list(d))}
    api.post("/api/specs/save", json={"name": "a", "data": d})
    api.post("/api/specs/save", json={"name": "b", "data": shuffled})
    a = (repo / "spec/drafts/a.yaml").read_text()
    assert a == (repo / "spec/drafts/b.yaml").read_text()
    keys = list(yaml.safe_load(a))
    assert keys[:3] == ["spec_version", "experiment_id", "task"]


def test_save_refuses_invalid_and_leaves_nothing(api, repo):
    d = _example_data()
    d["run"]["repeats"] = 0
    r = api.post("/api/specs/save", json={"name": "bad", "data": d})
    assert r.status_code == 422 and r.json()["saved"] is False
    assert r.json()["errors"][0]["path"] == "run.repeats"
    assert not (repo / "spec" / "drafts" / "bad.yaml").exists()


def test_save_overwrite_flag(api):
    d = _example_data()
    assert api.post("/api/specs/save", json={"name": "x1", "data": d}).status_code == 200
    assert api.post("/api/specs/save", json={"name": "x1", "data": d}).status_code == 409
    assert api.post("/api/specs/save", json={"name": "x1", "data": d, "overwrite": True}).status_code == 200


@pytest.mark.parametrize("name", ["../evil", "/abs", "a/b", "..", ".hidden", "UPPER", "", "x" * 65, "a b",
                                  "trail.", "x\x00y", "schema", "validate", "save", "paths", "a\\b", "-lead"])
def test_save_rejects_bad_names(api, repo, name):
    r = api.post("/api/specs/save", json={"name": name, "data": _example_data()})
    assert r.status_code in (400, 422), r.text
    assert not (repo / "spec" / "drafts").exists() or not any((repo / "spec" / "drafts").iterdir())
    assert not (repo.parent / "evil.yaml").exists()


def test_save_never_touches_examples(api, repo):
    before = (repo / "spec/examples/pilot.yaml").read_bytes()
    r = api.post("/api/specs/save", json={"name": "pilot", "data": _example_data(), "overwrite": True})
    assert r.status_code == 200 and r.json()["path"] == "spec/drafts/pilot.yaml"   # a draft, not the example
    assert (repo / "spec/examples/pilot.yaml").read_bytes() == before
    assert api.get("/api/specs/pilot").json()["source"] == "draft"                  # shadows by default
    assert api.get("/api/specs/pilot?source=example").json()["source"] == "example"


def test_save_refuses_symlinked_drafts_dir(api, repo, tmp_path):
    out = tmp_path / "elsewhere"
    out.mkdir()
    (repo / "spec" / "drafts").symlink_to(out, target_is_directory=True)
    r = api.post("/api/specs/save", json={"name": "x", "data": _example_data()})
    assert r.status_code == 500 and list(out.iterdir()) == []


def test_save_refuses_symlink_target(api, repo, tmp_path):
    api.post("/api/specs/save", json={"name": "first", "data": _example_data()})
    victim = tmp_path / "victim.yaml"
    victim.write_text("keep")
    link = repo / "spec/drafts/lnk.yaml"
    link.symlink_to(victim)
    r = api.post("/api/specs/save", json={"name": "lnk", "data": _example_data(), "overwrite": True})
    assert r.status_code == 409 and victim.read_text() == "keep"
    assert api.get("/api/specs/lnk").status_code == 404           # symlinks are not served either
    assert "lnk" not in {s["name"] for s in api.get("/api/specs").json()["specs"]}
    assert api.delete("/api/specs/lnk").status_code == 409 and victim.exists()


def test_duplicate_example_to_draft_keeps_hash_and_comments(api, repo):
    ex = api.get("/api/specs/pilot").json()
    r = api.post("/api/specs/pilot/duplicate", json={"new_name": "pilot-mine"})
    assert r.status_code == 200
    j = r.json()
    assert j["spec_hash"] == ex["spec_hash"] and j["path"] == "spec/drafts/pilot-mine.yaml"
    assert (repo / "spec/drafts/pilot-mine.yaml").read_text() == (repo / "spec/examples/pilot.yaml").read_text()
    assert api.post("/api/specs/pilot/duplicate", json={"new_name": "pilot-mine"}).status_code == 409
    assert api.post("/api/specs/pilot/duplicate").json()["name"] == "pilot-copy"
    assert api.post("/api/specs/pilot/duplicate", json={"new_name": "../x"}).status_code == 400
    assert api.post("/api/specs/nonexistent/duplicate").status_code == 404


def test_delete_drafts_only(api, repo):
    api.post("/api/specs/save", json={"name": "gone", "data": _example_data()})
    assert api.delete("/api/specs/gone").json() == {"deleted": True, "name": "gone"}
    assert not (repo / "spec/drafts/gone.yaml").exists()
    assert api.delete("/api/specs/gone").status_code == 404
    assert api.delete("/api/specs/pilot").status_code == 403
    assert (repo / "spec/examples/pilot.yaml").exists()
    assert api.delete("/api/specs/..%2F..%2Fetc").status_code in (400, 404)


def test_token_required(repo, tmp_path):
    from ui_server.app import create_app
    from ui_server.settings import Settings
    s = Settings(repo_root=repo, runs_dir=tmp_path / "runs", token=TOKEN, port=PORT, web_dist=tmp_path / "x")
    with TestClient(create_app(s), base_url=BASE) as c:
        assert c.get("/api/specs").status_code == 401
        assert c.post("/api/specs/save", json={"name": "a", "data": {}}).status_code == 401


def test_path_suggestions(tmp_path):
    from ui_server.app import create_app
    from ui_server.settings import Settings
    s = Settings(repo_root=REAL_REPO, runs_dir=tmp_path / "runs", token=TOKEN, port=PORT, web_dist=tmp_path / "x")
    with TestClient(create_app(s), base_url=BASE) as c:
        c.headers.update(AUTH)
        r = c.get("/api/specs/paths", params={"q": "export_csv/prompt"}).json()
    assert any(p["value"] == "../../fixtures/tasks/export_csv/prompt.md" for p in r["paths"])
    assert all(".." not in p["repo_path"] for p in r["paths"])


# --- the required proof: every example round-trips ------------------------------------------------------------

@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_example_round_trips_with_same_hash(api, repo, path):
    name = path.stem
    original = load_spec(path, repo_root=REAL_REPO)

    got = api.get(f"/api/specs/{name}").json()                      # load -> structured data
    assert got["valid"] and got["spec_hash"] == original.spec_hash
    saved = api.post("/api/specs/save", json={"name": name + "-rt", "data": got["data"]})  # -> draft
    assert saved.status_code == 200, saved.text
    assert saved.json()["spec_hash"] == original.spec_hash

    f = repo / "spec" / "drafts" / f"{name}-rt.yaml"
    assert load_spec(f, repo_root=repo).spec_hash == original.spec_hash   # reload from disk, production loader
    again = api.get(f"/api/specs/{name}-rt").json()                       # reload through the API
    assert again["spec_hash"] == original.spec_hash
    assert again["run_ids"] == got["run_ids"]
    # and the YAML view path: saving the saved YAML text changes nothing
    resaved = api.post("/api/specs/save", json={"name": name + "-rt", "yaml": again["yaml"], "overwrite": True})
    assert resaved.json()["spec_hash"] == original.spec_hash
    assert f.read_text() == again["yaml"]                                  # stable output (idempotent)
    # data equality modulo defaults the model fills in
    from spec.schema import Spec
    assert Spec.model_validate(again["data"]) == Spec.model_validate(got["data"])


def test_all_examples_real_repo_list_valid(tmp_path):
    """Read-only against the real examples dir: every shipped example is valid."""
    from ui_server.app import create_app
    from ui_server.settings import Settings
    s = Settings(repo_root=REAL_REPO, runs_dir=tmp_path / "runs", token=TOKEN, port=PORT, web_dist=tmp_path / "x")
    with TestClient(create_app(s), base_url=BASE) as c:
        c.headers.update(AUTH)
        specs = c.get("/api/specs").json()["specs"]
    ex = [x for x in specs if x["source"] == "example"]
    assert len(ex) == len(EXAMPLES) and all(x["valid"] for x in ex)


def test_prepare_drops_nulls_and_orders_keys():
    d = copy.deepcopy(_example_data())
    d["task"]["stages_file"] = None
    d["agent"]["script"] = ""
    out = ss.prepare(d)
    assert "stages_file" not in out["task"] and "script" not in out["agent"]
    assert list(out)[:2] == ["spec_version", "experiment_id"]
