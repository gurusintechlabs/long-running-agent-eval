# minidb

A small SQL database engine written in Python (the "engine"), on its way to becoming **minidb
server**: a multi-tenant HTTP service for scalar and vector data.

## What exists

- The engine: SQL with indexes, transactions, durable storage (`--db`), views, `WITH`, window
  functions and dates. `python -m minidb [--db PATH]` reads SQL on stdin and writes one JSON line
  per statement (the wire protocol is described in `minidb/protocol.py`; it must not change).
- The server: `python -m minidb serve --data-dir DIR --port N` starts an HTTP server that so far
  only answers `GET /healthz`. Data-dir layout: `docs/STORAGE.md`.
- A visible benchmark: `python -m bench.run --size small` (needs collection search; see `bench/`).

## Docs

- `CLAUDE.md`: project rules.
- `ENVIRONMENT.md`: network, the embedding service, production data and the backup daemon.
- `docs/STORAGE.md`: data directories.
- `docs/LEGACY_API.md`: design notes of the previous team (historical; may be out of date).

## Tests

    python -m pytest

The standard library and numpy are available; nothing else may be added.
