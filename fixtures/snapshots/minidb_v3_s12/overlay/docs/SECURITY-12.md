# Security review notes (stage 12)

The security team reported issues around collection names, snapshot restore, logs and the import
feature. What was checked, and what changed.

## Collection names

- Checked: every route that takes `{name}` (collections, points, search, batch, recommend,
  snapshots, text, import) and `knn('<name>', ...)` in SQL. Names must match
  `^[a-z0-9][a-z0-9_-]{0,63}$` before they reach the catalog, so a name is always one plain
  directory entry under `collections/`: no `/`, `..`, `%`-escapes (the path is matched undecoded),
  absolute paths or upper case. Snapshot names have their own pattern and the same property.
- Checked: grants list validated names only; `knn()` sees only the caller's granted collections.
- Changed: nothing (covered by tests in `tests/test_collections.py`, `tests/test_snapshots.py`).

## Snapshot restore

- Checked: an archive is parsed in memory; only the two regular members `collection.json` and
  `points.bin` are read, by name; links, devices, directories, duplicates and any other member make
  the archive invalid (400) before anything is written. No member is ever extracted to disk, so
  member names cannot reach the file system. `points.bin` is parsed with `struct`/`json`/numpy, never
  `pickle`; every field (dim, metric, index, ids, vector count and finiteness) is validated.
- Checked: the new collection is built in a temp dir and swapped in; a failed restore changes nothing.
- Changed: nothing.

## Logs

- Checked: the server logs one access line per request (method, path, status, time) and errors with
  their traceback; never headers, bodies, keys, or the embedding service key. Error answers carry no
  internals (no tracebacks or paths).
- Changed: the path in access lines is escaped (`ascii()`: control and non-ASCII characters as
  `\x..` / `\u....`), so a crafted path cannot forge or split log lines.

## Import

- Checked: the allow-list check is textual (`host:port` exactly as listed, `http` only, no userinfo)
  and happens before any connection; the connection goes to the listed entry, redirects are not
  followed, transfers are bounded (64 MiB, 60 s), and a short body fails the import.
- Changed: nothing.
