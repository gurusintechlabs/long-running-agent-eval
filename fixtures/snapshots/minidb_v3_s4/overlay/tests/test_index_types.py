"""Stage 4: k-means, residual PQ, the IVF and QSG indexes, disk vectors, payload columns, filtered
search strategies and the knn() SQL table function."""
import json

import numpy as np
import pytest

from minidb import index as indexes
from minidb.collection.columns import PayloadColumns, View
from minidb.collection.filters import compile_filter
from minidb.collection.points import Invalid
from minidb.collection.sqlfunc import Knn
from minidb.collection.store import PRE_FILTER_MAX, Catalog, Collection
from minidb.collection.vectors import DiskVectors, MemoryVectors
from minidb.index.base import transform
from minidb.index.ivf import IVFIndex
from minidb.index.kmeans import kmeans, nearest
from minidb.index.pq import ResidualPQ
from minidb.index.qsg import QSGIndex
from minidb.protocol import SQLNameError, SQLTypeError
from minidb.values import Vector


def _clustered(n, dim=32, seed=0, clusters=16):
    rng = np.random.default_rng(seed)
    c = rng.normal(size=(clusters, dim)).astype(np.float32)
    return (c[rng.integers(0, clusters, n)] + 0.3 * rng.normal(size=(n, dim))).astype(np.float32)


def _recall(index, x, metric="l2", k=10, params=None, queries=30):
    xt = transform(x, metric)
    hits = 0
    for q in x[:queries] + 0.01:
        qt = transform(q[None], metric)[0]
        truth = set(np.argsort(((xt - qt) ** 2).sum(1))[:k].tolist())
        cand = index.search(q, k, params or {"ef": 64, "nprobe": 8}, None).slots
        got = cand[np.argsort(((xt[cand] - qt) ** 2).sum(1))[:k]]
        hits += len(set(got.tolist()) & truth)
    return hits / (k * queries)


def test_index_objects_and_params():
    assert indexes.parse_index({"type": "ivf_pq"}, 32) == {"type": "ivf_pq", "nlist": 256, "m": 16, "nbits": 8}
    assert indexes.parse_index({"type": "qsg", "degree": 8}) == {"type": "qsg", "degree": 8, "m": 16}
    for bad in ({"type": "ivf_flat", "nlist": 0}, {"type": "ivf_pq", "nbits": 9}, {"type": "qsg", "ef": 3},
                {"type": "ivf_pq", "m": 5}):
        with pytest.raises(Invalid):
            indexes.parse_index(bad, 32)
    assert indexes.parse_params(None, {"type": "ivf_flat", "nlist": 8}) == {"ef": 64, "nprobe": 8}
    with pytest.raises(Invalid):
        indexes.parse_params({"nprobe": 9}, {"type": "ivf_flat", "nlist": 8})


def test_kmeans_finds_separated_clusters():
    x = _clustered(2000, clusters=8, seed=3)
    c = kmeans(x, 8, seed=1)
    assert len(np.unique(nearest(x, c))) == 8
    two = nearest(x[:5], c, 2)
    assert two.shape == (5, 2) and (two[:, 0] == nearest(x[:5], c)).all()


def test_residual_pq_distances_track_exact_ones():
    rng = np.random.default_rng(0)
    x = _clustered(3000)
    c = kmeans(x, 16)
    a = nearest(x, c)
    pq = ResidualPQ(32, 8, 8, inner=False)
    pq.train(x - c[a], rng)
    codes, extra = pq.encode(x - c[a], c[a])
    q = x[0] + 0.05
    t1, lut = pq.tables(q, c)
    approx = pq.distances(t1[a], lut, codes, extra)
    exact = ((x - q) ** 2).sum(1)
    assert np.corrcoef(approx, exact)[0, 1] > 0.95
    assert int(np.argmin(approx)) in np.argsort(exact)[:5].tolist()


@pytest.mark.parametrize("kind", ["ivf_flat", "ivf_pq"])
def test_ivf_recall_dead_and_allowed(kind):
    x = _clustered(3000)
    cfg = indexes.parse_index({"type": kind, "nlist": 32, **({"m": 8} if kind == "ivf_pq" else {})}, 32)
    ivf = IVFIndex(cfg, 32, "l2")
    ivf.train(np.arange(3000), lambda s: x[s])
    assert ivf.trained and _recall(ivf, x) >= 0.9
    for s in range(0, 3000, 2):
        ivf.mark_dead(s)
    allowed = np.zeros(3000, bool)
    allowed[::3] = True
    hits = ivf.search(x[3], 10, {"nprobe": 32}, allowed)
    assert len(hits.slots) and all(s % 2 == 1 and s % 3 == 0 for s in hits.slots.tolist())
    assert hits.info == {"nprobe": 32}


