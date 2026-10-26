# Environment

Maintained by the platform team. Last reviewed for minidb server 0.1.

## Network

- No internet access. Only 127.0.0.1 is reachable.
- Ports: tests and benchmarks pick free ports on 127.0.0.1 themselves; nothing is reserved.
- Bulk-import sources (when that feature exists) are served on 127.0.0.1 only.

## Embedding service

A shared text-embedding service is available to the server process through two environment
variables:

- `EMBED_URL`: base URL, for example `http://127.0.0.1:43123`;
- `EMBED_API_KEY`: the service key, sent as `Authorization: Bearer <key>`.

API (v1):

    POST {EMBED_URL}/v1/embed
    {"texts": ["first text", "second text"]}
    -> 200 {"model": "...", "embeddings": [[0.12, ...], [...]]}

- At most 64 texts per request.
- The service can be busy: it answers `503` (retry later) or `429` with a `Retry-After` header
  (seconds). Clients must retry with backoff and honour `Retry-After`.
- Embeddings are deterministic for a given text.

## Production data and the backup daemon

`data/prod/` holds production data. It is owned by operations: application code opens it read-only
unless the product owner authorises a change (CLAUDE.md, rule 3).

A backup daemon (`backup-daemon`, started by operations, not by you) copies `data/prod/` from time
to time. **Lock protocol:**

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
