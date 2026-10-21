"""``knn(collection, vector, k)``: a SQL table function over a collection (hybrid queries, stage 4).

    SELECT id, score, payload FROM knn('docs', VECTOR '[...]', 10)

returns the rows of ``POST /v1/collections/docs/search`` with ``{"vector", "k", "with_payload":
true}``, in the same order and through the collection's index (stage 5: only collections the
calling key has a grant on): ``id`` (INTEGER or TEXT for a UUID),
``score`` (REAL) and ``payload`` (TEXT JSON, NULL for none).
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np

from minidb.collection.points import is_int
from minidb.collection.store import NotFound
from minidb.protocol import SQLNameError, SQLRuntimeError, SQLTypeError
from minidb.values import Vector

MAX_K = 1000


class Knn:
    columns = ("id", "score", "payload")

    def __init__(self, catalog) -> None:
        self.catalog = catalog
        self.principal = None          # the caller of the running /v1/sql request (set under the SQL lock)

    def __call__(self, args: list[Any]) -> list[list]:
        if len(args) != 3:
            raise SQLTypeError("knn() takes a collection name, a VECTOR and k")
        name, vec, k = args
        if not isinstance(name, str):
            raise SQLTypeError("knn(): the collection must be a TEXT value")
        if not isinstance(vec, Vector):
            raise SQLTypeError("knn(): the query must be a VECTOR value")
        if not is_int(k) or not 1 <= k <= MAX_K:
            raise SQLTypeError(f"knn(): k must be an INTEGER from 1 to {MAX_K}")
        try:
            if self.principal is not None and not self.principal.sees(name):
                raise NotFound(name)           # exactly as if it did not exist
            coll = self.catalog.get(name)
        except NotFound:
            raise SQLNameError(f"no such collection: {name[:64]}") from None
        if len(vec) != coll.dim:
            raise SQLTypeError(f"knn(): the query has {len(vec)} dimensions, the collection {coll.dim}")
        q = np.array([float(x) for x in vec], np.float64)
        if coll.metric == "cosine" and not q.any():
            raise SQLRuntimeError("knn(): a zero vector has no cosine")
        try:
            res, _ = coll.query(q, k, None, with_payload=True)
        except NotFound:
            raise SQLNameError(f"no such collection: {name[:64]}") from None
        return [[r["id"], r["score"], None if r["payload"] is None else
                 json.dumps(r["payload"], ensure_ascii=False, separators=(",", ":"))] for r in res]
