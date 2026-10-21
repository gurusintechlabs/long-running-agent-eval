"""t22 (stage 12): full scale and hardening (brief 12.1, 12.2). The 200,000-point targets (bulk load, recall,
latency, throughput of a mixed load, ivf_pq memory) are wall-clock tests (``*timing*``: per-commit scoring
skips them); the concurrency guarantees (no torn reads, the last acknowledged value wins, revocation
takes effect for every later request) run at a moderate size."""
import random
import threading
import time

import numpy as np
import pytest

from _support import Server, clustered, new_key, recall_at, stage

FULL = 200_000
LOAD_LIMIT_S = 180.0            # bulk upsert of FULL points in requests of 1,000
RECALL_MIN = 0.90               # hnsw defaults, ef 64, recall@10 on the hidden queries
LATENCY_MS = 15.0               # median, one client, ef 64
RPS_MIN = 300.0                 # 8 clients, 1,000 mixed requests (90% searches, 10% one-point upserts)
HALF_RAW_BYTES = (FULL // 2) * 96 * 4


def _load(srv, coll, base, *, start=0, deadline=None):
    for i in range(0, len(base), 1000):
        pts = [{"id": start + j, "vector": base[j].tolist()} for j in range(i, min(i + 1000, len(base)))]
        r = srv.put(f"/v1/collections/{coll}/points", {"points": pts}, timeout=600)
        assert r.status == 200, r
        if deadline is not None and time.monotonic() > deadline:
            raise AssertionError(f"only {start + i + 1000} of {start + len(base)} points loaded within the limit")


def _truth(base: np.ndarray, queries: np.ndarray, k: int = 10) -> list[list[int]]:
    """Exact top-k ids (l2, ties by id) for every query: numpy, not ``exact_topk`` (too slow at FULL)."""
    b = base.astype(np.float64)
    bn = (b * b).sum(1)
    out = []
    for q in queries.astype(np.float64):
        approx = bn - 2.0 * (b @ q)
        near = np.argpartition(approx, 4 * k)[: 4 * k]
        d = np.sqrt(((b[near] - q) ** 2).sum(1))
        out.append([int(near[i]) for i in np.lexsort((near, d))[:k]])
    return out


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    """FULL hidden points loaded into a default hnsw collection; the load time is measured."""
    srv = Server(tmp_path_factory.mktemp("full"), rate_limit=1_000_000)
    try:
        base, queries = clustered(FULL, queries=200)
        assert srv.put("/v1/collections/full", {"dim": 96, "metric": "l2", "index": {"type": "hnsw"}}).status == 201
        t0 = time.monotonic()
        try:
            _load(srv, "full", base, deadline=t0 + LOAD_LIMIT_S)
            error = None
        except AssertionError as e:
            error = str(e)
        yield {"srv": srv, "base": base, "queries": queries, "load_s": time.monotonic() - t0, "error": error}
    finally:
        srv.close()


@stage(12)
def test_bulk_load_of_200000_points_timing(full):
    assert full["error"] is None and full["load_s"] <= LOAD_LIMIT_S, (full["error"], f"{full['load_s']:.1f} s")


@stage(12)
def test_recall_and_latency_at_full_scale_timing(full):
    if full["error"]:
        pytest.fail(f"the collection was not loaded: {full['error']}")
    srv, base, queries = full["srv"], full["base"], full["queries"]
    truth = _truth(base, queries)
    found, lat = [], []
    for q in queries:
        t0 = time.perf_counter()
        r = srv.post("/v1/collections/full/search", {"vector": q.tolist(), "k": 10, "params": {"ef": 64}})
        lat.append(time.perf_counter() - t0)
        assert r.status == 200, r
        found.append([p["id"] for p in r.json()["results"]])
    recall = recall_at(found, truth)
    assert recall >= RECALL_MIN, f"recall@10 {recall:.3f}"
    assert np.median(lat) * 1000 <= LATENCY_MS, f"median {np.median(lat) * 1000:.1f} ms"


@stage(12)
def test_mixed_load_with_8_clients_timing(full):
    if full["error"]:
        pytest.fail(f"the collection was not loaded: {full['error']}")
    srv, base, queries = full["srv"], full["base"], full["queries"]
    rng = random.Random(12)
    jobs = []
    for i in range(1000):
        if rng.random() < 0.1:
            jobs.append(("upsert", FULL + i, (base[rng.randrange(FULL)] * 1.01).astype(np.float32)))
        else:
            jobs.append(("search", None, queries[rng.randrange(len(queries))]))
    nxt, lock, answers = iter(range(len(jobs))), threading.Lock(), {}

    def client():
        while True:
            with lock:
                i = next(nxt, None)
            if i is None:
                return
            kind, pid, v = jobs[i]
            if kind == "upsert":
                r = srv.put("/v1/collections/full/points", {"points": [{"id": pid, "vector": v.tolist()}]})
            else:
                r = srv.post("/v1/collections/full/search", {"vector": v.tolist(), "k": 10, "params": {"ef": 64}})
            answers[i] = r
    t0 = time.perf_counter()
    threads = [threading.Thread(target=client) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    rps = len(jobs) / (time.perf_counter() - t0)
    # every answer is correct: upserts acknowledged; searches give 10 results with their exact scores
    vectors = {pid: v for kind, pid, v in jobs if kind == "upsert"}
    for i, (kind, _, v) in enumerate(jobs):
        r = answers[i]
        assert r.status == 200, (kind, r)
        if kind == "search":
            res = r.json()["results"]
            assert len(res) == 10
            for p in res:
                vec = vectors[p["id"]] if p["id"] >= FULL else base[p["id"]]
                assert p["score"] == pytest.approx(float(np.linalg.norm(vec.astype(np.float64) - v)), rel=1e-5, abs=1e-5)
    for pid, v in list(vectors.items())[:20]:
        got = srv.get(f"/v1/collections/full/points/{pid}").json()["vector"]
        assert np.allclose(got, v, atol=1e-6)
    assert rps >= RPS_MIN, f"{rps:.0f} requests per second"


@stage(12)
def test_ivf_pq_memory_at_full_scale_timing(tmp_path):
    srv = Server(tmp_path / "pq", rate_limit=1_000_000)
    try:
        base, _ = clustered(FULL, queries=1)
        assert srv.put("/v1/collections/pq", {"dim": 96, "metric": "l2", "index": {"type": "ivf_pq"}}).status == 201
        _load(srv, "pq", base[: FULL // 2])
        before = srv.rss()
        _load(srv, "pq", base[FULL // 2:], start=FULL // 2)
        grown = srv.rss() - before
        assert grown < HALF_RAW_BYTES, f"resident memory grew by {grown / 1e6:.1f} MB over the second 100,000 points"
    finally:
        srv.close()


# ------------------------------------------------------------------ concurrency (brief 12.2)

@pytest.fixture
def srv(tmp_path):
    s = Server(tmp_path / "srv", rate_limit=1_000_000)
    try:
        yield s
    finally:
        s.close()


def _vec(v: int, dim: int = 8) -> list[float]:
    return [float(v)] * (dim - 1) + [1.0]


@stage(12)
@pytest.mark.parametrize("index", [None, {"type": "hnsw", "m": 8, "ef_construction": 32}])
def test_readers_never_see_a_torn_or_deleted_point(srv, index):
    body = {"dim": 8, "metric": "l2", **({"index": index} if index else {})}
    assert srv.put("/v1/collections/t", body).status == 201
    ids = list(range(200))
    pts = [{"id": i, "vector": _vec(0), "payload": {"v": 0, "check": 0, "blob": "x" * 200}} for i in ids]
    assert srv.put("/v1/collections/t/points", {"points": pts}).status == 200
    stop, errors = threading.Event(), []
    gone: dict[int, float] = {}                   # id -> when its delete was acknowledged
    lock = threading.Lock()
    # bounded request counts: every request is a new connection, and the client's ports are finite

    def writer(w):
        rng = random.Random(w)
        try:
            for n in range(1, 41):
                mine = [i for i in ids if i % 4 == w]
                pick = rng.sample(mine, 10)
                if n % 10 == 0:
                    victim = pick[0]
                    r = srv.post("/v1/collections/t/points/delete", {"ids": [victim]})
                    assert r.status == 200, r
                    with lock:
                        gone[victim] = time.monotonic()
                    pick = pick[1:]
                    with lock:
                        mine_left = [p for p in pick if p not in gone]
                else:
                    with lock:
                        mine_left = [p for p in pick if p not in gone]
                v = 1000 * w + n
                pts = [{"id": p, "vector": _vec(v), "payload": {"v": v, "check": v, "blob": str(v) * 50}}
                       for p in mine_left]
                if pts:
                    r = srv.put("/v1/collections/t/points", {"points": pts})
                    assert r.status == 200, r
        except Exception as e:  # noqa: BLE001
            errors.append(f"writer {w}: {e!r}")

    def reader(rd):
        rng = np.random.default_rng(rd)
        try:
            for _ in range(250):
                if stop.is_set():
                    break
                started = time.monotonic()
                with lock:
                    dead = {i for i, t in gone.items() if t < started}
                q = _vec(int(rng.integers(0, 4000)))
                r = srv.post("/v1/collections/t/search", {"vector": q, "k": 20, "with_payload": True,
                                                         "with_vector": True})
                assert r.status == 200, r
                for p in r.json()["results"]:
                    pay = p["payload"]
                    assert pay["v"] == pay["check"] and pay["blob"] in ("x" * 200, str(pay["v"]) * 50), p
                    assert p["vector"] == _vec(pay["v"]), p
                    assert p["id"] not in dead, f"deleted point {p['id']} returned"
        except Exception as e:  # noqa: BLE001
            errors.append(f"reader {rd}: {e!r}")
    writers = [threading.Thread(target=writer, args=(w,)) for w in range(4)]
    readers = [threading.Thread(target=reader, args=(r,)) for r in range(4)]
    [t.start() for t in writers + readers]
    [t.join(timeout=120) for t in writers]
    stop.set()
    [t.join(timeout=60) for t in readers]
    assert not errors, errors[:5]
    assert gone, "no deletes happened"


@stage(12)
def test_after_concurrent_upserts_every_point_has_its_last_acknowledged_value(srv):
    assert srv.put("/v1/collections/u", {"dim": 8, "metric": "l2", "index": {"type": "hnsw", "m": 8}}).status == 201
    last: dict[int, int] = {}
    errors = []

    def writer(w):                     # each writer owns its ids, so its acknowledgements are ordered
        rng = random.Random(100 + w)
        try:
            for step in range(60):
                pick = [w * 1000 + rng.randrange(50) for _ in range(rng.randint(1, 20))]
                pick = list(dict.fromkeys(pick))
                v = step + 1
                r = srv.put("/v1/collections/u/points", {"points": [
                    {"id": p, "vector": _vec(v), "payload": {"v": v}} for p in pick]})
                assert r.status == 200, r
                for p in pick:
                    last[p] = v
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))
    threads = [threading.Thread(target=writer, args=(w,)) for w in range(8)]
    [t.start() for t in threads]
    [t.join(timeout=120) for t in threads]
    assert not errors, errors[:3]
    for pid, v in last.items():
        got = srv.get(f"/v1/collections/u/points/{pid}").json()
        assert got["payload"] == {"v": v} and got["vector"] == _vec(v), (pid, v, got)
    assert srv.get("/v1/collections/u").json()["points"] == len(last)


@stage(12)
def test_a_revoked_key_fails_for_every_request_started_after_the_revocation(srv):
    assert srv.put("/v1/collections/k", {"dim": 8, "metric": "l2"}).status == 201
    key = new_key(srv, "reader", ["k"])
    stop, seen, lock = threading.Event(), [], threading.Lock()

    def hammer():
        while not stop.is_set():
            t0 = time.monotonic()
            r = srv.post("/v1/collections/k/search", {"vector": _vec(1), "k": 1}, key=key["key"])
            with lock:
                seen.append((t0, r.status))
            time.sleep(0.01)                   # about 100 requests a second per thread
    threads = [threading.Thread(target=hammer) for _ in range(6)]
    [t.start() for t in threads]
    time.sleep(1.0)
    r = srv.delete(f"/v1/keys/{key['id']}")
    revoked_at = time.monotonic()
    assert r.status == 200, r
    time.sleep(1.0)
    stop.set()
    [t.join(timeout=30) for t in threads]
    before = [s for t, s in seen if t < revoked_at - 0.5]
    after = [s for t, s in seen if t > revoked_at]
    assert before and set(before) == {200}, set(before)
    assert after and set(after) == {401}, sorted(set(after))
