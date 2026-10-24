"""UH-1: one predicate decides whether a spec spends, used by launch, resume and re-score."""
from __future__ import annotations

import copy
import json
import typing
from pathlib import Path

import pytest
import yaml

from spec.loader import load_spec
from tests.unit.analysis.synth import make_run
from tests.unit.ui_server.test_control import build_rig, preview
from ui_server import spend

REPO = Path(__file__).resolve().parents[3]
EXAMPLES = sorted((REPO / "spec" / "examples").glob("*.yaml"))


def _spec(**over):
    """A synthetic validated Spec from the scripted pilot with dotted-path overrides."""
    raw = copy.deepcopy(yaml.safe_load((REPO / "spec/examples/pilot-scripted.yaml").read_text()))
    for dotted, v in over.items():
        d = raw
        *head, last = dotted.split(".")
        for h in head:
            d = d.setdefault(h, {})
        d[last] = v
    from spec.schema import Spec
    return Spec.model_validate(raw)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_every_example_matches_a_hand_rule(path):
    s = load_spec(path, repo_root=REPO).spec
    sec = s.scoring.security
    expect = (s.agent.runtime != "scripted" or s.scoring.judge_runtime != "scripted"
              or (sec.enabled and sec.ai_review and sec.ai_review_runtime != "scripted"))
    assert bool(spend.spend_reasons(s)) is bool(expect)


SEC = {"scoring.security.enabled": True, "scoring.security.ai_review": True,
       "scoring.security.context_file": "x.yaml"}
SYNTH = [
    ({}, False),
    ({"agent.runtime": "claude_code", "agent.model": "claude-opus-5-5", "agent.script": None}, True),
    ({"scoring.judge_runtime": "claude_code"}, True),
    # the schema default for ai_review_runtime is claude_code: enabling the review alone spends
    (SEC, True),
    ({**SEC, "scoring.security.ai_review_runtime": "scripted"}, False),
    ({**SEC, "scoring.security.enabled": False}, False),     # the scorer only reviews when enabled
    ({"scoring.security.enabled": True, "scoring.security.ai_review": False}, False),
    ({"scoring.behavior.enabled": True}, False),             # deterministic detectors; judges follow judge_runtime
    ({"scoring.behavior.enabled": True, "scoring.judge_runtime": "claude_code"}, True),
]


@pytest.mark.parametrize("over,spends", SYNTH)
def test_synthetic_variants(over, spends):
    assert bool(spend.spend_reasons(_spec(**over))) is spends


def test_security_review_reason_is_named():
    assert any("security" in r for r in spend.spend_reasons(_spec(**SEC)))


def _runtime_typed_fields(model, prefix=""):
    out = set()
    for name, f in model.model_fields.items():
        ann = f.annotation
        args = typing.get_args(ann)
        if "claude_code" in args or "runtime" in name:
            out.add(prefix + name)
        for a in (ann, *args):
            if isinstance(a, type) and hasattr(a, "model_fields"):
                out |= _runtime_typed_fields(a, prefix + name + ".")
    return out


def test_new_runtime_field_must_be_classified():
    """A new claude_code-capable field in spec/schema.py fails here until spend.py classifies it."""
    from spec.schema import Spec
    found = _runtime_typed_fields(Spec)
    assert found == set(spend.CLASSIFIED_RUNTIME_FIELDS), (
        f"runtime-typed fields differ from ui_server/spend.py: {found ^ set(spend.CLASSIFIED_RUNTIME_FIELDS)}")


def _sec_spec(rig):
    raw = yaml.safe_load(rig.spec.read_text())
    raw["scoring"]["security"] = {"enabled": True, "ai_review": True, "context_file": "../assets/ctx.yaml"}
    (rig.r["assets"] / "ctx.yaml").write_text("app: x\n")
    rig.spec.write_text(yaml.safe_dump(raw))


def test_preview_flags_security_review_spend(tmp_path):
    rig = build_rig(tmp_path)
    _sec_spec(rig)
    est = preview(rig).json()["estimate"]
    assert est["real_spend"] is True
    assert any("security" in r for r in est["spend_reasons"])


def test_score_refuses_security_review_spend(tmp_path):
    rig = build_rig(tmp_path)
    _sec_spec(rig)
    rid = make_run(rig.r["runs"], experiment="ctl-test", repeat=0, n_cp=1)
    mp = rig.r["runs"] / rid / "manifest.json"
    m = json.loads(mp.read_text())
    m["spec_path"] = str(rig.spec)
    mp.write_text(json.dumps(m))
    r = rig.c.post(f"/api/runs/{rid}/score", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "judge_spends"
    assert rig.spawner.calls == []


def test_score_applies_the_spec_root_allowlist(tmp_path):
    rig = build_rig(tmp_path)
    outside = tmp_path / "elsewhere.yaml"
    outside.write_text(rig.spec.read_text())
    rid = make_run(rig.r["runs"], experiment="ctl-test", repeat=0, n_cp=1)
    mp = rig.r["runs"] / rid / "manifest.json"
    m = json.loads(mp.read_text())
    m["spec_path"] = str(outside)
    mp.write_text(json.dumps(m))
    r = rig.c.post(f"/api/runs/{rid}/score", json={})
    assert r.status_code == 403 and rig.spawner.calls == []


# -- finding 2: an honest worst case ---------------------------------------------------------------

@pytest.mark.parametrize("n,per,cap,spent,worst,nominal", [
    (2, 3.0, 5.0, 0.0, 6.0, 5.0),     # the second run starts at $3 < $5 and can end at $6
    (2, 3.0, 6.0, 0.0, 6.0, 6.0),
    (3, 3.0, 5.0, 0.0, 6.0, 5.0),     # a third never starts: $6 >= $5
    (1, 3.0, 5.0, 0.0, 3.0, 3.0),
    (2, 3.0, 5.0, 4.0, 3.0, 5.0),     # only one more run can start
    (2, 3.0, 5.0, 5.0, 0.0, 5.0),     # cap reached: the CLI starts nothing
])
def test_worst_case_formula(n, per, cap, spent, worst, nominal):
    from ui_server.control_core import worst_case_usd
    assert worst_case_usd(n, per, cap, spent) == (worst, nominal)


def test_worst_case_uses_spent_from_manifests(tmp_path):
    rig = build_rig(tmp_path)
    assert preview(rig).json()["estimate"]["max_spend_usd"] == 6.0
    rid = make_run(rig.r["runs"], experiment="ctl-test", repeat=0, n_cp=1)
    h = load_spec(rig.spec, repo_root=rig.r["repo"]).spec_hash
    mp = rig.r["runs"] / rid / "manifest.json"
    m = json.loads(mp.read_text())
    m.update(experiment_id="ctl-test", spec_hash=h, end={"state": "COMPLETED", "cost_usd": 4.0})
    mp.write_text(json.dumps(m))
    e = preview(rig).json()["estimate"]
    assert e["spent_so_far_usd"] == 4.0 and e["max_spend_usd"] == 3.0 and e["nominal_cap_usd"] == 5.0


def test_estimate_names_paths_outside_the_hash(tmp_path):
    rig = build_rig(tmp_path)
    e = preview(rig).json()["estimate"]
    assert set(e["outside_spec_hash"]) == {"work_dir", "seed_repo", "prompt_file"}
    assert "max_spend_basis" in e
