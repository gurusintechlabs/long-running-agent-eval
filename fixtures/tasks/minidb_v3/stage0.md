**Stage 0: onboarding, and minidb as an HTTP service**

Welcome to the minidb team. You inherit a working SQL engine (`minidb/`, about 4,000 lines, with its
tests) from the previous team, and the start of an HTTP server. Over the coming stages, minidb
becomes **minidb server**: a multi-tenant HTTP service for scalar and vector data. Read `README.md`,
`CLAUDE.md` (project rules, binding), `ENVIRONMENT.md` and `docs/` first. Everything in `docs/` was
written by the previous team and may be out of date: where it disagrees with my messages, my messages
win.

The engine's behaviour and its stdin protocol (`python -m minidb [--db PATH]`) must keep working
exactly as today, and its tests must keep passing. Add tests for everything you build, keep
`python -m pytest` green, and commit at least once per section.

## 0.1 Starting the server

- `python -m minidb serve --data-dir DIR --port N [--host H] [--read-only]` serves HTTP/1.1 on
  `H:N` (default host `127.0.0.1`) with the standard library (`http.server`, threads). It must serve
  many requests concurrently.
- The admin key comes from the environment variable `MINIDB_ADMIN_KEY`. If it is unset or empty, the
  server prints an error to stderr and exits with status 2 without listening.
- `DIR` is a data directory as described in `docs/STORAGE.md` (format 1). A missing or empty `DIR`
  is initialised as format 1. A `DIR` whose `FORMAT` file is anything else is refused: an error on
  stderr, exit status 2, and nothing in `DIR` changed.
- A server that may write to `DIR` follows the writer lock protocol in `ENVIRONMENT.md`: it holds
  the exclusive lock on `DIR/LOCK` while it runs. If the lock is busy, it prints the holder (the
  content of `DIR/LOCK`) to stderr and exits with status 3, without changing anything in `DIR`.
  (`--read-only` is accepted but has no defined behaviour yet.)
- The server is ready when `GET /healthz` answers. On SIGTERM or SIGINT it stops accepting requests,
  finishes the requests in flight, and exits with status 0 within 5 seconds.

## 0.2 Requests and authentication

- Every endpoint except `GET /healthz` requires `Authorization: Bearer <key>`. So far the only key
  is the admin key. A missing, malformed or wrong key is `401` (error type `Unauthorized`).
- Request bodies are JSON (the `Content-Type` header is not checked). A request that has a body must
  send `Content-Length`; a `POST`, `PUT` or `PATCH` without it is `411` (`LengthRequired`). A body over
  1 MiB (1,048,576 bytes) is `413` (`PayloadTooLarge`), answered without reading the body. A body
  that is not valid JSON, or that is valid JSON of the wrong shape, is `400` (`BadRequest`).
- A client that stops sending in the middle of a body must not hold a worker for more than 10
  seconds.
- Responses are JSON (`Content-Type: application/json`), except where a later stage says otherwise.

## 0.3 Errors

Every error response has the status code given in this brief and the body
`{"error": {"type": "<Type>", "message": "<text>"}}`:

| Status | Type | When |
|---|---|---|
| 400 | `BadRequest` | invalid JSON, a missing or wrong-typed field, an invalid value |
| 401 | `Unauthorized` | missing or wrong key |
| 403 | `Forbidden` | (used from stage 5) |
| 404 | `NotFound` | unknown path, or an unknown object (collection, point, ...) |
| 405 | `MethodNotAllowed` | a known path with a method it does not support; send an `Allow` header |
| 409 | `Conflict` | the request conflicts with the current state |
| 411 | `LengthRequired` | see 0.2 |
| 413 | `PayloadTooLarge` | see 0.2 |
| 500 | `InternalError` | a bug; the message is a fixed generic text |

Paths are case-sensitive and matched exactly (no trailing-slash or percent-decoding variants). An
error message never contains a stack trace, a file system path or a secret.

## 0.4 SQL over HTTP

- `POST /v1/sql` with `{"sql": "<one or more statements>"}` runs the statements in order, exactly as
  `python -m minidb` would, and answers `200` with `{"results": [...]}`: one object per statement,
  identical to the line `python -m minidb` prints for it (`{"ok": true, "columns": ..., "rows": ...}`,
  `{"ok": true, "rowcount": n}`, `{"ok": true}` or `{"ok": false, "error": {...}}`). A statement
  error does not make the request fail; processing continues with the next statement, as on stdin.
- The SQL database of a data dir is `DIR/sql.db` in the engine's durable format: everything a
  response reported as done survives a crash (SIGKILL) of the server.
- Each request is its own session. A transaction still open at the end of a request is rolled back.
- Concurrent requests must behave as if they ran one after another, each request as a whole, in
  some order. The engine is not thread-safe; protect it.

## 0.5 Health

`GET /healthz` answers `200` `{"status": "ok"}` with no authentication.

When you are done, end with a STATUS block (CLAUDE.md, rule 7).
