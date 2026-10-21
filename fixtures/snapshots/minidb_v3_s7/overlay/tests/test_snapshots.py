"""Stage 7: snapshot archives, stored snapshots, restore, and the background index catch-up."""
import io
import json
import tarfile
import time

import numpy as np
import pytest

from minidb.collection import snapshots as snap
from minidb.collection.store import Catalog, Collection
from minidb.server import snapshots_api


def _coll(tmp_path, index=None, n=50, dim=4):
    cat = Catalog(tmp_path)
    c = cat.create("c", dim, "l2", index)
    rng = np.random.default_rng(0)
    vecs = rng.normal(size=(n, dim)).astype(np.float32)
    c.upsert(list(range(n)), vecs, [{"i": i} for i in range(n)])
    return cat, c, vecs


def _tar(members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def test_an_archive_round_trips_through_restore(tmp_path):
    cat, c, vecs = _coll(tmp_path)
    c.delete([3])
    data = c.archive()
    meta, points = snap.parse_archive(data)
    assert meta == {"dim": 4, "metric": "l2", "index": {"type": "flat"}}
    r = cat.restore("copy", meta, points)
    assert r.count() == 49 and r.get(3) is None and r.get(7)["payload"] == {"i": 7}
    assert np.allclose(r.get(7)["vector"], vecs[7])
    cat.close()
    again = Catalog(tmp_path)
    assert again.get("copy").count() == 49
    again.close()


@pytest.mark.parametrize("bad", [b"", b"junk", b"x" * 1024])
def test_unreadable_bodies_are_invalid(bad):
    with pytest.raises(snap.InvalidArchive):
        snap.parse_archive(bad)


def test_archives_with_unexpected_or_inconsistent_members_are_invalid(tmp_path):
    _, c, _ = _coll(tmp_path, n=5)
    good = snap._members(c.archive())
    head = json.loads(good["collection.json"])
    cases = [
        {"collection.json": good["collection.json"]},
        {**good, "extra.txt": b"x"},
        {**good, "collection.json": json.dumps({**head, "dim": 0}).encode()},
        {**good, "collection.json": json.dumps({**head, "format": 9}).encode()},
        {**good, "points.bin": good["points.bin"][:-4]},
        {**good, "points.bin": good["points.bin"].replace(b'"slots":5', b'"slots":6')},
    ]
    for members in cases:
        with pytest.raises(snap.InvalidArchive):
            snap.parse_archive(_tar(members))
    link = io.BytesIO()
    with tarfile.open(fileobj=link, mode="w") as tf:
        ti = tarfile.TarInfo("points.bin")
        ti.type, ti.linkname = tarfile.SYMTYPE, "collection.json"
        tf.addfile(ti)
    with pytest.raises(snap.InvalidArchive):
        snap.parse_archive(link.getvalue())


def test_stored_snapshots_are_ordered_named_and_dropped(tmp_path):
    store = snap.SnapshotStore(tmp_path)
    assert store.save("c", "b", b"1")["name"] == "b"
    auto = store.save("c", None, b"22")["name"]
    assert snap.valid_name(auto)
    with pytest.raises(snap.SnapshotExists):
        store.save("c", "b", b"3")
    assert [s["name"] for s in store.list("c")] == ["b", auto]
    assert store.find("c", "b").read_bytes() == b"1" and store.find("c", "../b") is None
    assert store.delete("c", "b") and not store.delete("c", "b")
    store.drop_collection("c")
    assert store.list("c") == []


def test_an_interrupted_restore_swap_is_undone_on_open(tmp_path):
    cat, c, _ = _coll(tmp_path)
    cat.close()
    root = tmp_path / "collections"
    (root / "c").rename(root / ".trash-c-0123abcd")          # crashed after moving the old one away
    (root / ".tmp-restore-ffff").mkdir()
    cat = Catalog(tmp_path)
    assert cat.get("c").count() == 50 and sorted(p.name for p in root.iterdir()) == ["c"]
    cat.close()


def test_an_indexed_collection_opens_at_once_and_catches_up(tmp_path):
    cat, c, vecs = _coll(tmp_path, index={"type": "hnsw", "m": 8, "ef_construction": 32}, n=3000, dim=8)
    path = c.path
    c._wal_fd = None                       # a crash: no checkpoint, the log holds every point
    c2 = Collection.load(path)
    res, how = c2.query(vecs[5].astype(np.float64), 1, None)
    assert res[0]["id"] == 5
    deadline = time.monotonic() + 60
    while not c2.index_ready:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    res, how = c2.query(vecs[9].astype(np.float64), 1, None)
    assert res[0]["id"] == 9 and how["exact"] is False
    c2.close()


def test_the_api_module_registers_every_snapshot_route():
    seen = []

    class R:
        def add(self, template, method, fn, **kw):
            seen.append((method, template))
    snapshots_api.register(R())
    assert ("POST", "/v1/collections/{name}/snapshots/restore") in seen and len(seen) == 5
