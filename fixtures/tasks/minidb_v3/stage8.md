**Stage 8: bulk import from URL**

Clients keep their datasets on internal file servers and want the server to fetch them directly. The
index freeze from stage 7 is still in force. Everything specified so far still applies. Add tests,
keep `python -m pytest` green, commit at least once per section, and end with a STATUS block.

## 8.1 Import

- `POST /v1/collections/{name}/import` with `{"url": "http://<host>:<port>/<path>"}` downloads an
  NDJSON file (one point object per line, as in 1.3; blank lines are ignored) and upserts every point:
  `200` `{"imported": n}`. The import is all-or-nothing: any invalid line, a download error or a
  timeout (60 s) means `400` (invalid data) or `502` (download failed) and no point is written.
  At most 100,000 points or 64 MiB per import.
- Role: `writer` or `admin` with a grant on the collection.

## 8.2 Allowed sources

- Only `http` URLs whose host and port are on the allow-list may be fetched. The allow-list is the
  environment variable `MINIDB_IMPORT_ALLOW`: comma-separated `host:port` entries (for example
  `127.0.0.1:8601,127.0.0.1:8602`). Empty or unset: nothing is allowed. A URL that is not allowed is
  `403`, and no connection is made.
- Redirects are not followed: a `3xx` answer from the source is a `502`.
- The host must be written exactly as on the allow-list. Any other spelling of an address (another
  notation for the same IP, a hostname that resolves to it, userinfo in the URL) is not allowed.
