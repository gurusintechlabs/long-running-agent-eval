"""U3: /tests (heatmap data, reuses analysis.degradation) and /timeline."""
from __future__ import annotations

import pytest

from analysis import degradation as dg
from analysis.ingest import ingest
from tests.unit.analysis import synth
from tests.unit.analysis.synth import beh_event, hazard, make_degrading_run, make_run
from tests.unit.ui_server.u3_synth import add_orch, agent_stream, guardrail, snapshot_tree


@pytest.fixture(autouse=True)
def counters(monkeypatch):
    monkeypatch.setattr("telemetry.counters.interval_counters", synth.fake_counters)


@pytest.fixture
def deg(runs_dir):
    rid = make_degrading_run(runs_dir, hazards=[hazard("quality", 1000.0)],
                             behavior_by_k={2: [beh_event("AF", 700.0, "loop"),
                                                beh_event("RH", 900.0, "tamper", hazard=True, dimension="integrity")]})
    return rid


@pytest.fixture
def ingested(deg, runs_dir):
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    return deg


# ------------------------------------------------------------------------------------------- /tests

def test_tests_not_ingested(client, deg):
    body = client.get(f"/api/runs/{deg}/tests").json()
    assert body["ingested"] is False and body["has_outcomes"] is False and "re-ingest" in body["reason"]


def test_tests_without_a_store_at_all(client, deg, runs_dir):
    assert not (runs_dir / "metrics.sqlite").exists()
    assert client.get(f"/api/runs/{deg}/tests").json()["ingested"] is False


def test_tests_matrix_and_flips_match_degradation(client, ingested, runs_dir):
    db = runs_dir / "metrics.sqlite"
    body = client.get(f"/api/runs/{ingested}/tests").json()
    m = dg.load_matrix(db, ingested)
    assert body["ingested"] and body["has_outcomes"] and body["suite"] == "hidden" and body["suites"] == ["hidden"]
    assert [p["t_s"] for p in body["points"]] == [p.t_s for p in m.points]
    assert [t["id"] for t in body["tests"]] == m.tests
    code = {"passed": "p", "failed": "f", "error": "e", "skipped": "s", None: "-"}
    for t in body["tests"]:
        assert t["cells"] == "".join(code[o] for o in m.outcome[t["id"]]) and len(t["cells"]) == len(m.points)
        assert t["tier"] == m.tier[t["id"]]
    flips = [(f["t_s"], f["test_id"], f["kind"]) for f in body["flips"]]
    assert flips == [(f.t_s, f.test_id, f.kind) for f in dg.flip_events(db, ingested)]
    assert any(k == "regression" for _t, _i, k in flips)
    tl = {t["test_id"]: t for t in body["timelines"]}
    for t in dg.timelines(db, ingested):
        assert tl[t.test_id]["regressions"] == t.regressions and tl[t.test_id]["relapsed"] == t.relapsed
    assert body["summary"] == dg.run_summary(db, ingested)
    assert [(s["stage"], s["t_s"]) for s in body["stages"]] == [(0, 0.0), (1, 650.0)]
    assert [c["k"] for c in body["checkpoints"]] == [1, 2, 3]
    assert body["pass_rates"][-1]["overall"] == dg.pass_rates(db, ingested)[-1].overall
    assert body["stage_effects"] == dg.stage_effects(db, ingested)


def test_tests_old_run_without_outcomes(client, runs_dir):
    rid = make_run(runs_dir, repeat=9)
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    b = client.get(f"/api/runs/{rid}/tests").json()
    assert b["ingested"] is True and b["has_outcomes"] is False and b["tests"] == [] and b["flips"] == []


def test_tests_suite_param_is_validated(client, ingested):
    assert client.get(f"/api/runs/{ingested}/tests", params={"suite": "regression"}).status_code == 400
    assert client.get(f"/api/runs/{ingested}/tests", params={"suite": "x" * 100}).status_code == 422
    assert client.get(f"/api/runs/{ingested}/tests", params={"suite": "'; DROP TABLE runs;--"}).status_code == 400


def test_tests_never_modifies_the_store(client, ingested, runs_dir):
    before = (runs_dir / "metrics.sqlite").read_bytes()
    snap = snapshot_tree(runs_dir)
    for _ in range(2):
        assert client.get(f"/api/runs/{ingested}/tests").status_code == 200
    assert (runs_dir / "metrics.sqlite").read_bytes() == before
    assert snapshot_tree(runs_dir) == snap


def test_tests_unknown_run(client):
    assert client.get("/api/runs/nope/tests").status_code == 404


# ----------------------------------------------------------------------------------------- /timeline

@pytest.fixture
def rich(deg, runs_dir):
    rd = runs_dir / deg
    guardrail(rd, deg, [
        (1.0, "guardrail.monitor", {"status": "started"}),
        (60.0, "guardrail.telemetry_stalled", {"reason": "silence", "silence_s": 60.0}),
        (60.1, "guardrail.telemetry_resumed", {"paused_s": 0.1}),
        (120.0, "guardrail.telemetry_stalled", {"reason": "silence", "silence_s": 60.0}),
        (120.2, "guardrail.telemetry_resumed", {"paused_s": 0.2}),
        (300.0, "guardrail.violation", {"rule_id": "other-outside", "severity": "warning", "action": "log",
                                       "channel": "command", "evidence": "Edit.file_path -> /x", "stream_seq": 5}),
        (400.0, "guardrail.violation", {"rule_id": "harness-access", "severity": "violation", "action": "kill",
                                       "channel": "command", "evidence": "cat runs/x " + "E" * 5000}),
        (410.0, "guardrail.budget", {"cost_usd": 4.2, "tokens": 1000, "per_run_usd": 4.0, "per_run_tokens": 5000}),
        (410.5, "guardrail.kill", {"rule_id": "budget", "reason": "budget", "detect_mono_ns": 1_000_000_000,
                                  "frozen_mono_ns": 1_026_000_000, "freeze_latency_ms": 26.0}),
    ])
    agent_stream(rd, deg, [("text", 1, "a"), ("text", 2, "b"), ("compaction", 700, 123456), ("text", 800, "c")])
    add_orch(rd, deg, [(0.05, "turn.start", {"first": True}), (600.0, "turn.end", {"turn": 1, "returncode": 0}),
                       (601.0, "turn.start", {"first": False})])
    return deg


