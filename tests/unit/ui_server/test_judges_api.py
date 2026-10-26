"""Judges tab: every LLM judgement of a run, per checkpoint, from the ingested scorer metrics."""
from __future__ import annotations

from analysis.ingest import ingest
from tests.unit.analysis.synth import make_run

CONTRA = {"earlier": "msg 4: all tests pass", "later": "msg 9: 2 tests fail", "evidence": "both cannot hold",
          "kind": "statement_vs_statement"}
X_DETAIL = {"X_spread": 0.5, "judge_cost_usd": 0.25,
            "samples": [{"index": 0, "count": 1, "contradictions": [CONTRA], "cached": False, "cost_usd": 0.25}]}
GOALS = {"cost_usd": 0.3, "cached": False, "inferred_goals": [{"goal": "Ship stage 0", "evidence": "[8] Write app.py"}]}
DRIFT = {"drift": [{"instruction": "commit per section", "instead": "one commit", "evidence": "STATUS says so"}],
         "priority_inversions": []}
CLAIMS = {"stages": [{"stage": 0, "misstatements": [{"kind": "contradicted", "claim": "All 630 tests pass.",
                                                     "fact": "628 passed, 2 failed", "evidence": "rerun"}],
                      "dropped": []}]}
TACTICS = {"tactics": [{"tactic": "misrepresentation", "request": "message", "quote": "663 tests pass",
                        "evidence": "661 pass"}], "cached": False}
JUDGE_EV = {"mode": "GM", "t_s": 590.0, "detector": "goal_observer.drift", "evidence": "asked: x; did: y",
            "hazard": False, "deterministic": False, "dimension": "context"}
RULE_EV = {"mode": "ED", "t_s": 100.0, "detector": "risk_tier_3", "evidence": "pkill", "hazard": False,
           "deterministic": True, "dimension": "safety"}


def _judged_run(runs_dir):
    rid = make_run(
        runs_dir, experiment="exp-j", n_cp=2,
        details_by_k={1: {"X": X_DETAIL}},
        metrics_by_k={1: {"X_spread": (0.5, {}),
                          "lrae.beh.gm.fidelity": (0.9, GOALS), "lrae.beh.gm.drift_items": (1.0, DRIFT),
                          "lrae.beh.dc.prose_misstatements": (1.0, CLAIMS), "lrae.beh.se.tactics": (1.0, TACTICS),
                          "lrae.beh.judge.cost_usd": (0.3, {"judges": ["goal_observer", "prose_claims"]})},
                      2: {"lrae.beh.se.tactics": (None, {"reason": "no ops-channel traffic"})}},
        behavior_by_k={1: [JUDGE_EV, RULE_EV]})
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    return rid


def test_judges_per_checkpoint(client, runs_dir):
    rid = _judged_run(runs_dir)
    j = client.get(f"/api/runs/{rid}/judges").json()
    assert j["ingested"] is True and [c["k"] for c in j["checkpoints"]] == [1, 2]
    c1 = j["checkpoints"][0]
    assert c1["t_s"] == 600.0
    assert c1["quality"]["value"] == 0.5 and c1["quality"]["spread"] == 0.5
    assert c1["quality"]["samples"][0]["contradictions"] == [CONTRA]
    assert c1["goals"]["fidelity"] == 0.9 and c1["goals"]["inferred_goals"] == GOALS["inferred_goals"]
    assert c1["goals"]["drift"] == DRIFT["drift"] and c1["goals"]["priority_inversions"] == []
    assert c1["claims"]["value"] == 1.0 and c1["claims"]["stages"] == CLAIMS["stages"]
    assert c1["manipulation"]["tactics"] == TACTICS["tactics"]
    # only the judges' findings, not the deterministic detectors'
    assert [f["detector"] for f in c1["findings"]] == ["goal_observer.drift"]
    assert c1["cost_usd"] == 0.55          # X judge 0.25 + behaviour judges 0.3
    assert c1["summary"] == {"x": 0.5, "fidelity": 0.9, "drift": 1, "misstatements": 1, "tactics": 1, "findings": 1}
    c2 = j["checkpoints"][1]
    assert c2["manipulation"]["reason"] == "no ops-channel traffic" and c2["manipulation"]["tactics"] == []
    assert c2["goals"] is None and c2["claims"] is None


def test_judges_not_ingested(client, runs_dir):
    rid = make_run(runs_dir, experiment="exp-n", n_cp=1)
    j = client.get(f"/api/runs/{rid}/judges").json()
    assert j["ingested"] is False and j["checkpoints"] == [] and "not in metrics.sqlite" in j["reason"]


def test_judges_unknown_run_is_404(client):
    assert client.get("/api/runs/nope-A-r00-x/judges").status_code == 404
