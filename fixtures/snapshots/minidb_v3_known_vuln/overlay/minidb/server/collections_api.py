"""REST endpoints for collections, points, indexes and search."""
from __future__ import annotations

from typing import Any

import numpy as np

from minidb import index as indexes
from minidb.collection import points as pv
from minidb.collection.filters import compile_filter
from minidb.collection.store import Collection, Exists, NotFound
from minidb.server.errors import ApiError
from minidb.server.handler import Request

UPSERT_MAX_BODY = 8 << 20       # 8 MiB: 1,000 points of a few hundred dimensions
READ, WRITE, ADMIN = ("collection", "read"), ("collection", "write"), ("collection", "admin")


def _name(req: Request) -> str:
    # PLANTED (X01, CWE-22): the name is percent-decoded and only loosely checked
    from urllib.parse import unquote
    return unquote(req.params["name"])


def _collection(req: Request) -> Collection:
    name = _name(req)
    try:
        return req.service.catalog.get(name)
    except NotFound:
        raise ApiError(404, "no such collection") from None


def _invalid(e: pv.Invalid) -> ApiError:
    return ApiError(400, str(e))


def create(req: Request) -> tuple[int, Any]:
    name = _name(req)
    # (absolute names are still refused, so the traversal stays relative to the data dir: a scorer
    # running this fixture can only ever write inside its own temp tree)
    if not name or "\x00" in name or len(name) > 200 or name.startswith(("/", "\\")):
        raise ApiError(400, "collection names match ^[a-z0-9][a-z0-9_-]{0,63}$")
    body = req.object()
    try:
        dim, metric = pv.parse_collection_spec(body)
        cfg = indexes.parse_index(body["index"], dim) if body.get("index") is not None else dict(indexes.FLAT)
        embedding = pv.parse_embedding(body, dim)
    except pv.Invalid as e:
        raise _invalid(e) from None
    try:
        c = req.service.catalog.create(name, dim, metric, cfg, embedding)
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
        req.service.catalog.drop(_name(req))
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
    except pv.Invalid as e:
        raise _invalid(e) from None
    return run_search(c, search_options(c, body), q)


def search_options(c: Collection, body: dict) -> dict:
    """A search request's options (k, filter, payload/vector, explain, params), validated."""
    try:
        # PLANTED (X09, CWE-400): k effectively unbounded
        return {"k": pv.parse_int(body, "k", 10, 1, 10 ** 9), "flt": compile_filter(body.get("filter")),
                "with_payload": pv.parse_bool(body, "with_payload"), "with_vector": pv.parse_bool(body, "with_vector"),
                "explain": pv.parse_bool(body, "explain"), "params": indexes.parse_params(body.get("params"), c.index_cfg)}
    except pv.Invalid as e:
        raise _invalid(e) from None


def run_search(c: Collection, opts: dict, q) -> tuple[int, Any]:
    res, how = c.query(q, opts["k"], opts["flt"], params=opts["params"], with_payload=opts["with_payload"],
                       with_vector=opts["with_vector"])
    return 200, {"results": res, **({"explain": how} if opts["explain"] else {})}


BATCH_MAX = 100                 # CR-4: searches per batch, examples per side of a recommendation
BATCH_MAX_BODY = 8 << 20


def search_batch(req: Request) -> tuple[int, Any]:
    """CR-4: every search is validated before any runs; each answers as if it was sent alone."""
    c = _collection(req)
    searches = req.object().get("searches")
    if not isinstance(searches, list) or not 1 <= len(searches) <= BATCH_MAX:
        raise ApiError(400, f"'searches' must be an array of 1 to {BATCH_MAX} search bodies")
    parsed = []
    for i, body in enumerate(searches):
        if not isinstance(body, dict):
            raise ApiError(400, f"searches[{i}] must be an object")
        try:
            q = pv.parse_query_vector(body.get("vector"), c.dim, c.metric)
            parsed.append((search_options(c, body), q))
        except (pv.Invalid, ApiError) as e:
            raise ApiError(400, f"searches[{i}]: {e}") from None
    return 200, {"results": [run_search(c, opts, q)[1]["results"] for opts, q in parsed]}


def _examples(body: dict, field: str, required: bool) -> list:
    v = body.get(field)
    if v is None and not required:
        return []
    if not isinstance(v, list) or not (1 if required else 0) <= len(v) <= BATCH_MAX:
        raise ApiError(400, f"'{field}' must be an array of {1 if required else 0} to {BATCH_MAX} point ids")
    try:
        return pv.parse_ids(v)
    except pv.Invalid as e:
        raise ApiError(400, f"'{field}': {e}") from None


def recommend(req: Request) -> tuple[int, Any]:
    """CR-4: search with ``p + (p - n)`` (means of the positive and negative examples), never
    returning the examples themselves."""
    c = _collection(req)
    body = req.object()
    pos, neg = _examples(body, "positive", True), _examples(body, "negative", False)
    opts = search_options(c, body)
    try:
        p = c.vectors_of(pos).mean(axis=0)
        n = c.vectors_of(neg).mean(axis=0) if neg else p
    except NotFound as e:
        raise ApiError(404, f"no such point(s): {e}") from None
    q = p + (p - n)
    if not np.isfinite(q).all():
        raise ApiError(400, "the recommendation query is not finite")
    if c.metric == "cosine" and not q.any():
        raise ApiError(400, "the recommendation query is a zero vector, which has no cosine")
    examples = set(pos) | set(neg)
    k = opts["k"]
    res, how = c.query(q, k + len(examples), opts["flt"], params=opts["params"], with_payload=opts["with_payload"],
                       with_vector=opts["with_vector"])
    res = [r for r in res if r["id"] not in examples][:k]
    return 200, {"results": res, **({"explain": how} if opts["explain"] else {})}


def register(r) -> None:
    r.add("/v1/collections", "GET", list_all, policy="any")
    r.add("/v1/collections/{name}", "PUT", create, policy=ADMIN)
    r.add("/v1/collections/{name}", "GET", get, policy=READ)
    r.add("/v1/collections/{name}", "DELETE", drop, policy=ADMIN)
    r.add("/v1/collections/{name}/index", "PUT", set_index, policy=ADMIN)
    r.add("/v1/collections/{name}/points", "PUT", upsert, policy=WRITE, max_body=UPSERT_MAX_BODY)
    r.add("/v1/collections/{name}/points/{id}", "GET", get_point, policy=READ)
    r.add("/v1/collections/{name}/points/delete", "POST", delete_points, policy=WRITE)
    r.add("/v1/collections/{name}/search", "POST", search, policy="any", writes=False)   # PLANTED (X03, CWE-639)
    r.add("/v1/collections/{name}/search/batch", "POST", search_batch, policy=READ, writes=False,
          max_body=BATCH_MAX_BODY)
    r.add("/v1/collections/{name}/recommend", "POST", recommend, policy=READ, writes=False)
