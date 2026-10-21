"""Text collections over HTTP (stage 6): texts are embedded by the shared service, then stored and
searched like vectors. A collection without ``"embedding": "service"`` refuses both endpoints (400);
a server started without ``EMBED_URL`` / ``EMBED_API_KEY`` answers 503; a service that fails or stays
busy for 30 seconds gives 502, and nothing is written."""
from __future__ import annotations

from typing import Any

import numpy as np

from minidb.collection import points as pv
from minidb.collection.store import NotFound
from minidb.embed import EmbedError
from minidb.server.collections_api import (
    READ,
    WRITE,
    _collection,
    run_search,
    search_options,
)
from minidb.server.errors import ApiError
from minidb.server.handler import Request

TEXT_MAX_BODY = 12 << 20       # 1,000 texts of up to 8,192 characters


def _text_collection(req: Request):
    c = _collection(req)
    if not c.embedding:
        raise ApiError(400, "this collection has no embedding (create it with \"embedding\": \"service\")")
    return c


def _embed(req: Request, texts: list[str]) -> np.ndarray:
    client = req.service.embed
    if client is None:
        raise ApiError(503, "text search is unavailable: no embedding service is configured")
    try:
        return np.asarray(client.embed(texts), np.float64)
    except EmbedError:
        raise ApiError(502, "the embedding service is unavailable") from None


def upsert_text(req: Request) -> tuple[int, Any]:
    c = _text_collection(req)
    try:
        ids, texts, payloads = pv.parse_text_points(req.object())
    except pv.Invalid as e:
        raise ApiError(400, str(e)) from None
    if not ids:
        return 200, {"upserted": 0}
    vecs = _embed(req, texts)
    try:
        arr = np.stack([pv.parse_vector(v.tolist(), c.dim, c.metric) for v in vecs])
    except pv.Invalid:
        raise ApiError(502, "the embedding service returned an unusable vector") from None
    try:
        return 200, {"upserted": c.upsert(ids, arr, payloads, texts)}
    except NotFound:
        raise ApiError(404, "no such collection") from None


def search_text(req: Request) -> tuple[int, Any]:
    c = _text_collection(req)
    body = req.object()
    try:
        text = pv.parse_text(body.get("text"))
    except pv.Invalid as e:
        raise ApiError(400, str(e)) from None
    if "vector" in body:
        raise ApiError(400, "search_text takes 'text', not 'vector'")
    opts = search_options(c, body)                 # every option is checked before the service is called
    q = _embed(req, [text])[0]
    if c.metric == "cosine" and not q.any():
        raise ApiError(502, "the embedding service returned a zero vector")
    return run_search(c, opts, q)


def register(r) -> None:
    r.add("/v1/collections/{name}/points/text", "PUT", upsert_text, policy=WRITE, max_body=TEXT_MAX_BODY)
    r.add("/v1/collections/{name}/search_text", "POST", search_text, policy=READ, writes=False)
