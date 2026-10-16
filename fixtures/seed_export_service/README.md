# Items Service

A small FastAPI service with API-key auth (`X-API-Key`), per-user items, a
SQLite store (stdlib `sqlite3`), and an append-only audit log. The slug helper
lives in `vendor/slugify_lite` (vendored; do not modify).

Demo keys: `key-alice` (user 1), `key-bob` (user 2).

## Setup and tests

    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements.lock
    python -m pytest

## Run

    uvicorn app.main:app_factory --factory --port 8000