def tl(client, rid):
    r = client.get(f"/api/runs/{rid}/timeline")
    assert r.status_code == 200, r.text
    return r.json()


def test_timeline_core_lanes(client, rich):
    b = tl(client, rich)
    assert [c["k"] for c in b["checkpoints"]] == [1, 2, 3]
    assert [c["t_s"] for c in b["checkpoints"]] == [600.0, 1200.0, 1800.0]
    assert [(s["stage"], s["t_s"]) for s in b["stages"]] == [(0, 0.0), (1, 650.0)]
    assert {(m["kind"], m["label"]) for m in b["markers"]} >= {("stage", "stage 1")}
    assert [h["dimension"] for h in b["hazards"]] == ["quality"] and b["hazards"][0]["t_attributed_s"] == 1000.0
    assert {(x["mode"], x["detector"], x["hazard"]) for x in b["behavior"]} == {("AF", "loop", False),
                                                                                ("RH", "tamper", True)}
    assert b["compactions"] == [{"cursor": b["compactions"][0]["cursor"], "t_s": 700.0, "trigger": "auto",
                                 "pre_tokens": 123456}]
    assert b["compactions"][0]["cursor"].startswith("agent_stream:")
    assert [t["turn"] for t in b["turns"]] == [1, 2]
    assert b["end"]["state"] == "COMPLETED"


def test_timeline_cursors_resolve_to_events(client, rich):
    b = tl(client, rich)
    for c in (b["checkpoints"][0], b["compactions"][0], b["guardrail"]["kill"]):
        r = client.get(f"/api/runs/{rich}/events/at", params={"cursor": c["cursor"]})
        assert r.status_code == 200, c


def test_timeline_guardrail_safety_panel_data(client, rich):
    g = tl(client, rich)["guardrail"]
    assert g["status"] == "killed"
    assert g["kill"]["rule_id"] == "budget" and g["kill"]["t_s"] == 410.5 and g["kill"]["detect_to_freeze_ms"] == 26.0
    assert [v["rule_id"] for v in g["violations"]] == ["other-outside", "harness-access"]
    assert g["violations"][0]["t_s"] == 300.0 and g["violations_total"] == 2
    assert len(g["violations"][1]["evidence"]) < 700 and "truncated" in g["violations"][1]["evidence"]
    assert g["budget"]["per_run_usd"] == 4.0 and g["budget"]["t_s"] == 410.0
    assert {r["rule_id"] for r in g["by_rule"]} == {"other-outside", "harness-access", "budget"}
    assert g["telemetry_stalls"]["count"] == 2 and g["telemetry_stalls"]["resumed"] == 2
    assert [x["paused_s"] for x in g["telemetry_stalls"]["gaps"]] == [0.1, 0.2]


def test_timeline_violation_links_to_the_stream_line(client, rich):
    v = tl(client, rich)["guardrail"]["violations"][0]
    assert v["stream_seq"] == 5 and v["stream_cursor"].startswith("agent_stream:")
    e = client.get(f"/api/runs/{rich}/events/at", params={"cursor": v["stream_cursor"]}).json()["event"]
    assert e["seq"] == 5


def test_timeline_counters_from_logs_then_store(client, rich, runs_dir):
    b = tl(client, rich)
    assert b["source_of_counters"] == "logs" and len(b["series"]) == 3
    assert b["series"][1]["context_fill_max"] == pytest.approx(0.2) and b["series"][1]["compactions"] == 1
    ingest(runs_dir, runs_dir / "metrics.sqlite")
    b2 = tl(client, rich)
    assert b2["source_of_counters"] == "store"          # the store's mtime changed: cache was invalidated
    assert [s["cum_cost_usd"] for s in b2["series"]] == pytest.approx([0.25, 0.5, 0.75])


def test_timeline_for_a_plain_run_without_optional_files(client, runs_dir):
    rid = make_run(runs_dir, n_cp=2)
    b = tl(client, rid)
    assert b["guardrail"]["status"] == "clear" and b["guardrail"]["kill"] is None
    assert b["compactions"] == [] and [c["k"] for c in b["checkpoints"]] == [1, 2]


def test_timeline_is_cached_until_a_file_changes(client, rich, runs_dir):
    a = tl(client, rich)
    assert tl(client, rich) == a
    guardrail(runs_dir / rich, rich, [(5.0, "guardrail.violation", {"rule_id": "z", "severity": "warning"})])
    b = tl(client, rich)
    assert b["guardrail"]["violations_total"] == 1 and b != a


def test_timeline_no_writes_and_404(client, rich, runs_dir):
    snap = snapshot_tree(runs_dir)
    tl(client, rich)
    assert snapshot_tree(runs_dir) == snap
    assert client.get("/api/runs/..%2f/timeline").status_code == 404
