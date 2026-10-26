# Data directories

`python -m minidb serve --data-dir DIR` keeps everything it stores under `DIR`.

## Format 1 (current)

| Path | Content |
|---|---|
| `DIR/FORMAT` | the line `minidb-data 1` |
| `DIR/sql.db`, `DIR/sql.db-wal` | the SQL database, in the format of `python -m minidb --db DIR/sql.db` (see `minidb/durable.py`) |
| `DIR/LOCK` | the writer lock (see ENVIRONMENT.md) |

An empty or missing `DIR` is initialised as format 1. A data dir with any other `FORMAT` line must
be refused with a clear error, never silently rewritten.

`data/prod/` is a format-1 data dir holding production tables (`customers`, `orders`).
