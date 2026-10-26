"""UH-7: a malformed scorer.jsonl / review-items.json cannot 500 the review API, and one bad run does
not hide the others."""
from __future__ import annotations

import json

import pytest

from tests.unit.ui_server.test_review_api import _ev, make_review_run

BAD_EVENTS = [
    dict(k="1", mode="ED", t_s=10.0, detector="d", evidence="x", pass_id="p"),            # k as a string
    dict(k=1, mode="ED", t_s=10.0, detector="d", evidence={"a": [1, 2]}, pass_id="p"),    # evidence as dict
    dict(k=1, mode="ED", t_s=10.0, detector="d", evidence=["a", {"b": 1}], pass_id="p"),  # evidence as list
    dict(k=1, mode=["x"], t_s="soon", detector={"y": 1}, evidence=None, pass_id={"z": 1}),
    dict(k=None, mode="ED", detector="d"),
    dict(k=[1], mode="ED", detector="d"),
    dict(k=1.5, mode="ED", detector="d"),
    dict(k=True, mode="ED", detector="d"),
    dict(k=1, mode="ED", detector="d", t_s=float("inf"), evidence="e", pass_id="p"),
    dict(k=10**30, mode="ED", detector="d"),
    dict(mode="ED", detector="d"),
    dict(k=1, dimension={"a": 1}, rule=5, t_attributed_s="x", pass_id="p"),
]


def _bad_run(runs_dir, rid="bad-run-A-r00-bbbbbbbb"):
    d = make_review_run(runs_dir, rid)
    lines = [_ev(rid, "scorer.start", 50, k=1, pass_id="p")]
    for i, p in enumerate(BAD_EVENTS):
        lines.append(_ev(rid, "scorer.behavior", 60 + i, **p))
        lines.append(_ev(rid, "scorer.hazard", 90 + i, **p))
    lines.append(_ev(rid, "scorer.done", 99, k=1, pass_id="p", ok=True))
    lines.append('{"type": "scorer.behavior", "payload": 5}')
    lines.append('{"type": "scorer.behavior", "payload": null}')
    lines.append('{"type": "scorer.behavior"}')
    lines.append("[1,2]")
    with open(d / "events" / "scorer.jsonl", "a") as fh:
        fh.write("\n".join(lines) + "\n")
    (d / "review-items.json").write_text(json.dumps({"items": [
        {"id": "a", "k": "x", "t_s": "y", "evidence": {"d": 1}, "title": ["t"], "group": 5, "name": {"n": 1}},
        {"id": "b", "k": 2, "t_s": 3.0},
        {"id": "c", "k": None},
        {"id": "dd", "k": "3"},
        "junk", 5, None, {"id": 5},
    ]}))
    (d / "review-draft.json").write_text(json.dumps({"labels": [{"match": {"k": ["x"]}}, {"match": {"kind": {"a": 1}}}]}))
    return d


def test_malformed_events_never_500(client, runs_dir):
    d = _bad_run(runs_dir)
    r = client.get("/api/review/queue", params={"run_id": d.name, "status": "all", "limit": 1000})
    assert r.status_code == 200, r.text
    for it in r.json()["items"]:
        assert isinstance(it["k"], int) or it["k"] is None
        assert isinstance(it["title"], str) and isinstance(it["group"], str) and isinstance(it["name"], str)
        assert it["t_s"] is None or isinstance(it["t_s"], (int, float))
    assert client.get("/api/review/runs").status_code == 200
    assert client.get("/api/review/queue").status_code == 200


def test_k_as_digit_string_is_coerced_and_junk_dropped(client, runs_dir):
    d = _bad_run(runs_dir)
    items = client.get("/api/review/queue", params={"run_id": d.name, "status": "all", "limit": 1000}).json()["items"]
    scorer = [i for i in items if i["source"] == "scorer_events"]
    assert any(i["k"] == 1 and i["name"] == "d" for i in scorer)
    assert all(not isinstance(i["k"], bool) for i in items)


def test_one_broken_run_does_not_hide_the_others(client, runs_dir, monkeypatch):
    good = make_review_run(runs_dir)
    bad = make_review_run(runs_dir, "bad-run-A-r00-bbbbbbbb")
    from ui_server import review_store as rs
    real = rs.run_items

    def boom(run_dir):
        if run_dir.name == bad.name:
            raise RuntimeError("explode")
        return real(run_dir)

    monkeypatch.setattr(rs, "run_items", boom)
    r = client.get("/api/review/runs")
    assert r.status_code == 200
    rows = {x["run_id"]: x for x in r.json()["runs"]}
    assert rows[good.name]["items"] == 5 and rows[bad.name]["error"]
    q = client.get("/api/review/queue", params={"status": "all"})
    assert q.status_code == 200 and q.json()["total"] == 5
    assert bad.name in q.json().get("errors", {})


def test_unreadable_review_log_is_not_fatal(client, runs_dir):
    d = make_review_run(runs_dir)
    (d / "review.jsonl").write_text('{"item_id": "x", "decision": "weird"}\n{"item_id": 5}\n[1]\nnot json\n')
    r = client.get("/api/review/queue", params={"run_id": d.name, "status": "all"})
    assert r.status_code == 200
    assert r.json()["counts"]["pending"] == 5
    assert client.get("/api/review/history", params={"run_id": d.name}).status_code == 200


@pytest.mark.parametrize("name", ["review-items.json", "review-draft.json"])
def test_hostile_json_documents(client, runs_dir, name):
    d = make_review_run(runs_dir)
    for body in ("[" * 5000, '{"items": 5, "labels": "x"}', "\x00", '{"items": [[]]}'):
        (d / name).write_text(body)
        assert client.get("/api/review/queue", params={"run_id": d.name, "status": "all"}).status_code == 200
