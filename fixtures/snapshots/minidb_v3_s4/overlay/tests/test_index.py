"""Vector indexes (stage 2): configuration, SQ8, the hnsw graph, persistence, and the collection wiring."""
import numpy as np
import pytest

from minidb import index as indexes
from minidb.collection.points import Invalid
from minidb.collection.store import Collection
from minidb.index.hnsw import HNSWIndex
from minidb.index.quant import ScalarQuantizer


def _clustered(n, dim=32, seed=0):
    rng = np.random.default_rng(seed)
    centres = rng.normal(size=(16, dim))
    pts = centres[rng.integers(0, 16, n)] + rng.normal(scale=0.3, size=(n, dim))
    return pts.astype(np.float32)


def _recall(found, truth):
    return np.mean([len(set(f) & set(t)) / len(t) for f, t in zip(found, truth, strict=True)])


def test_index_objects():
    assert indexes.parse_index({"type": "flat"}) == {"type": "flat"}
    assert indexes.parse_index({"type": "hnsw", "m": 8}) == {"type": "hnsw", "m": 8, "ef_construction": 200}
    for bad in ({"type": "x"}, {"type": "hnsw", "m": 3}, {"type": "hnsw", "ef_construction": 2000},
                {"type": "flat", "m": 4}, {"type": "hnsw", "nope": 1}, []):
        with pytest.raises(Invalid):
            indexes.parse_index(bad)
    assert indexes.build({"type": "flat"}, 4, "l2") is None


def test_sq8_distances_track_exact_ones():
    x = _clustered(500)
    q = ScalarQuantizer(x.shape[1])
    q.train(x)
    codes = q.encode(x)
    prep = q.prepare(x[0], inner=False)
    approx = q.distances(codes, prep, inner=False)
    exact = ((x - x[0]) ** 2).sum(1)
    assert np.corrcoef(approx, exact)[0, 1] > 0.999


@pytest.mark.parametrize("metric", ["l2", "cosine"])
def test_hnsw_recall_on_clustered_data(metric):
    x = _clustered(4000)
    h = HNSWIndex(x.shape[1], metric, m=8, ef_construction=100)
    for i in range(0, len(x), 1000):
        h.add(np.arange(i, i + 1000), x[i:i + 1000])
    rng = np.random.default_rng(1)
    qs = x[rng.integers(0, len(x), 50)] + rng.normal(scale=0.1, size=(50, x.shape[1])).astype(np.float32)
    if metric == "cosine":
        xn = x / np.linalg.norm(x, axis=1, keepdims=True)
        truth = [np.argsort(-(xn @ (q / np.linalg.norm(q))))[:10] for q in qs]
    else:
        truth = [np.argsort(((x - q) ** 2).sum(1))[:10] for q in qs]
    found = []
    for q in qs:
        cand = h.search(q, 10, {"ef": 64}, None).slots
        d = ((x[cand] - q) ** 2).sum(1) if metric == "l2" else -(x[cand] @ q) / np.linalg.norm(x[cand], axis=1)
        found.append(cand[np.argsort(d)[:10]])
    assert _recall(found, truth) >= 0.95


def test_hnsw_skips_dead_and_disallowed_nodes():
    x = _clustered(1000)
    h = HNSWIndex(x.shape[1], "l2", m=8, ef_construction=64)
    h.add(np.arange(1000), x)
    for s in range(0, 1000, 2):
        h.mark_dead(s)
    allowed = np.zeros(1000, bool)
    allowed[::3] = True
    res = h.search(x[1], 10, {"ef": 50}, allowed).slots
    assert len(res) and all(s % 2 == 1 and s % 3 == 0 for s in res.tolist())


def test_hnsw_save_and_load(tmp_path):
    x = _clustered(1500)
    h = HNSWIndex(x.shape[1], "l2", m=8, ef_construction=64)
    h.add(np.arange(1500), x)
    h.save(tmp_path / "g.npz", {"seq": 3})
    g = HNSWIndex(x.shape[1], "l2", m=8, ef_construction=64)
    assert not g.load(tmp_path / "g.npz", {"seq": 4}, lambda s: x[s], np.arange(1500))
    assert g.load(tmp_path / "g.npz", {"seq": 3}, lambda s: x[s], np.arange(1500))
    assert np.array_equal(g.search(x[7], 10, {"ef": 64}, None).slots, h.search(x[7], 10, {"ef": 64}, None).slots)


def test_collection_keeps_its_graph_across_restarts(tmp_path):
    x = _clustered(2000, dim=16)
    c = Collection.create(tmp_path, "c", 16, "l2", {"type": "hnsw", "m": 8, "ef_construction": 64})
    c.upsert(list(range(2000)), x, [None] * 2000)
    before, how = c.query(x[3].astype(np.float64), 5, None)
    assert how["index"] == "hnsw" and before[0]["id"] == 3
    c.close()
    d = Collection.load(tmp_path / "c")
    assert (tmp_path / "c" / "index.npz").exists() and d.index.size == 2000          # loaded, not rebuilt
    assert d.query(x[3].astype(np.float64), 5, None)[0] == before
    d.delete([3])
    assert all(r["id"] != 3 for r in d.query(x[3].astype(np.float64), 5, None)[0])
    d.set_index({"type": "flat"})
    assert d.query(x[3].astype(np.float64), 5, None)[1]["index"] == "flat"
    assert not (tmp_path / "c" / "index.npz").exists()