def test_qsg_recall_reachability_adds_and_persistence(tmp_path):
    x = _clustered(3000, clusters=24, seed=5)
    g = QSGIndex({"degree": 16, "m": 8}, 32, "l2")
    g.train(np.arange(2500), lambda s: x[s])
    assert _recall(g, x[:2500]) >= 0.9
    g.fetch = lambda s: x[s]
    g.add(np.arange(2500, 3000), x[2500:])
    assert g.search(x[2900], 1, {"ef": 64}, None).slots[0] == 2900
    g.save(tmp_path / "q.npz", {"seq": 1})
    h = QSGIndex({"degree": 16, "m": 8}, 32, "l2")
    assert not h.load(tmp_path / "q.npz", {"seq": 2}, None, None)
    assert h.load(tmp_path / "q.npz", {"seq": 1}, None, None)
    assert np.array_equal(h.search(x[7], 10, {"ef": 32}, None).slots, g.search(x[7], 10, {"ef": 32}, None).slots)


def test_disk_and_memory_vectors(tmp_path):
    x = _clustered(100, dim=4)
    d, m = DiskVectors(tmp_path / "v.f32", 4), MemoryVectors(4)
    for store in (d, m):
        store.write(0, x[:60])
        store.write(60, x[60:])
        assert np.array_equal(store.rows([5, 6, 7, 99, 0]), x[[5, 6, 7, 99, 0]])
        assert np.array_equal(store.prefix(100), x)
    d.close()


def test_payload_columns_follow_new_points():
    class Coll:
        def __init__(self):
            self.n_slots = 4
            self.payloads = [{"a": 1}, {"a": "x"}, {"a": [1, 2]}, None]
            self.slot_of = {10: 0, 11: 1}
            self.columns = PayloadColumns()
    c = Coll()
    f = compile_filter({"must": [{"key": "a", "match": {"value": 1}}]})
    assert f.mask(View(c)).tolist() == [True, False, True, False]
    c.payloads.append({"a": 1.0})
    c.n_slots = 5
    c.columns.added(4, [{"a": 1.0}])
    assert f.mask(View(c)).tolist() == [True, False, True, False, True]
    assert compile_filter({"must": [{"has_id": [11]}]}).mask(View(c)).tolist() == [False, True, False, False, False]
    assert compile_filter({"must_not": [{"key": "a", "range": {"gte": 1}}]}).mask(View(c)).tolist() == \
        [False, True, False, True, False]


def test_filtered_search_strategies(tmp_path):
    n = 3 * PRE_FILTER_MAX
    x = _clustered(n, dim=8)
    c = Collection.create(tmp_path, "c", 8, "l2", indexes.parse_index({"type": "ivf_flat", "nlist": 16}, 8))
    for i in range(0, n, 1000):
        ids = list(range(i, min(i + 1000, n)))
        c.upsert(ids, x[ids], [{"g": j % 2} for j in ids])
    q = x[0].astype(np.float64)
    res, ex = c.query(q, 10, compile_filter({"must": [{"has_id": list(range(0, n, 7))[:50]}]}))
    assert ex["filter"] == "pre" and len(res) == 10 and all(r["id"] % 7 == 0 for r in res)
    res, ex = c.query(q, 10, compile_filter({"must": [{"key": "g", "match": {"value": 1}}]}))
    assert ex["filter"] == "post" and len(res) == 10 and all(r["id"] % 2 == 1 for r in res)
    assert c.query(q, 10, None)[1]["filter"] == "none"
    c.close()


def test_switching_index_moves_vectors_and_survives_restart(tmp_path):
    x = _clustered(1500, dim=8)
    c = Collection.create(tmp_path, "c", 8, "l2")
    c.upsert(list(range(1500)), x, [None] * 1500)
    c.set_index(indexes.parse_index({"type": "ivf_pq", "nlist": 8, "m": 4}, 8))
    assert (tmp_path / "c" / "vectors.f32").exists() and c.store.kind == "disk"
    want = c.query(x[3].astype(np.float64), 5, None)[0]
    c.close()
    d = Collection.load(tmp_path / "c")
    assert d.query(x[3].astype(np.float64), 5, None)[0] == want
    assert d.get(3)["vector"] == pytest.approx(x[3].tolist())
    d.set_index({"type": "flat"})
    assert not (tmp_path / "c" / "vectors.f32").exists() and d.store.kind == "memory"
    assert d.get(3)["vector"] == pytest.approx(x[3].tolist())


def test_knn_table_function(tmp_path):
    cat = Catalog(tmp_path)
    c = cat.create("docs", 2, "l2")
    c.upsert([1, 2], np.array([[0, 0], [1, 0]], np.float32), [{"t": "a"}, None])
    knn = Knn(cat)
    assert knn(["docs", Vector([0.9, 0.0]), 2]) == [[2, pytest.approx(0.1), None], [1, pytest.approx(0.9), json.dumps({"t": "a"}, separators=(",", ":"))]]
    with pytest.raises(SQLNameError):
        knn(["nope", Vector([0.0, 0.0]), 1])
    for bad in (["docs", "[0, 0]", 1], ["docs", Vector([0.0]), 1], ["docs", Vector([0.0, 0.0]), 0], [1, Vector([0.0, 0.0]), 1]):
        with pytest.raises(SQLTypeError):
            knn(bad)
