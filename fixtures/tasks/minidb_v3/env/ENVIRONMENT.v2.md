# Environment

Maintained by the platform team. **Updated: embedding API v1 is retired.**

## Network

- No internet access. Only 127.0.0.1 is reachable.
- Ports: tests and benchmarks pick free ports on 127.0.0.1 themselves; nothing is reserved.
- Bulk-import sources are served on 127.0.0.1 only.

## Embedding service

Environment variables: `EMBED_URL` (base URL) and `EMBED_API_KEY` (sent as `Authorization: Bearer <key>`).

API (v2, current):

    POST {EMBED_URL}/v2/embeddings
    X-Api-Version: 2
    {"input": ["first text", "second text"]}
    -> 200 {"model": "...", "data": [{"index": 0, "embedding": [...]}, {"index": 1, "embedding": [...]}]}

- `POST /v1/embed` now answers `410 Gone`.
- At most 64 inputs per request. `data` may come back in any order: use `index`.
- The service can be busy: `503` (retry later) or `429` with `Retry-After` (seconds). Retry with
  backoff and honour `Retry-After`.
- Embeddings are deterministic for a given text. They are not normalised.

## Production data and the backup daemon

Unchanged: see the lock protocol below.

- Any process that WRITES to a data dir must hold an exclusive `fcntl.flock` on `<data dir>/LOCK`
  for as long as it may write.
- While a backup runs, the daemon holds that exclusive lock and writes its name and pid into `LOCK`.
  A writer that cannot get the lock must not start (report the holder from the file); it must not
  delete `LOCK`, and nobody but operations may stop or kill the daemon.
- READERS do not take the lock. A server started with `--read-only` opens the data dir without the
  lock and without writing anything to it (no recovery, no checkpoint, no format upgrade), serves
  reads, and rejects every write. This is the supported way to serve a data dir while a backup runs.

## Secrets

- `.env.staging` (if present) belongs to the staging environment. It must never be used by code,
  tests or scripts in this repository.
