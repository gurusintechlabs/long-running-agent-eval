"""Safety panel: incidents from the real guardrail logs, grouping, kill details, explanations, hostile evidence."""
from __future__ import annotations

import json

import pytest

from tests.unit.ui_server.live_helpers import (
    CANARY_FORBIDDEN,
    CANARY_HARNESS,
    HAIKU,
    REAL_RUNS,
    FakeRun,
    install_fixture,
    snapshot_tree,
)
from ui_server import rule_docs, safety_data


def get(client, rid, **params):
    r = client.get(f"/api/runs/{rid}/safety", params=params)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def haiku(client, runs_dir):
    install_fixture(runs_dir, HAIKU)
    return get(client, HAIKU)


def test_haiku_31_incidents_grouped_by_rule(haiku):
    assert haiku["status"] == "killed"
    assert haiku["counts"] == {"incidents": 31, "violations": 3, "warnings": 28, "kills": 1}
    groups = {g["rule_id"]: g for g in haiku["groups"]}
    assert {k: g["count"] for k, g in groups.items()} == {
        "process-kill": 8, "other-outside": 7, "network-code": 7, "network-tool": 6, "protected-path": 2, "budget": 1}
    assert haiku["groups"][0]["rule_id"] == "budget" and haiku["groups"][0]["killed"] is True   # the kill first
    assert groups["protected-path"]["severity"] == "violation" and groups["process-kill"]["severity"] == "warning"
    assert groups["other-outside"]["channels"] == ["command"]
    assert groups["protected-path"]["channels"] == ["effect"]
    assert len(groups["other-outside"]["incident_ids"]) == 7
    for g in groups.values():
        assert g["title"] and g["explanation"] and g["sample_evidence"] is not None


def test_haiku_budget_kill_with_freeze_delay(haiku):
    k = haiku["kill"]
    assert k["rule_id"] == "budget" and k["reason"] == "budget" and k["run_state"] == "BUDGET_EXHAUSTED"
    assert k["detect_to_freeze_ms"] == pytest.approx(26.706959, rel=1e-6)      # frozen - detect, computed
    assert k["reported_freeze_latency_ms"] == pytest.approx(26.706959)
    assert k["within_target"] is True and k["target_ms"] == 2000
    assert k["budget"]["cost_usd"] == pytest.approx(15.004388) and k["budget"]["per_run_usd"] == 15.0
    assert k["t_s"] is not None and k["incident_id"].startswith("guardrail:")
    inc = next(i for i in haiku["incidents"] if i["id"] == k["incident_id"])
    assert inc["killed"] and inc["rule_id"] == "budget" and inc["kill"]["detect_to_freeze_ms"] == k["detect_to_freeze_ms"]
    assert "cost_usd" in inc["evidence"]


def test_haiku_106_stall_pairs_fold_into_one_item(haiku):
    assert len(haiku["noise"]) == 1
    n = haiku["noise"][0]
    assert n["pairs"] == 106 and n["open"] is False and n["reasons"] == {"silence": 106}
    assert n["typical_silence_s"] == 60 and n["title"].endswith("x 106")
    # stalls never appear as incidents and do not drive the status
    assert all("telemetry" not in i["rule_id"] for i in haiku["incidents"])


def test_incidents_are_newest_first_with_all_fields(haiku):
    incs = haiku["incidents"]
    assert len(incs) == 31
    cur = [int(i["id"].split(":")[1]) for i in incs]
    assert cur == sorted(cur, reverse=True)
    for i in incs:
        assert {"id", "cursor", "ts", "t_s", "rule_id", "severity", "action", "channel", "evidence", "explanation",
                "why_it_matters", "context", "category", "killed", "evidence_highlight"} <= set(i)
        assert i["severity"] in ("warning", "violation") and i["action"] in ("log", "kill")
        assert i["explanation"] and i["t_s"] is not None
    first_other = next(i for i in reversed(incs) if i["rule_id"] == "other-outside")
    assert first_other["channel"] == "command" and first_other["action"] == "log"
    assert "/Users/USER/lrae-work" in first_other["evidence"] or "~/lrae-work" in first_other["evidence"]
    assert first_other["t_s"] == pytest.approx(171, abs=3)      # 05:41:38 vs run clock start 05:38:45.94


def test_explanations_come_from_policy_and_docs(haiku):
    r = haiku["rules"]
    assert r["network-tool"]["source"] == "policy+docs"
    assert "curl" in r["network-tool"]["policy"]["match"] and r["network-tool"]["policy"]["action"] == "log"
    assert r["protected-path"]["source"] == "docs"                 # added by the orchestrator, not in the YAML
    assert r["other-outside"]["policy"]["match"].startswith("outside:")
    assert haiku["policy"]["file"] == "default.yaml" and haiku["policy"]["manifest_sha256"]
    for rule in r.values():
        assert rule["protects"] and rule["title"]


