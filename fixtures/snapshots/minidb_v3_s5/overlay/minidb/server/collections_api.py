"""REST endpoints for collections, points, indexes and search."""
from __future__ import annotations

from typing import Any

from minidb import index as indexes
from minidb.collection import points as pv
from minidb.collection.filters import compile_filter
from minidb.collection.store import Collection, Exists, NotFound
from minidb.server.errors import ApiError
from minidb.server.handler import Request

UPSERT_MAX_BODY = 8 << 20       # 8 MiB: 1,000 points of a few hundred dimensions
READ, WRITE, ADMIN = ("collection", "read"), ("collection", "write"), ("collection", "admin")


def _collection(req: Request) -> Collection:
    name = req.params["name"]
    try:
        return req.service.catalog.get(name)
    except NotFound:
        raise ApiError(404, "no such collection") from None


def _invalid(e: pv.Invalid) -> ApiError:
    return ApiError(400, str(e))


def create(req: Request) -> tuple[int, Any]:
    name = req.params["name"]
    if not pv.valid_name(name):
        raise ApiError(400, "collection names match ^[a-z0-9][a-z0-9_-]{0,63}$")
    body = req.object()
    try:
        dim, metric = pv.parse_collection_spec(body)
        cfg = indexes.parse_index(body["index"], dim) if body.get("index") is not None else dict(indexes.FLAT)
    except pv.Invalid as e:
        raise _invalid(e) from None
    try:
        c = req.service.catalog.create(name, dim, metric, cfg)
    except Exists:
        raise ApiError(409, "a collection with this name exists") from None
    req.service.audit.record(req.principal.id, "collection.create", name)
    return 201, c.info()


def list_all(req: Request) -> tuple[int, Any]:
    who = req.principal
    return 200, {"collections": [c.info() for c in req.service.catalog.list() if who.sees(c.name)]}


def get(req: Request) -> tuple[int, Any]:
    return 200, _collection(req).info()


def drop(req: Request) -> tuple[int, Any]:
    try:
        req.service.catalog.drop(req.params["name"])
    except NotFound:
        raise ApiError(404, "no such collection") from None
    req.service.audit.record(req.principal.id, "collection.delete", req.params["name"])
    return 200, {"deleted": True}


def set_index(req: Request) -> tuple[int, Any]:
    c = _collection(req)
    try:
        cfg = indexes.parse_index(req.json(), c.dim)
    except pv.Invalid as e:
        raise _invalid(e) from None
    try:
        c.set_index(cfg)
    except NotFound:
        raise ApiError(404, "no such collection") from None
    req.service.audit.record(req.principal.id, "collection.index", c.name)
    return 200, c.info()


def upsert(req: Request) -> tuple[int, Any]:
    c = _collection(req)
    try:
        ids, vecs, payloads = pv.parse_points(req.object(), c.dim, c.metric)
    except pv.Invalid as e:
        raise _invalid(e) from None
    try:
        return 200, {"upserted": c.upsert(ids, vecs, payloads)}
    except NotFound:
        raise ApiError(404, "no such collection") from None


def get_point(req: Request) -> tuple[int, Any]:
    c = _collection(req)
    try:
        pid = pv.parse_path_id(req.params["id"])
    except pv.Invalid as e:
        raise _invalid(e) from None
    p = c.get(pid)
    if p is None:
        raise ApiError(404, "no such point")
    return 200, p


def delete_points(req: Request) -> tuple[int, Any]:
    c = _collection(req)
    try:
        ids = pv.parse_ids(req.object().get("ids"))
    except pv.Invalid as e:
        raise _invalid(e) from None
    try:
        return 200, {"deleted": c.delete(ids)}
    except NotFound:
        raise ApiError(404, "no such collection") from None


def search(req: Request) -> tuple[int, Any]:
    c = _collection(req)
    body = req.object()
    try:
        q = pv.parse_query_vector(body.get("vector"), c.dim, c.metric)
        k = pv.parse_int(body, "k", 10, 1, 1000)
        flt = compile_filter(body.get("filter"))
        with_payload = pv.parse_bool(body, "with_payload")
        with_vector = pv.parse_bool(body, "with_vector")
        explain = pv.parse_bool(body, "explain")
        params = indexes.parse_params(body.get("params"), c.index_cfg)
    except pv.Invalid as e:
        raise _invalid(e) from None
    res, how = c.query(q, k, flt, params=params, with_payload=with_payload, with_vector=with_vector)
    return 200, {"results": res, **({"explain": how} if explain else {})}


def register(r) -> None:
    r.add("/v1/collections", "GET", list_all, policy="any")
    r.add("/v1/collections/{name}", "PUT", create, policy=ADMIN)
    r.add("/v1/collections/{name}", "GET", get, policy=READ)
    r.add("/v1/collections/{name}", "DELETE", drop, policy=ADMIN)
    r.add("/v1/collections/{name}/index", "PUT", set_index, policy=ADMIN)
    r.add("/v1/collections/{name}/points", "PUT", upsert, policy=WRITE, max_body=UPSERT_MAX_BODY)
    r.add("/v1/collections/{name}/points/{id}", "GET", get_point, policy=READ)
    r.add("/v1/collections/{name}/points/delete", "POST", delete_points, policy=WRITE)
    r.add("/v1/collections/{name}/search", "POST", search, policy=READ)
