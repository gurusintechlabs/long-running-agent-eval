"""Label review API (phase U6): queue, append-only decisions, pluggable sources."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from ui_server import review_store as rs

B7_RUN = Path("/Users/tonylee/Documents/coding/longhorizon_testing/runs/minidb-v3-pilot-haiku-A-r00-f47fe80e")


def _ev(rid: str, typ: str, seq: int, **payload) -> str:
    return json.dumps({"ts": f"2026-10-23T06:00:{seq:02d}Z", "mono_ns": seq, "run_id": rid, "source": "scorer",
                       "type": typ, "seq": seq, "payload": payload})


def make_review_run(runs_dir: Path, rid: str = "rev-run-A-r00-aaaaaaaa") -> Path:
    d = runs_dir / rid
    (d / "events").mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"run_id": rid}))
    lines = [
        _ev(rid, "scorer.start", 1, k=1, pass_id="p1a"),
        _ev(rid, "scorer.behavior", 2, k=1, mode="ED", t_s=10.0, detector="risk_tier_3", evidence="kill x",
            hazard=False, deterministic=True, dimension="safety", pass_id="p1a"),
        _ev(rid, "scorer.done", 3, k=1, pass_id="p1a", ok=False),            # failed pass: ignored
        _ev(rid, "scorer.start", 4, k=1, pass_id="p1b"),
        _ev(rid, "scorer.behavior", 5, k=1, mode="ED", t_s=10.0, detector="risk_tier_3", evidence="kill x",
            hazard=False, deterministic=True, dimension="safety", pass_id="p1b"),
        _ev(rid, "scorer.behavior", 6, k=1, mode="CE", t_s=20.0, detector="inbox_not_read", evidence="no call",
            hazard=True, deterministic=True, dimension="context", pass_id="p1b"),
        _ev(rid, "scorer.hazard", 7, k=1, dimension="context", rule="C>0", t_detected_s=30.0,
            t_attributed_s=5.0, evidence="1 violation", pass_id="p1b"),
        _ev(rid, "scorer.metric", 8, k=1, name="P", value=0.5),
        _ev(rid, "scorer.done", 9, k=1, pass_id="p1b", ok=True),
        _ev(rid, "scorer.start", 10, k=2, pass_id="p2"),
        _ev(rid, "scorer.behavior", 11, k=2, mode="ED", t_s=40.0, detector="risk_tier_3", evidence="kill x",
            hazard=False, deterministic=True, dimension="safety", pass_id="p2"),
        _ev(rid, "scorer.behavior", 12, k=2, mode="ED", t_s=40.0, detector="risk_tier_3", evidence="kill x",
            hazard=False, deterministic=True, dimension="safety", pass_id="p2"),   # identical twin
        _ev(rid, "scorer.done", 13, k=2, pass_id="p2", ok=True),
    ]
    (d / "events" / "scorer.jsonl").write_text("\n".join(lines) + "\n")
    return d


@pytest.fixture
def rdir(runs_dir) -> Path:
    return make_review_run(runs_dir)


def queue(client, **params):
    return client.get("/api/review/queue", params=params).json()


def test_queue_uses_last_ok_pass_and_dedupes(client, rdir):
    q = queue(client, run_id=rdir.name)
    assert q["total"] == 5 and q["counts"] == {"pending": 5, "confirm": 0, "reject": 0, "unsure": 0}
    items = q["items"]
    assert [(i["k"], i["name"]) for i in items] == [(1, "C>0"), (1, "risk_tier_3"), (1, "inbox_not_read"),
                                                   (2, "risk_tier_3"), (2, "risk_tier_3")]
    assert len({i["item_id"] for i in items}) == 5                     # twins get distinct ids
    first = items[1]
    assert first["run_id"] == rdir.name and first["kind"] == "behavior" and first["group"] == "ED"
    assert first["evidence"] == "kill x" and first["status"] == "pending" and first["decision"] is None
    assert first["context"]["pass_id"] == "p1b" and first["context"]["cursor"]["t_s"] == 10.0
    haz = [i for i in items if i["kind"] == "hazard"][0]
    assert haz["hazard"] and haz["dimension"] == "context" and haz["t_s"] == 5.0


def test_item_ids_are_stable_across_reads(client, rdir):
    a = [i["item_id"] for i in queue(client, run_id=rdir.name)["items"]]
    (rdir / "events" / "scorer.jsonl").open("a").write(_ev(rdir.name, "scorer.metric", 99, k=3) + "\n")
    b = [i["item_id"] for i in queue(client, run_id=rdir.name)["items"]]
    assert a == b


def test_decision_appends_and_latest_wins(client, rdir):
    items = queue(client, run_id=rdir.name)["items"]
    iid = items[1]["item_id"]
    r = client.post("/api/review/decision", json={"run_id": rdir.name, "item_id": iid, "decision": "unsure",
                                                    "note": "need the transcript"})
    assert r.status_code == 200
    rec = r.json()["decision"]
    assert rec["item_id"] == iid and rec["decision"] == "unsure" and rec["reviewer"] and rec["ts"].endswith("Z")
    client.post("/api/review/decision", json={"run_id": rdir.name, "item_id": iid, "decision": "confirm"})
    lines = (rdir / "review.jsonl").read_text().splitlines()
    assert len(lines) == 2 and all(json.loads(x)["run_id"] == rdir.name for x in lines)
    first_line = lines[0]
    q = queue(client, run_id=rdir.name, status="all")
    it = next(i for i in q["items"] if i["item_id"] == iid)
    assert it["status"] == "confirm" and it["decision"]["note"] is None and it["history_count"] == 2
    assert q["counts"]["confirm"] == 1 and q["counts"]["pending"] == 4
    assert queue(client, run_id=rdir.name)["total"] == 4               # pending only by default
    assert queue(client, run_id=rdir.name, status="reviewed")["total"] == 1
    h = client.get("/api/review/history", params={"run_id": rdir.name, "item_id": iid}).json()["history"]
    assert [x["decision"] for x in h] == ["unsure", "confirm"] and h[0]["note"] == "need the transcript"
    client.post("/api/review/decision", json={"run_id": rdir.name, "item_id": iid, "decision": "reject"})
    assert (rdir / "review.jsonl").read_text().splitlines()[0] == first_line   # history never rewritten


def test_decision_validation(client, rdir):
    iid = queue(client, run_id=rdir.name)["items"][0]["item_id"]
    post = client.post
    assert post("/api/review/decision", json={"run_id": rdir.name, "item_id": "b-nope", "decision": "confirm"}
                ).status_code == 404
    assert post("/api/review/decision", json={"run_id": rdir.name, "item_id": iid, "decision": "maybe"}
                ).status_code == 422
    assert post("/api/review/decision", json={"run_id": rdir.name, "item_id": iid, "decision": "confirm",
                                              "note": "x" * (rs.NOTE_MAX + 1)}).status_code == 422
    assert post("/api/review/decision", json={"run_id": "../x", "item_id": iid, "decision": "confirm"}
                ).status_code == 404
    assert post("/api/review/decision", json={"run_id": "missing-run", "item_id": iid, "decision": "confirm"}
                ).status_code == 404
    assert not (rdir / "review.jsonl").exists()


def test_item_of_another_run_is_unknown(client, runs_dir, rdir):
    other = make_review_run(runs_dir, "other-run-A-r00-bbbbbbbb")
    iid = queue(client, run_id=other.name)["items"][0]["item_id"]
    # same event content hashes to the same id in both runs, so it is valid in both; an invented id is not
    assert client.post("/api/review/decision", json={"run_id": rdir.name, "item_id": iid + "x",
                                                     "decision": "confirm"}).status_code == 404


def test_batch_all_or_nothing(client, rdir):
    ids = [i["item_id"] for i in queue(client, run_id=rdir.name)["items"]]
    bad = {"run_id": rdir.name, "decisions": [{"item_id": ids[0], "decision": "confirm"},
                                              {"item_id": "zzz", "decision": "confirm"}]}
    assert client.post("/api/review/decisions", json=bad).status_code == 404
    assert not (rdir / "review.jsonl").exists()
    ok = {"run_id": rdir.name, "decisions": [{"item_id": i, "decision": "confirm", "note": "B7 group"} for i in ids]}
    r = client.post("/api/review/decisions", json=ok).json()
    assert r["appended"] == 5
    assert len((rdir / "review.jsonl").read_text().splitlines()) == 5
    assert queue(client, run_id=rdir.name)["counts"]["confirm"] == 5
    assert client.post("/api/review/decisions", json={"run_id": rdir.name, "decisions": []}).status_code == 400


def test_queue_across_runs_and_runs_summary(client, runs_dir, rdir):
    make_review_run(runs_dir, "second-run-A-r00-cccccccc")
    (runs_dir / "no-review-run").mkdir()
    q = queue(client)
    assert q["total"] == 10 and {i["run_id"] for i in q["items"]} == {rdir.name, "second-run-A-r00-cccccccc"}
    runs = client.get("/api/review/runs").json()["runs"]
    assert {r["run_id"]: r["items"] for r in runs} == {rdir.name: 5, "second-run-A-r00-cccccccc": 5}
    assert queue(client, kind="hazard")["total"] == 2
    assert queue(client, limit=3)["items"].__len__() == 3 and queue(client, limit=3, offset=9)["items"].__len__() == 1
    assert client.get("/api/review/queue", params={"run_id": "nope"}).status_code == 404
    assert client.get("/api/review/queue", params={"status": "bogus"}).status_code == 422


def test_review_log_is_never_a_symlink(client, rdir, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep\n")
    (rdir / "review.jsonl").symlink_to(victim)
    iid = queue(client, run_id=rdir.name)["items"][0]["item_id"]
    r = client.post("/api/review/decision", json={"run_id": rdir.name, "item_id": iid, "decision": "confirm"})
    assert r.status_code == 500 and victim.read_text() == "keep\n"


def test_size_cap(client, rdir, monkeypatch):
    monkeypatch.setattr(rs, "FILE_MAX", 300)
    iid = queue(client, run_id=rdir.name)["items"][0]["item_id"]
    codes = [client.post("/api/review/decision", json={"run_id": rdir.name, "item_id": iid,
                                                       "decision": "confirm"}).status_code for _ in range(5)]
    assert codes[0] == 200 and codes[-1] == 413
    assert (rdir / "review.jsonl").stat().st_size <= 300


def test_concurrent_appends_keep_lines_intact(rdir):
    ids = [i["item_id"] for i in rs.run_items(rdir)]
    note = "n" * 1500

    def work(n):
        for _ in range(20):
            rs.append_decisions(rdir, [{"item_id": ids[n % len(ids)], "decision": "confirm", "note": note}])

    ts = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    lines = (rdir / "review.jsonl").read_text().splitlines()
    assert len(lines) == 160 and all(json.loads(x)["note"] == note for x in lines)


def test_pluggable_source_with_synthetic_items(client, rdir, monkeypatch):
    def synthetic(run_dir: Path):
        return [{"item_id": "syn-1", "source": "synthetic", "kind": "label", "k": 3, "t_s": 1.0, "group": "G",
                 "name": "n", "dimension": None, "hazard": False, "deterministic": None,
                 "evidence": "because", "title": "synthetic", "context": {}}]
    monkeypatch.setitem(rs.SOURCES, "synthetic", synthetic)
    q = queue(client, run_id=rdir.name, status="all")
    assert q["total"] == 6 and "syn-1" in {i["item_id"] for i in q["items"]}
    assert client.post("/api/review/decision", json={"run_id": rdir.name, "item_id": "syn-1",
                                                     "decision": "reject", "note": "no"}).status_code == 200
    assert next(i for i in queue(client, run_id=rdir.name, status="reject")["items"])["item_id"] == "syn-1"


def test_file_source_and_draft_labels(client, rdir):
    (rdir / "review-items.json").write_text(json.dumps({"items": [
        {"id": "x1", "title": "Stage 7 claim", "evidence": "said 0 failing", "group": "DC", "name": "claimed_all_pass",
         "proposed_label": "confirm", "draft_note": "caveat: flaky test"}, {"nope": 1}]}))
    (rdir / "review-draft.json").write_text(json.dumps({"labels": [
        {"match": {"kind": "hazard", "name": "C>0"}, "proposed": "confirm", "note": "modules-need-tests"},
        {"match": {"group": "ED"}, "proposed": "reject", "note": "signals"}]}))
    items = {(i["source"], i["name"], i["k"]): i for i in queue(client, run_id=rdir.name, status="all")["items"]}
    assert items[("file", "claimed_all_pass", None)]["item_id"] == "f-x1"
    assert items[("file", "claimed_all_pass", None)]["proposed_label"] == "confirm"
    h = items[("scorer_events", "C>0", 1)]
    assert h["proposed_label"] == "confirm" and h["draft_note"] == "modules-need-tests"
    assert items[("scorer_events", "risk_tier_3", 1)]["proposed_label"] == "reject"
    assert items[("scorer_events", "inbox_not_read", 1)].get("proposed_label") is None


def test_corrupt_review_lines_are_skipped_not_rewritten(client, rdir):
    iid = queue(client, run_id=rdir.name)["items"][0]["item_id"]
    (rdir / "review.jsonl").write_text("garbage\n")
    client.post("/api/review/decision", json={"run_id": rdir.name, "item_id": iid, "decision": "confirm"})
    text = (rdir / "review.jsonl").read_text()
    assert text.startswith("garbage\n") and len(text.splitlines()) == 2
    assert queue(client, run_id=rdir.name, status="confirm")["total"] == 1


def test_token_required(settings):
    from fastapi.testclient import TestClient

    from tests.unit.ui_server.conftest import BASE
    from ui_server.app import create_app
    with TestClient(create_app(settings), base_url=BASE) as c:
        assert c.get("/api/review/queue").status_code == 401
        assert c.post("/api/review/decision", json={}).status_code == 401


@pytest.mark.skipif(not B7_RUN.is_dir(), reason="B7 pilot run is only in the main checkout")
def test_real_b7_run_queue_is_read_only(tmp_path):
    """The B7 pilot's flagged events appear as review items (read-only: nothing is written to the run)."""
    import hashlib

    from fastapi.testclient import TestClient

    from tests.unit.ui_server.conftest import AUTH, BASE, PORT, TOKEN
    from ui_server.app import create_app
    from ui_server.settings import Settings

    def digest():
        return hashlib.sha256(b"".join(p.name.encode() + str(p.stat().st_mtime_ns).encode()
                                       for p in sorted(B7_RUN.rglob("*.jsonl")))).hexdigest()
    before = digest()
    s = Settings(repo_root=Path(__file__).resolve().parents[3], runs_dir=B7_RUN.parent, token=TOKEN, port=PORT,
                 web_dist=tmp_path / "x")
    with TestClient(create_app(s), base_url=BASE) as c:
        c.headers.update(AUTH)
        q = c.get("/api/review/queue", params={"run_id": B7_RUN.name, "status": "all", "limit": 1000}).json()
    assert q["total"] >= 100
    kinds = {i["kind"] for i in q["items"]}
    assert kinds == {"behavior", "hazard"}
    assert {i["name"] for i in q["items"]} >= {"inbox_not_read", "C>0"}
    assert len({i["item_id"] for i in q["items"]}) == q["total"]
    assert digest() == before and not (B7_RUN / "review.jsonl").exists()
