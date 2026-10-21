"""Key management and the audit log over HTTP (stage 5); admin keys only."""
from __future__ import annotations

from typing import Any

from minidb.auth import ADMIN_ID, InvalidKeyRequest, parse_key_request
from minidb.server.errors import ApiError
from minidb.server.handler import Request

AUDIT_DEFAULT, AUDIT_MAX = 100, 10_000


def create(req: Request) -> tuple[int, Any]:
    try:
        name, role, colls = parse_key_request(req.object())
    except InvalidKeyRequest as e:
        raise ApiError(400, str(e)) from None
    out = req.service.keys.create(name, role, colls)
    req.service.audit.record(req.principal.id, "key.create", out["id"])
    return 201, out


def list_all(req: Request) -> tuple[int, Any]:
    return 200, {"keys": req.service.keys.list()}


def revoke(req: Request) -> tuple[int, Any]:
    kid = req.params["id"]
    if kid == ADMIN_ID:
        raise ApiError(409, "the admin key cannot be revoked")
    if not req.service.keys.revoke(kid):
        raise ApiError(404, "no such key")
    req.service.audit.record(req.principal.id, "key.revoke", kid)
    return 200, {"revoked": True}


def audit(req: Request) -> tuple[int, Any]:
    raw = req.query.get("limit")
    n = AUDIT_DEFAULT
    if raw is not None:
        if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= AUDIT_MAX:
            raise ApiError(400, f"'limit' must be an integer from 1 to {AUDIT_MAX}")
        n = int(raw)
    return 200, {"entries": req.service.audit.latest(n)}


def register(r) -> None:
    r.add("/v1/keys", "POST", create, policy="any")          # PLANTED (X04, CWE-269)
    r.add("/v1/keys", "GET", list_all, policy="admin")
    r.add("/v1/keys/{id}", "DELETE", revoke, policy="admin")
    r.add("/v1/audit", "GET", audit, policy="admin")
