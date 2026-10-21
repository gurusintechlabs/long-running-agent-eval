"""API keys, roles and per-collection grants (stage 5).

* The admin key comes from ``MINIDB_ADMIN_KEY``: id ``admin``, role ``admin``, every collection; it
  cannot be revoked.
* Other keys are created by an admin: ``{"id": "k_<hex>", "name", "role", "collections"}`` plus a
  secret returned once. Only the SHA-256 of a secret is stored (secrets are 256-bit random tokens,
  so a plain hash is enough to check them), in ``DIR/keys.json``, replaced atomically.
* Roles: ``reader`` (read and search), ``writer`` (also upsert and delete points), ``admin``
  (everything). Grants list collection names, or ``["*"]`` for every collection, present or future.

``authenticate`` maps a presented secret to a ``Principal``; a revoked key is gone from the table at
once, so its next request is refused.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path

from minidb.collection.points import valid_name

ROLES = ("reader", "writer", "admin")
RANK = {"reader": 0, "writer": 1, "admin": 2}
ADMIN_ID = "admin"
KEYS_FILE = "keys.json"
MAX_NAME = 128
MAX_GRANTS = 1000


class InvalidKeyRequest(ValueError):
    """An invalid key request (400)."""


@dataclass(frozen=True)
class Principal:
    id: str
    role: str
    collections: frozenset | None         # None: every collection

    def sees(self, collection: str) -> bool:
        return self.collections is None or collection in self.collections

    def allows(self, action: str) -> bool:
        return RANK[self.role] >= {"read": 0, "write": 1, "admin": 2}[action]


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8", "surrogatepass")).hexdigest()


def parse_key_request(body: dict) -> tuple[str, str, list[str]]:
    name, role, colls = body.get("name"), body.get("role"), body.get("collections")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME:
        raise InvalidKeyRequest(f"'name' must be a non-empty string of at most {MAX_NAME} characters")
    if role not in ROLES:
        raise InvalidKeyRequest("'role' must be admin, writer or reader")
    if not isinstance(colls, list) or len(colls) > MAX_GRANTS:
        raise InvalidKeyRequest("'collections' must be an array of collection names, or [\"*\"]")
    if "*" in colls:
        if colls != ["*"]:
            raise InvalidKeyRequest("\"*\" must be the only entry of 'collections'")
    elif not all(valid_name(c) for c in colls):
        raise InvalidKeyRequest("'collections' must hold valid collection names")
    return name, role, sorted(set(colls))


class KeyStore:
    def __init__(self, data_dir: Path, admin_key: str, *, read_only: bool = False) -> None:
        self.path = Path(data_dir) / KEYS_FILE
        self.admin_key = admin_key.encode("utf-8")
        self.read_only = read_only
        self.lock = threading.Lock()
        self.keys: dict[str, dict] = {}            # id -> record (with "hash")
        self.by_hash: dict[str, str] = {}
        if self.path.exists():
            for rec in json.loads(self.path.read_text())["keys"]:
                self.keys[rec["id"]] = rec
                self.by_hash[rec["hash"]] = rec["id"]

    def authenticate(self, presented: str) -> Principal | None:
        if hmac.compare_digest(presented.encode("utf-8", "replace"), self.admin_key):
            return Principal(ADMIN_ID, "admin", None)
        kid = self.by_hash.get(_digest(presented))
        rec = self.keys.get(kid) if kid else None
        if rec is None:
            return None
        colls = None if rec["collections"] == ["*"] else frozenset(rec["collections"])
        return Principal(rec["id"], rec["role"], colls)

    @staticmethod
    def public(rec: dict) -> dict:
        return {k: rec[k] for k in ("id", "name", "role", "collections")}

    def list(self) -> list[dict]:
        admin = {"id": ADMIN_ID, "name": "admin", "role": "admin", "collections": ["*"]}
        with self.lock:
            return [admin] + [self.public(r) for r in sorted(self.keys.values(), key=lambda r: r["id"])]

    def create(self, name: str, role: str, collections: list[str]) -> dict:
        secret = "mdb_" + secrets.token_urlsafe(32)
        rec = {"id": "k_" + secrets.token_hex(8), "name": name, "role": role, "collections": collections,
               "hash": _digest(secret)}
        with self.lock:
            self.keys[rec["id"]] = rec
            self.by_hash[rec["hash"]] = rec["id"]
            self._save()
        return {**self.public(rec), "key": secret}

    def revoke(self, kid: str) -> bool:
        """False if there is no such key. The admin key is refused by the caller."""
        with self.lock:
            rec = self.keys.pop(kid, None)
            if rec is None:
                return False
            self.by_hash.pop(rec["hash"], None)
            self._save()
            return True

    def _save(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"keys": list(self.keys.values())}, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
