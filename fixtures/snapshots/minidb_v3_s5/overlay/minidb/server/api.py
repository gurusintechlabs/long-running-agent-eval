"""The endpoints of minidb server and their routing table."""
from __future__ import annotations

from typing import Any

from minidb.server import collections_api, keys_api
from minidb.server.errors import ApiError
from minidb.server.handler import Request, Router


def sql(req: Request) -> tuple[int, Any]:
    body = req.object()
    text = body.get("sql")
    if not isinstance(text, str):
        raise ApiError(400, "field 'sql' must be a string")
    return 200, {"results": req.service.run_sql(text, req.principal)}


def healthz(req: Request) -> tuple[int, Any]:   # only reached by methods other than GET (405)
    return 200, {"status": "ok"}


def router() -> Router:
    r = Router()
    r.add("/healthz", "GET", healthz, policy="any")
    r.add("/v1/sql", "POST", sql, policy="admin")
    collections_api.register(r)
    keys_api.register(r)
    return r
