# Data directories

`python -m minidb serve --data-dir DIR` keeps everything it stores under `DIR`.

## Format 1

| Path | Content |
|---|---|
| `DIR/FORMAT` | the line `minidb-data 1` |
| `DIR/sql.db`, `DIR/sql.db-wal` | the SQL database, in the format of `python -m minidb --db DIR/sql.db` (see `minidb/durable.py`) |
| `DIR/LOCK` | the writer lock (see ENVIRONMENT.md) |

An empty or missing `DIR` is initialised as format 1. A data dir with any other `FORMAT` line must
be refused with a clear error, never silently rewritten.

`data/prod/` holds production tables (`customers`, `orders`); it was migrated to format 2 at CR-5.

## Format 2 (current, CR-5)

Format 1 plus a manifest for the backup tooling. Nothing moves: the SQL database stays in `sql.db`
(+ `sql.db-wal`), collections in `collections/<name>/`, keys in `keys.json`, the audit log in
`audit.log`, stored snapshots in `snapshots/<collection>/`.

| Path | Content |
|---|---|
| `DIR/FORMAT` | the line `minidb-data 2` |
| `DIR/MANIFEST.json` | `{"format": 2, "state": "closed" or "open", "files": {"<path>": {"size", "sha256"}}}` |

- `files` lists every file under `DIR` except `LOCK` and the manifest itself, and is exact while
  `state` is `closed`: after a clean stop (the server writes it last, under the lock) and after a
  migration. A writer marks the manifest `open` as soon as it has opened the dir.
- A writer opening a closed dir checks every file first; a missing, changed or unlisted file
  refuses the open (status 2, nothing changed). An `open` (or missing) manifest means the last writer
  crashed: the stores recover as before. `--read-only` reports a mismatch on stderr and serves.
- **Migration** (`python -m minidb migrate --data-dir DIR`, or any writer opening a format-1 dir),
  under the writer lock: write the closed manifest of the migrated dir (listing `FORMAT` with its new
  content), then replace `FORMAT`; each through a temp file, `fsync` and `rename`. A crash before the
  second rename leaves a format-1 dir (the next migration rewrites the stray manifest); after it, a
  complete format-2 dir.
