"""Collections (stage 1): validation, filters, storage, recovery, search, and the REST endpoints."""
import numpy as np
import pytest

from minidb.collection import points as pv
from minidb.collection.filters import MAX_DEPTH, compile_filter
from minidb.collection.store import Catalog, Collection, Exists, NotFound
from minidb.server import collections_api
from tests.server_util import Proc

# ---------------------------------------------------------------- validation

def test_names_ids_and_specs():
    assert pv.valid_name("a") and pv.valid_name("a1_-x") and not pv.valid_name("A") and not pv.valid_name("..")
    assert not pv.valid_name("a" * 65) and not pv.valid_name("-a")
    assert pv.parse_id(0) == 0 and pv.parse_path_id("12") == 12
    for bad in (-1, 2 ** 63, True, 1.0, "7"):
        with pytest.raises(pv.Invalid):
            pv.parse_id(bad)
    assert pv.parse_collection_spec({"dim": 3}) == (3, "l2")
    for body in ({"dim": 0}, {"dim": 3, "metric": "L2"}, {"dim": True}):
        with pytest.raises(pv.Invalid):
            pv.parse_collection_spec(body)


def test_points_are_validated_as_a_batch():
    ids, vecs, payloads = pv.parse_points({"points": [{"id": 1, "vector": [1, 2]}, {"id": 2, "vector": [0, 1],
                                                                                     "payload": {"a": 1}}]}, 2, "cosine")
    assert ids == [1, 2] and vecs.dtype == np.float32 and payloads == [None, {"a": 1}]
    for bad in ([{"id": 1, "vector": [0, 0]}], [{"id": 1, "vector": [1, 2]}, {"id": 1, "vector": [1, 2]}],
                [{"id": 1, "vector": [1e39, 0]}], [{"id": 1, "vector": [1, 2], "payload": {"s": "x" * 70_000}}]):
        with pytest.raises(pv.Invalid):
            pv.parse_points({"points": bad}, 2, "cosine")


# ---------------------------------------------------------------- filters

def test_filter_semantics():
    f = compile_filter({"must": [{"key": "a.b", "match": {"value": 1}}], "must_not": [{"key": "c", "range": {"gt": 5}}]})
    assert f(1, {"a": {"b": 1.0}, "c": 1}) and not f(1, {"a": {"b": True}}) and not f(1, {"a": {"b": 1}, "c": 6})
    g = compile_filter({"should": [{"key": "tags", "match": {"any": ["x"]}}, {"has_id": [7]}]})
    assert g(1, {"tags": ["y", "x"]}) and g(7, None) and not g(1, {"tags": "y"})
    assert compile_filter(None) is None and compile_filter({}) is None and compile_filter({"should": []}) is None
    assert not compile_filter({"must": [{"key": "m", "range": {"gte": 0}}]})(1, {"m": None})


def test_filter_validation_and_depth():
    for bad in ({"must": {}}, {"x": []}, {"must": [{"key": "a"}]}, {"must": [{"key": "a", "range": {}}]},
                {"must": [{"key": "a", "match": {"value": None}}]}, [], {"must": [{"has_id": [-1]}]}):
        with pytest.raises(pv.Invalid):
            compile_filter(bad)
    deep = {"must": [{"key": "a", "match": {"value": 1}}]}
    for _ in range(MAX_DEPTH - 1):
        deep = {"must": [deep]}
    assert compile_filter(deep) is not None
    with pytest.raises(pv.Invalid):
        compile_filter({"must": [deep]})


# ---------------------------------------------------------------- storage

def _vecs(*rows):
    return np.array(rows, dtype=np.float32)


def test_collection_recovers_from_its_log_and_snapshot(tmp_path):
    c = Collection.create(tmp_path, "c", 2, "l2")
    c.upsert([1, 2, 3], _vecs([1, 0], [0, 1], [1, 1]), [{"a": 1}, None, None])
    c.delete([2, 9])
    c.upsert([1], _vecs([5, 5]), [None])
    d = Collection.load(tmp_path / "c")                     # replay of the log only
    assert d.count() == 2 and d.get(1) == {"id": 1, "vector": [5.0, 5.0], "payload": None} and d.get(2) is None
    c.close()                                               # checkpoint
    e = Collection.load(tmp_path / "c")
    assert e.count() == 2 and e.get(3)["vector"] == [1.0, 1.0]
    assert (tmp_path / "c" / "wal.log").stat().st_size == 0


def test_a_torn_log_line_is_discarded(tmp_path):
    c = Collection.create(tmp_path, "c", 1, "l2")
    c.upsert([1], _vecs([1]), [None])
    c.upsert([2], _vecs([2]), [None])
    wal = tmp_path / "c" / "wal.log"
    wal.write_bytes(wal.read_bytes()[:-5])                  # a crash in the middle of the second write
    d = Collection.load(tmp_path / "c")
    assert d.count() == 1 and d.get(2) is None


