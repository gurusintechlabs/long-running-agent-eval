"""t18 (stage 7): crash safety for points (brief 7.2). Acknowledged upserts and deletes survive a SIGKILL,
an interrupted request is all-or-nothing, and a crashed server with 20,000 indexed points is ready
again within 5 seconds and answers searches correctly from then on."""
import http.client
import json
import threading
import time

import numpy as np
import pytest

from _support import Server, clustered, exact_topk, stage, upsert_all

READY_LIMIT_S = 5.0


@pytest.fixture
def srv(tmp_path):
    s = Server(tmp_path / "srv")
    try:
        yield s
    finally:
        s.close()


def _state(srv, coll, ids):
    out = {}
    for pid in ids:
        r = srv.get(f"/v1/collections/{coll}/points/{pid}")
        assert r.status in (200, 404), r
        out[pid] = r.json() if r.status == 200 else None
    return out


@stage(7)
def test_acknowledged_writes_survive_a_sigkill(srv):
    for coll, index in (("plain", None), ("graph", {"type": "hnsw", "m": 8, "ef_construction": 64})):
        assert srv.put(f"/v1/collections/{coll}", {"dim": 4, **({"index": index} if index else {})}).status == 201
    expected = {"plain": {}, "graph": {}}
    lock = threading.Lock()
    errors = []

    def writer(coll, worker):                    # each worker owns its ids, so acknowledgements are ordered
        rng = np.random.default_rng(18 + worker)
        try:
            for step in range(40):
                ids = [worker * 1000 + int(x) for x in rng.choice(100, 5, replace=False)]
                if step % 4 == 3:
                    r = srv.post(f"/v1/collections/{coll}/points/delete", {"ids": ids})
                    assert r.status == 200, r
                    with lock:
                        expected[coll].update(dict.fromkeys(ids))
                else:
                    pts = [{"id": pid, "vector": [float(worker), float(step), float(pid), 1.0],
                            "payload": {"w": worker, "s": step}} for pid in ids]
                    r = srv.put(f"/v1/collections/{coll}/points", {"points": pts})
                    assert r.status == 200, r
                    with lock:
                        expected[coll].update({p["id"]: p for p in pts})
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=writer, args=(c, w)) for c in expected for w in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    srv.restart(crash=True)
    for coll, want in expected.items():
        got = _state(srv, coll, sorted(want))
        for pid, p in want.items():
            if p is None:
                assert got[pid] is None, (coll, pid)
            else:
                assert got[pid]["vector"] == p["vector"] and got[pid]["payload"] == p["payload"], (coll, pid, got[pid])
        live = sum(p is not None for p in want.values())
        assert srv.get(f"/v1/collections/{coll}").json()["points"] == live


@stage(7)
def test_an_interrupted_request_is_all_or_nothing(srv):
    assert srv.put("/v1/collections/c", {"dim": 96}).status == 201
    base, _ = clustered(1000, queries=1, seed=81)
    count = 0
    for attempt, delay in enumerate((0.0, 0.002, 0.01, 0.03, 0.06, 0.1, 0.2, 0.4)):
        ids = [100_000 * (attempt + 1) + i for i in range(1000)]
        body = json.dumps({"points": [{"id": pid, "vector": base[i].tolist(), "payload": {"a": attempt}}
                                      for i, pid in enumerate(ids)]}).encode()
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
        conn.putrequest("PUT", "/v1/collections/c/points")
        conn.putheader("Authorization", f"Bearer {srv.admin_key}")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(len(body)))
        conn.endheaders()
        conn.send(body)
        time.sleep(delay)
        srv.kill()
        conn.close()
        srv.spawn()
        srv.wait_ready(30)
        n = srv.get("/v1/collections/c").json()["points"]
        assert n in (count, count + 1000), (delay, count, n)
        present = [srv.get(f"/v1/collections/c/points/{pid}").status == 200 for pid in ids[::97]]
        assert all(present) if n == count + 1000 else not any(present), (delay, present)
        if n == count + 1000:
            assert srv.get(f"/v1/collections/c/points/{ids[-1]}").json()["payload"] == {"a": attempt}
        count = n
    victims = list(range(100_000, 101_000)) if count else []
    if victims:
        body = json.dumps({"ids": victims}).encode()
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
        conn.request("POST", "/v1/collections/c/points/delete", body=body,
                     headers={"Authorization": f"Bearer {srv.admin_key}", "Content-Type": "application/json"})
        srv.kill()
        conn.close()
        srv.spawn()
        srv.wait_ready(30)
        n = srv.get("/v1/collections/c").json()["points"]
        assert n in (count, count - 1000), (count, n)


@stage(7)
def test_restart_after_a_sigkill_is_ready_within_5_s_timing(srv):
    """20,000 points in an hnsw collection, never checkpointed by a clean shutdown."""
    base, queries = clustered(20_000, queries=20, seed=1807)
    assert srv.put("/v1/collections/c", {"dim": 96, "index": {"type": "hnsw"}}).status == 201
    upsert_all(srv, "c", base, payload=lambda i: {"group": i % 10})
    ready = srv.restart(crash=True)
    assert ready <= READY_LIMIT_S, f"ready after {ready:.1f} s"
    assert srv.get("/v1/collections/c").json()["points"] == 20_000
    for q in queries[:5]:                                # correct from the first request on
        r = srv.post("/v1/collections/c/search", {"vector": q.tolist(), "k": 10}, timeout=120)
        assert r.status == 200, r
        got = [x["id"] for x in r.json()["results"]]
        want = [i for i, _ in exact_topk(base, q, 10)]
        assert len(set(got) & set(want)) >= 9, (got, want)
    flt = {"must": [{"key": "group", "match": {"value": 3}}]}
    r = srv.post("/v1/collections/c/search", {"vector": queries[0].tolist(), "k": 5, "filter": flt,
                                              "with_payload": True}, timeout=120)
    assert r.status == 200 and [x["payload"]["group"] for x in r.json()["results"]] == [3] * 5, r
    assert srv.put("/v1/collections/c/points", {"points": [{"id": 99_999, "vector": base[0].tolist()}]}).status == 200
    deadline = time.monotonic() + 120                    # the index serves again (not only exact scans)
    while True:
        out = srv.post("/v1/collections/c/search", {"vector": queries[1].tolist(), "k": 10, "explain": True}).json()
        if not out["explain"]["exact"]:
            break
        assert time.monotonic() < deadline, out["explain"]
        time.sleep(1)
    found = [[x["id"] for x in srv.post("/v1/collections/c/search", {"vector": q.tolist(), "k": 10}).json()["results"]]
             for q in queries]
    truth = [[i for i, _ in exact_topk(base, q, 10)] for q in queries]
    hits = sum(len(set(f) & set(t)) for f, t in zip(found, truth, strict=True))
    assert hits >= 0.95 * 10 * len(queries), hits
    assert srv.get("/v1/collections/c/points/99999").status == 200