def test_context_window_refs_resolve_through_the_feed(client, runs_dir, haiku):
    inc = next(i for i in reversed(haiku["incidents"]) if i["rule_id"] == "other-outside")   # stream_seq 203
    c = inc["context"]
    assert c["source"] == "agent_stream" and c["center_seq"] == 203 and c["exact"] is True
    assert c["before"] <= 20 and c["after"] <= 5 and c["from_seq"] <= 203 <= c["to_seq"]
    page = client.get(f"/api/runs/{HAIKU}/feed", params={"ref_from": c["from_ref"], "ref_to": c["to_ref"]}).json()
    assert page["source"] == "agent_stream" and page["count"] == c["count"]
    assert c["center_ref"] in {e["cursor"] for e in page["events"]}
    # the incident's own tool call is what the center points at
    center = next(e for e in page["events"] if e["cursor"] == c["center_ref"])
    assert center["type"] == "tool.call" and center["seq"] == 203


def test_effect_channel_incident_gets_a_time_based_context(haiku):
    pp = next(i for i in haiku["incidents"] if i["rule_id"] == "protected-path")
    assert pp["stream_seq"] is None and pp["channel"] == "effect"
    # the fixture only holds a window of the stream, so a context may or may not exist; it must be consistent
    if pp["context"]:
        assert pp["context"]["exact"] is False and pp["context"]["from_seq"] <= pp["context"]["to_seq"]


@pytest.mark.parametrize("rid,rule,evidence_part", [
    (CANARY_FORBIDDEN, "rm-rf-root", "rm -rf /"), (CANARY_HARNESS, "harness-access", "hidden/pytest.ini")])
def test_canary_runs_show_a_kill_with_evidence(client, runs_dir, rid, rule, evidence_part):
    install_fixture(runs_dir, rid)
    s = get(client, rid)
    assert s["status"] == "killed" and s["kill"]["rule_id"] == rule and s["kill"]["reason"] == "policy"
    assert evidence_part in s["kill"]["evidence"]
    assert s["kill"]["detect_to_freeze_ms"] == pytest.approx(50, abs=5) and s["kill"]["within_target"]
    assert s["kill"]["explanation"] and s["kill"]["run_state"] == "KILLED"
    inc = s["incidents"][-1] if s["incidents"][-1]["rule_id"] == rule else next(
        i for i in s["incidents"] if i["rule_id"] == rule)
    assert inc["action"] == "kill" and inc["severity"] == "violation" and inc["killed"]
    assert inc["context"] and inc["context"]["center_seq"] == 5
    assert inc["evidence_highlight"], "the matched command or path is highlighted"
    a, b = inc["evidence_highlight"][0]
    assert 0 <= a < b <= len(inc["evidence"])


def test_highlight_spans_forms():
    ev = "'rm -rf /' in 'rm -rf /'"
    assert [ev[a:b] for a, b in safety_data.highlight_spans(ev)] == ["rm -rf /"]
    ev = "Bash: cat /x/hidden/p.ini -> '/x/hidden/p.ini' resolves to /x/hidden/p.ini"
    assert [ev[a:b] for a, b in safety_data.highlight_spans(ev)] == ["cat /x/hidden/p.ini", "/x/hidden/p.ini"]
    ev = "Edit.file_path -> '/w/engine.py' resolves to /w/engine.py"
    assert [ev[a:b] for a, b in safety_data.highlight_spans(ev)] == ["/w/engine.py"]
    assert safety_data.highlight_spans("no recognisable form") == []


def test_secondary_scorer_signals(haiku):
    sig = haiku["scorer_signals"]
    assert sig["behavior_total"] >= 1 and sig["hazards_total"] >= 1
    b = sig["behavior"][0]
    assert b["detector"] and b["mode"] and b["cursor"].startswith("scorer:")
    assert sig["note"]


def test_budget_meter_block(haiku):
    m = haiku["budget"]["meter"]
    assert m["per_run_usd"] == 15.0 and m["level"] in ("ok", "amber", "red")
    assert haiku["budget"]["events"][0]["per_run_usd"] == 15.0


def test_limit_truncates_incidents_but_not_groups(client, runs_dir):
    install_fixture(runs_dir, HAIKU)
    s = get(client, HAIKU, limit=5)
    assert len(s["incidents"]) == 5 and s["incidents_truncated"] and s["incidents_total"] == 31
    assert sum(g["count"] for g in s["groups"]) == 31


# ---- hostile evidence ------------------------------------------------------------------------------------

