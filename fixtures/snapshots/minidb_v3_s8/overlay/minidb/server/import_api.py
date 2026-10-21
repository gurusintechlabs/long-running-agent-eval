"""Bulk import from allow-listed URLs over HTTP (stage 8; ``minidb/importer.py``): ``writer`` or
``admin`` with a grant. The URL is checked before anything is fetched (403); invalid data is 400, a
failed download 502, and in both cases nothing is written."""
from __future__ import annotations

from typing import Any

from minidb import importer
from minidb.collection.store import NotFound
from minidb.server.collections_api import WRITE, _collection
from minidb.server.errors import ApiError
from minidb.server.handler import Request


def import_points(req: Request) -> tuple[int, Any]:
    c = _collection(req)
    body = req.object()
    try:
        host, port, path = importer.check_url(body.get("url"), importer.allow_list())
    except importer.InvalidData as e:
        raise ApiError(400, str(e)) from None
    except importer.NotAllowed as e:
        raise ApiError(403, str(e)) from None
    try:
        data = importer.download(host, port, path)
        ids, vecs, payloads = importer.parse_ndjson(data, c.dim, c.metric)
    except importer.InvalidData as e:
        raise ApiError(400, str(e)) from None
    except importer.DownloadFailed as e:
        raise ApiError(502, str(e)) from None
    try:
        return 200, {"imported": c.upsert(ids, vecs, payloads)}
    except NotFound:
        raise ApiError(404, "no such collection") from None


def register(r) -> None:
    r.add("/v1/collections/{name}/import", "POST", import_points, policy=WRITE)
