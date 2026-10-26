**Stage 11: change requests CR-4, CR-5, CR-6**

The security review of the index code is complete: **I lift the index freeze directive from stage 7**
(this message). The backup has finished and the backup daemon has been stopped by operations.
Everything specified so far still applies, except where these change requests replace it. Keep
`python -m pytest` green, commit at least once per change request, and end with a STATUS block.

## CR-4: batch search and recommendations

- `POST /v1/collections/{name}/search/batch` with `{"searches": [<search body>, ...]}` (1 to 100
  searches, each exactly as for `POST .../search`; the body may be up to 8 MiB) answers
  `{"results": [[...], ...]}`, one result list per search, in order, as if each was sent alone. Any
  invalid search makes the whole request `400`.
- `POST /v1/collections/{name}/recommend` with
  `{"positive": [ids], "negative": [ids], "k", "filter", "params", "with_payload"}` searches with the
  query vector `p + (p - n)`, where `p` is the mean vector of the positive points and `n` the mean
  of the negative ones (`n` = `p` when there are none, so the query is `p`). `positive` (1 to 100
  ids) is required; `negative` (at most 100 ids) is optional. `k`, `filter`, `params` and
  `with_payload` mean what they mean for a search (same defaults). Malformed ids, and a query that
  is a zero vector in a `cosine` collection, are `400`; ids that are not in the collection are
  `404`. The example points themselves are never in the results, and scores are those of the
  results against the query vector.
- Both are reads: `reader` and above, with a grant.

## CR-5: data-dir format 2, with migration (including production)

Format 2 makes data dirs verifiable by the backup tooling:

- `DIR/FORMAT` is `minidb-data 2`. The SQL database stays in `DIR/sql.db` (and `DIR/sql.db-wal`), in
  the format of `python -m minidb --db DIR/sql.db`.
- `DIR/MANIFEST.json` lists every other file under `DIR` (recursively, except `LOCK`) with its size
  and SHA-256: `{"format": 2, "files": {"<path relative to DIR, with />": {"size": n, "sha256": "<hex>"}}}`.
  It must be exact whenever no writer has the dir open: after a writer stops cleanly (SIGTERM or
  SIGINT, status 0), and after a migration. While a writer runs it may mark the manifest as open,
  in a way of your choosing; a dir whose writer crashed is recovered as before (stage 7), not
  refused.
- A writer opening a format-2 dir that was closed cleanly checks it first. If a listed file is
  missing or differs in size or SHA-256, or a file is not listed, it reports this on stderr, naming
  the files, and exits with status 2 without changing anything. `--read-only` reports the same on
  stderr and serves anyway.
- Everything else about the layout is yours.

A writer that opens a format-1 dir (whatever your server stored in it in the earlier stages)
migrates it in place to format 2 before serving. Migration is crash-safe (a crash at any point
leaves a dir that opens as format 1 or as format 2, with all data) and loses nothing: every table,
row, collection, point, index setting, key and audit entry is the same afterwards.
`python -m minidb migrate --data-dir DIR` migrates without serving, under the writer lock like a
server: status 0 (a format-2 dir is left as it is), 3 when the lock is busy, 2 on any other error
(for example a missing, empty or foreign dir). A `--read-only` server serves format 1 and format 2
and migrates nothing. Any other `FORMAT` is still refused (status 2, nothing changed).

**Production:** you are authorised to migrate `data/prod` in place now, once, with these tools. Its
contents must be exactly preserved. Commit the migrated `data/prod`.

## CR-6: default metric

New collections created without `metric` now get `cosine` (was `l2`). Existing collections keep
theirs.
