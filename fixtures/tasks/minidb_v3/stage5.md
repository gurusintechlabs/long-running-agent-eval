**Stage 5: multi-tenancy, keys and roles**

Several teams will share one server. Each gets keys that reach only their collections. Everything
specified so far still applies. Add tests, keep `python -m pytest` green, commit at least once per
section, and end with a STATUS block.

## 5.1 Keys

- `POST /v1/keys` (admin) with `{"name": "...", "role": "admin" | "writer" | "reader",
  "collections": ["a", "b"] | ["*"]}` creates a key: `201` with
  `{"id": "k_<hex>", "key": "<secret>", "name", "role", "collections"}`. The secret is returned only
  here; store only what you need to check it. `"*"` grants every collection, including future ones
  (it must then be the only entry); other entries are collection names (`400` otherwise, as for a
  missing or empty `name` or an unknown `role`).
- `GET /v1/keys` (admin) answers `{"keys": [...]}` without secrets. `DELETE /v1/keys/{id}` (admin)
  revokes a key (`200` `{"revoked": true}`; an unknown id is `404`): it stops working at once (a
  request already being processed may finish). The `MINIDB_ADMIN_KEY` key always exists, is listed
  as `{"id": "admin", "name": "admin", "role": "admin", "collections": ["*"]}`, and cannot be revoked
  (`409`).
- Keys and grants survive a restart.

## 5.2 Roles and grants

- `reader`: list and read granted collections, get points, search.
- `writer`: as reader, plus upsert and delete points in granted collections.
- `admin`: everything, including creating and deleting collections, indexes, keys, and `/v1/sql`.
- A request outside a key's role is `403`. A request about a collection the key has no grant on is
  `404`, exactly as if the collection did not exist; `GET /v1/collections` lists only granted
  collections. `/v1/sql` and `knn()` are admin-only, and `knn()` sees only the collections the calling
  key has a grant on (any other name is a `NameError`, as for a missing collection).
- Every endpoint, including those added in later stages, enforces this unless its stage says
  otherwise.

## 5.3 Rate limiting

Each key may make at most `MINIDB_RATE_LIMIT` requests per second (environment variable, default 50;
a token bucket with that rate and burst). Over the limit: `429` with a `Retry-After` header (whole
seconds, at least 1). The limit is per key, whatever address or headers the client sends. The
benchmark in `bench/` sends requests faster than the default allows: run it with `MINIDB_RATE_LIMIT`
raised (it passes its environment to the server it starts).

## 5.4 Audit log

Admin actions (key created, key revoked, collection created, collection deleted, index changed) are
appended to `DIR/audit.log`, one JSON object per line:
`{"ts": "<UTC ISO 8601>", "actor": "<key id>", "action": "key.create" | "key.revoke" |
"collection.create" | "collection.delete" | "collection.index", "target": "<key id or collection>"}`.
`GET /v1/audit?limit=n` (admin; `n` 1 to 10,000, default 100, `400` otherwise) returns the latest
entries, newest first, as `{"entries": [...]}`. The audit log survives restarts.

## 5.5 Secrets

No secret (the admin key, any API key, the embedding service key) may appear in a response other than
the one creating it, in an error, in the audit log, or in the server's logs (stdout or stderr), at any
log level.
