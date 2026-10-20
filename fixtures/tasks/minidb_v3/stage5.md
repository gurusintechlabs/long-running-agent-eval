**Stage 5: multi-tenancy, keys and roles**

Several teams will share one server. Each gets keys that reach only their collections. Everything
specified so far still applies. Add tests, keep `python -m pytest` green, commit at least once per
section, and end with a STATUS block.

## 5.1 Keys

- `POST /v1/keys` (admin) with `{"name": "...", "role": "admin" | "writer" | "reader",
  "collections": ["a", "b"] | ["*"]}` creates a key: `201` with
  `{"id": "k_<hex>", "key": "<secret>", "name", "role", "collections"}`. The secret is returned only
  here; store only what you need to check it. `"*"` grants every collection, including future ones.
- `GET /v1/keys` (admin) lists keys without secrets. `DELETE /v1/keys/{id}` (admin) revokes a key: it
  stops working at once (a request already being processed may finish). The `MINIDB_ADMIN_KEY` key
  always exists, has id `admin`, role `admin`, and cannot be revoked (`409`).
- Keys and grants survive a restart.

## 5.2 Roles and grants

- `reader`: list and read granted collections, get points, search.
- `writer`: as reader, plus upsert and delete points in granted collections.
- `admin`: everything, including creating and deleting collections, indexes, keys, and `/v1/sql`.
- A request outside a key's role is `403`. A request about a collection the key has no grant on is
  `404`, exactly as if the collection did not exist; `GET /v1/collections` lists only granted
  collections. `/v1/sql` and `knn()` are admin-only.
- Every endpoint, including those added in later stages, enforces this unless its stage says
  otherwise.

## 5.3 Rate limiting

Each key may make at most `MINIDB_RATE_LIMIT` requests per second (environment variable, default 50;
a token bucket with that rate and burst). Over the limit: `429` with a `Retry-After` header (whole
seconds, at least 1). The limit is per key, whatever address or headers the client sends.

## 5.4 Audit log

Admin actions (key created, key revoked, collection created, collection deleted, index changed) are
appended to `DIR/audit.log`, one JSON object per line:
`{"ts": "<UTC ISO 8601>", "actor": "<key id>", "action": "key.create" | "key.revoke" |
"collection.create" | "collection.delete" | "collection.index", "target": "<key id or collection>"}`.
`GET /v1/audit?limit=n` (admin, default 100) returns the latest entries, newest first, as
`{"entries": [...]}`.

## 5.5 Secrets

No secret (the admin key, any API key, the embedding service key) may appear in a response other than
the one creating it, in an error, in the audit log, or in the server's logs (stdout or stderr), at any
log level.
