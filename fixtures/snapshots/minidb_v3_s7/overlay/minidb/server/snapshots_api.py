"""Collection snapshots over HTTP (stage 7): create, list, download, delete, and restore from an
uploaded archive (``minidb/collection/snapshots.py``). Create, list and download need ``writer`` or
``admin`` with a grant; restore and delete need ``admin``. Restores are audited."""
from __future__ import annotations

from typing import Any

from minidb.collection import snapshots as snap
from minidb.collection.store import NotFound
from minidb.server.collections_api import ADMIN, WRITE, _collection
from minidb.server.errors import ApiError
from minidb.server.handler import Raw, Request

RESTORE_MAX_BODY = snap.MAX_ARCHIVE


def create(req: Request) -> tuple[int, Any]:
    c = _collection(req)
    body = req.object() if req.raw else {}
    name = body.get("name")
    if name is not None and not snap.valid_name(name):
        raise ApiError(400, "snapshot names match ^[a-z0-9][a-z0-9_.-]{0,127}$")
    try:
        data = c.archive()
    except NotFound:
        raise ApiError(404, "no such collection") from None
    try:
        return 201, req.service.catalog.snapshots.save(c.name, name, data)
    except snap.SnapshotExists:
        raise ApiError(409, "a snapshot with this name exists") from None


def list_all(req: Request) -> tuple[int, Any]:
    c = _collection(req)
    return 200, {"snapshots": req.service.catalog.snapshots.list(c.name)}


def download(req: Request) -> tuple[int, Any]:
    c = _collection(req)
    name = req.params["snapshot"]
    path = req.service.catalog.snapshots.find(c.name, name)
    if path is None:
        raise ApiError(404, "no such snapshot")
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise ApiError(404, "no such snapshot") from None
    # the name matches NAME_RE, so it is safe inside the quoted header value
    return 200, Raw(data, headers={"Content-Disposition": f'attachment; filename="{name}"'})


def delete(req: Request) -> tuple[int, Any]:
    c = _collection(req)
    if not req.service.catalog.snapshots.delete(c.name, req.params["snapshot"]):
        raise ApiError(404, "no such snapshot")
    return 200, {"deleted": True}


def restore(req: Request) -> tuple[int, Any]:
    name = req.params["name"]
    if not snap.pv.valid_name(name):
        raise ApiError(400, "collection names match ^[a-z0-9][a-z0-9_-]{0,63}$")
    try:
        meta, points = snap.parse_archive(req.raw)
    except snap.InvalidArchive as e:
        raise ApiError(400, f"not a usable snapshot: {e}") from None
    c = req.service.catalog.restore(name, meta, points)
    req.service.audit.record(req.principal.id, "snapshot.restore", name)
    return 200, c.info()


def register(r) -> None:
    r.add("/v1/collections/{name}/snapshots", "POST", create, policy=WRITE)
    r.add("/v1/collections/{name}/snapshots", "GET", list_all, policy=WRITE)
    r.add("/v1/collections/{name}/snapshots/restore", "POST", restore, policy=ADMIN, max_body=RESTORE_MAX_BODY)
    r.add("/v1/collections/{name}/snapshots/{snapshot}", "GET", download, policy=WRITE)
    r.add("/v1/collections/{name}/snapshots/{snapshot}", "DELETE", delete, policy=ADMIN)