def test_search_orders_by_score_then_id(tmp_path):
    c = Collection.create(tmp_path, "c", 2, "l2")
    c.upsert([9, 3, 5], _vecs([1, 0], [0, 1], [3, 3]), [{"k": 1}, {"k": 2}, None])
    res = c.search(np.array([0.0, 0.0]), 2)
    assert [r["id"] for r in res] == [3, 9] and res[0]["score"] == 1.0
    res = c.search(np.array([0.0, 0.0]), 5, {"must": [{"key": "k", "match": {"value": 1}}]}, with_payload=True)
    assert res == [{"id": 9, "score": 1.0, "payload": {"k": 1}}]


def test_catalog_create_drop_and_reload(tmp_path):
    cat = Catalog(tmp_path)
    cat.create("a", 2, "dot")
    with pytest.raises(Exists):
        cat.create("a", 2, "dot")
    cat.create("b", 3, "l2")
    cat.drop("b")
    with pytest.raises(NotFound):
        cat.drop("b")
    cat.close()
    again = Catalog(tmp_path)
    assert [c.info() for c in again.list()] == [{"name": "a", "dim": 2, "metric": "dot", "points": 0,
                                                 "index": {"type": "flat"}}]
    assert not [p for p in (tmp_path / "collections").iterdir() if p.name.startswith(".")]


# ---------------------------------------------------------------- endpoints

@pytest.fixture
def srv(tmp_path):
    p = Proc(tmp_path / "data").wait_ready()
    yield p
    p.stop()


def test_rest_round_trip(srv):
    assert srv.request("PUT", "/v1/collections/c", {"dim": 2, "metric": "cosine"})[:2] == (
        201, {"name": "c", "dim": 2, "metric": "cosine", "points": 0, "index": {"type": "flat"}})
    assert srv.request("PUT", "/v1/collections/c", {"dim": 2})[0] == 409
    assert srv.request("PUT", "/v1/collections/C", {"dim": 2})[0] == 400
    assert srv.request("PUT", "/v1/collections/c/points",
                       {"points": [{"id": 1, "vector": [1, 0]}, {"id": 2, "vector": [0, 1]}]})[1] == {"upserted": 2}
    status, body, _ = srv.request("POST", "/v1/collections/c/search", {"vector": [1, 0.1], "k": 1})
    assert status == 200 and [r["id"] for r in body["results"]] == [1]
    assert srv.request("POST", "/v1/collections/c/points/delete", {"ids": [1, 5]})[1] == {"deleted": 1}
    assert srv.request("GET", "/v1/collections/c/points/1")[0] == 404
    assert srv.request("DELETE", "/v1/collections/c")[1] == {"deleted": True}
    assert srv.request("GET", "/v1/collections")[1] == {"collections": []}


def test_upsert_accepts_bodies_up_to_its_own_limit():
    assert collections_api.UPSERT_MAX_BODY == 8 << 20


# ---------------------------------------------------------------- change requests (stage 3)

def test_uuid_ids_are_canonical_and_sort_after_integers(tmp_path):
    u = "6F9619FF8B86D011B42D00C04FC964FF"
    assert pv.parse_id(u) == "6f9619ff-8b86-d011-b42d-00c04fc964ff" == pv.parse_path_id(u.lower())
    for bad in ("7", "", "6f9619ff-8b86-d011-b42d-00c04fc964f", "{6f9619ff-8b86-d011-b42d-00c04fc964ff}"):
        with pytest.raises(pv.Invalid):
            pv.parse_id(bad)
    c = Collection.create(tmp_path, "c", 1, "l2")
    ids = [5, pv.parse_id(u), 2, pv.parse_id("00000000-0000-0000-0000-000000000001")]
    c.upsert(ids, np.ones((4, 1), np.float32), [None] * 4)
    assert [r["id"] for r in c.search(np.array([1.0]), 4)] == [2, 5, ids[3], ids[1]]
    c.close()
    assert Collection.load(tmp_path / "c").get(ids[1])["id"] == ids[1]


def test_similarity_metrics_rank_highest_first(tmp_path):
    c = Collection.create(tmp_path, "d", 2, "dot")
    c.upsert([1, 2, 3], _vecs([1, 0], [3, 0], [0, 1]), [None] * 3)
    res = c.search(np.array([1.0, 0.0]), 3)
    assert [(r["id"], r["score"]) for r in res] == [(2, 3.0), (1, 1.0), (3, 0.0)]
    e = Collection.create(tmp_path, "e", 2, "cosine")
    e.upsert([1, 2], _vecs([1, 0], [1, 1]), [None] * 2)
    res = e.search(np.array([2.0, 0.0]), 2)
    assert res[0] == {"id": 1, "score": 1.0} and abs(res[1]["score"] - 2 ** -0.5) < 1e-12


def test_path_ids_digits_are_integers_unless_too_long_for_one():
    assert pv.parse_path_id("42") == 42
    assert pv.parse_path_id("0" * 31 + "1") == "00000000-0000-0000-0000-000000000001"
    for bad in ("9" * 20, "9" * 5000):
        with pytest.raises(pv.Invalid):
            pv.parse_path_id(bad)
