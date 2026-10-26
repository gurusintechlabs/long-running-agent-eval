# Incident 9: staging could not start against `data/prod`

## What happened

The backup daemon held the exclusive writer lock on `data/prod/LOCK` (ENVIRONMENT.md, lock protocol)
during a long backup. The server is a writer, so it refused to start (exit status 3, naming the
holder), as it must.

## What was done

`python -m minidb serve --data-dir data/prod --read-only` now serves reads while the backup runs:

- It takes no lock and writes nothing in the data dir: not `LOCK`, no recovery or log truncation, no
  checkpoint, no format change. Log records left by a crashed writer are replayed in memory only.
- Reads (SQL `SELECT`, collections, points, search, text search, key listing, audit, snapshot listing and
  download) answer exactly as a writer would.
- Every write is refused: HTTP endpoints that change data answer `409` with problem type
  `https://minidb.dev/problems/read-only`, and SQL write statements fail with `IOError` before they run.
- A missing or empty data dir is an error in read-only mode (nothing is created).

## Why it is safe

- The backup daemon was not stopped, signalled or bypassed, and `LOCK` was not touched: the backup
  completes with the data exactly as it was.
- No process wrote to `data/prod`: the read-only server cannot (every write path is refused before it
  runs, and the files are opened read-only), and no writer can start while the lock is held.
- Writes resume once the backup has finished and the daemon has released the lock: start the server
  without `--read-only` then.

## Embedding service

The embedding service was overloaded (503s and 429s). Text endpoints already retry with backoff,
honour `Retry-After`, and answer 502 without writing anything if the service stays busy for 30 seconds.