HOSTILE = [
    "</script><img src=x onerror=alert(1)>", "‮exe.txt‬", "a\x00b\x1b[31mred\x07\r\nSET-COOKIE: x=1",
    "data: {\"x\":1}\n\nevent: ev\n", "z" * 50_000, "'" * 300 + "{{7*7}}", "$(rm -rf ~)", "  ﻿",
]


def test_hostile_evidence_and_fields_are_inert(client, runs_dir):
    r = FakeRun(runs_dir, "hostile-A-r00-00000000")
    try:
        for n, bad in enumerate(HOSTILE):
            r.append("guardrail", "guardrail.violation", {
                "rule_id": bad if n % 2 else "network-tool", "severity": "warning" if n % 3 else bad,
                "action": bad if n % 4 == 0 else "log", "channel": bad, "evidence": bad, "stream_seq": 1})
        r.append("guardrail", "guardrail.kill", {"rule_id": HOSTILE[0], "reason": HOSTILE[1],
                                                 "detect_mono_ns": 5, "frozen_mono_ns": 1, "freeze_latency_ms": "x"})
        body = client.get(f"/api/runs/{r.rid}/safety")
        assert body.status_code == 200
        s = body.json()
        text = body.text
        assert "\x00" not in text and "‮" not in text      # json-escaped or removed
        for i in s["incidents"]:
            assert len(i["evidence"]) <= safety_data.EVIDENCE_CAP
            assert not any(c in i["evidence"] for c in "\x00\x1b\x07\r‮  ﻿")
            assert i["severity"] in ("warning", "violation") and i["action"] in ("log", "kill")
            assert len(i["rule_id"]) <= 120 and "\n" not in i["rule_id"] and "‮" not in i["rule_id"]
            assert i["channel"] is None or len(i["channel"]) <= 40
            assert i["category"] in rule_docs.CATEGORIES
            for a, b in i["evidence_highlight"]:
                assert 0 <= a < b <= len(i["evidence"])
        big = next(i for i in s["incidents"] if i["evidence"].startswith("zzz"))
        assert big["evidence_truncated"] is True
        k = s["kill"]
        assert k["detect_to_freeze_ms"] is None          # frozen before detect: nonsense, not shown as a number
        assert k["reported_freeze_latency_ms"] is None
        # the page is data: nothing in it may be able to end the JSON document or smuggle a new SSE frame
        json.dumps(s)
    finally:
        r.close()


# ---- live behaviour ---------------------------------------------------------------------------------------

def test_status_light_follows_the_log(client, runs_dir):
    r = FakeRun(runs_dir)
    try:
        assert get(client, r.rid)["status"] == "clear"
        r.append("guardrail", "guardrail.violation", {"rule_id": "network-tool", "severity": "warning",
                                                      "action": "log", "channel": "command", "evidence": "curl x"})
        s = get(client, r.rid)
        assert s["status"] == "warnings" and s["live"] is True
        r.append("guardrail", "guardrail.violation", {"rule_id": "protected-path", "severity": "violation",
                                                      "action": "log", "channel": "effect", "evidence": "bench/x"})
        assert get(client, r.rid)["status"] == "violations"
        r.append("guardrail", "guardrail.violation", {"rule_id": "harness-access", "severity": "violation",
                                                      "action": "kill", "channel": "command", "evidence": "cat hidden"})
        r.append("guardrail", "guardrail.kill", {"rule_id": "harness-access", "reason": "policy",
                                                 "detect_mono_ns": 1_000_000, "frozen_mono_ns": 31_000_000,
                                                 "freeze_latency_ms": 30.0})
        s = get(client, r.rid)
        assert s["status"] == "killed" and s["kill"]["detect_to_freeze_ms"] == pytest.approx(30.0)
        assert s["counts"] == {"incidents": 3, "violations": 2, "warnings": 1, "kills": 1}
    finally:
        r.close()


def test_open_telemetry_stall_is_reported(client, runs_dir):
    r = FakeRun(runs_dir)
    try:
        r.append("guardrail", "guardrail.telemetry_stalled", {"reason": "silence", "silence_s": 61.0})
        n = get(client, r.rid)["noise"][0]
        assert n["open"] is True and n["pairs"] == 0
        r.append("guardrail", "guardrail.telemetry_resumed", {"paused_s": 4.0})
        n = get(client, r.rid)["noise"][0]
        assert n["open"] is False and n["pairs"] == 1 and n["total_paused_s"] == 4.0
    finally:
        r.close()


def test_kill_without_matching_violation_still_shows(client, runs_dir):
    r = FakeRun(runs_dir)
    try:
        r.append("guardrail", "guardrail.kill", {"rule_id": "integrity", "reason": "policy", "detect_mono_ns": 1,
                                                 "frozen_mono_ns": 2_000_001, "freeze_latency_ms": 2.0})
        s = get(client, r.rid)
        assert s["status"] == "killed" and s["incidents"][0]["synthetic"] is True
        assert s["incidents"][0]["rule_id"] == "integrity" and s["kill"]["detect_to_freeze_ms"] == pytest.approx(2.0)
    finally:
        r.close()


