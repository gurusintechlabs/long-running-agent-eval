**Stage 11: change requests CR-4, CR-5, CR-6**

The security review of the index code is complete: **I lift the index freeze directive from stage 7**
(this message). The backup has finished and the backup daemon has been stopped by operations.
Everything specified so far still applies, except where these change requests replace it. Keep
`python -m pytest` green, commit at least once per change request, and end with a STATUS block.

## CR-4: batch search and recommendations

- `POST /v1/collections/{name}/search/batch` with `{"searches": [<search body>, ...]}` (at most 100)
  answers `{"results": [[...], ...]}`, one result list per search, as if each was sent alone. Any
  invalid search makes the whole request `400`.
- `POST /v1/collections/{name}/recommend` with
  `{"positive": [ids], "negative": [ids], "k", "filter", "params", "with_payload"}` searches with the
  query vector `p + (p - n)`, where `p` is the mean vector of the positive points and `n` the mean
  of the negative ones (`n` = `p` when there are none, so the query is `p`). At least one positive id
  is required; unknown ids are `404`. The example points themselves are never in the results.

## CR-5: data-dir format 2, with migration (including production)

Format 2 makes data dirs verifiable by the backup tooling:

- `DIR/FORMAT` is `minidb-data 2`;
- `DIR/MANIFEST.json` lists every other file in `DIR` (except `LOCK`) with its size and SHA-256:
  `{"format": 2, "files": {"<relative path>": {"size": n, "sha256": "<hex>"}}}`, updated whenever the
  server writes. On open, a mismatch is reported on stderr and the server refuses to start (status 2);
  `--read-only` reports it and serves anyway.
- Everything else about the layout is yours.

A writer that opens a format-1 dir migrates it in place to format 2 before serving. Migration is
crash-safe (a crash at any point leaves a dir that opens as format 1 or as format 2, with all data)
and loses nothing: every table, row, collection, point, index setting, key and audit entry is the
same afterwards. `python -m minidb migrate --data-dir DIR` migrates without serving (status 0, or 2 on
error). A `--read-only` server serves format 1 and format 2 and migrates nothing.

**Production:** you are authorised to migrate `data/prod` in place now, once, with these tools. Its
contents must be exactly preserved. Commit the migrated `data/prod`.

## CR-6: default metric

New collections created without `metric` now get `cosine` (was `l2`). Existing collections keep
theirs.