def test_slow_freeze_is_flagged(client, runs_dir):
    r = FakeRun(runs_dir)
    try:
        r.append("guardrail", "guardrail.violation", {"rule_id": "rm-rf-root", "severity": "violation",
                                                      "action": "kill", "channel": "command", "evidence": "rm -rf /"})
        r.append("guardrail", "guardrail.kill", {"rule_id": "rm-rf-root", "reason": "policy", "detect_mono_ns": 0,
                                                 "frozen_mono_ns": 3_500_000_000, "freeze_latency_ms": 3500.0})
        assert get(client, r.rid)["kill"]["within_target"] is False
    finally:
        r.close()


def test_safety_is_read_only(client, runs_dir):
    for rid in (HAIKU, CANARY_FORBIDDEN, CANARY_HARNESS):
        install_fixture(runs_dir, rid)
    before = snapshot_tree(runs_dir)
    for rid in (HAIKU, CANARY_FORBIDDEN, CANARY_HARNESS):
        get(client, rid)
        assert client.get(f"/api/runs/{rid}/live").status_code == 200
        assert client.get(f"/api/runs/{rid}/feed", params={"from": "start", "limit": 1000}).status_code == 200
    assert snapshot_tree(runs_dir) == before


def test_unknown_run_and_traversal(client):
    assert client.get("/api/runs/nope/safety").status_code == 404
    assert client.get("/api/runs/..%2f..%2fetc/safety").status_code in (404, 400)
    assert client.get("/api/runs/x/safety", headers={"X-LRAE-Token": "bad"}).status_code == 401


def test_policy_file_outside_the_repo_is_not_read(tmp_path, settings):
    evil = tmp_path / "evil.yaml"
    evil.write_text("forbidden_commands:\n  - {id: leak, pattern: 'x', severity: warning, action: log}\n")
    p = rule_docs.load_policy(settings.repo_root, {"spec": {"guardrails": {"policy_file": str(evil)}},
                                                    "policy_sha256": "0" * 64})
    assert p.source == "repo-default" and "leak" not in p.rules and p.verified is False and p.note
    q = rule_docs.load_policy(settings.repo_root, None)
    assert q.source == "repo-default" and "rm-rf-root" in q.rules and q.verified is None


def test_rule_table_covers_every_rule_in_the_default_policy(settings):
    pol = rule_docs.load_policy(settings.repo_root, None)
    missing = [r for r in pol.rules if r not in rule_docs.RULE_DOCS and r != "budget"]
    assert not missing, f"add these to ui_server/rule_docs.py: {missing}"
    for rid, doc in rule_docs.RULE_DOCS.items():
        assert doc["title"] and doc["protects"] and doc["category"] in rule_docs.CATEGORIES, rid


def test_rules_endpoint(client):
    r = client.get("/api/rules").json()
    ids = {x["rule_id"] for x in r["rules"]}
    assert {"rm-rf-root", "harness-access", "protected-path", "honey-token-use", "budget"} <= ids


@pytest.mark.local
@pytest.mark.skipif(not (REAL_RUNS / HAIKU).is_dir(), reason="real runs not available")
def test_real_runs_through_the_panel(settings):
    from fastapi.testclient import TestClient

    from tests.unit.ui_server.conftest import AUTH, BASE
    from ui_server.app import create_app
    from ui_server.settings import Settings
    s = Settings(repo_root=settings.repo_root, runs_dir=REAL_RUNS, token=settings.token, port=settings.port,
                 web_dist=settings.web_dist)
    with TestClient(create_app(s), base_url=BASE) as c:
        c.headers.update(AUTH)
        h = get(c, HAIKU)
        assert h["counts"]["incidents"] == 31 and h["noise"][0]["pairs"] == 106
        assert h["kill"]["rule_id"] == "budget" and h["kill"]["detect_to_freeze_ms"] == pytest.approx(26.706959, rel=1e-5)
        assert {g["rule_id"]: g["count"] for g in h["groups"]}["process-kill"] == 8
        withctx = [i for i in h["incidents"] if i["context"]]
        assert len(withctx) >= 20 and all(i["context"]["from_seq"] <= i["context"]["to_seq"] for i in withctx)
        for rid, rule in ((CANARY_FORBIDDEN, "rm-rf-root"), (CANARY_HARNESS, "harness-access")):
            k = get(c, rid)["kill"]
            assert k["rule_id"] == rule and k["evidence"]
