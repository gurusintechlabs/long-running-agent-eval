**Stage 3: change requests CR-1, CR-2, CR-3**

Three changes requested by our first clients. Each one **replaces** what was specified before; tests
that assert the old behaviour must be updated. Everything else still applies. Keep `python -m pytest`
green, commit at least once per change request, and end with a STATUS block.

## CR-1: score direction per metric

Scores now follow each metric's natural direction:

- `l2`: Euclidean distance, ascending (unchanged);
- `cosine`: cosine **similarity** `cos(a, b)`, descending;
- `dot`: the inner product, descending.

Ties are still broken by id ascending. This applies to every search response (including `explain`
and every later endpoint that returns scored points). The SQL functions do not change.

## CR-2: UUID point ids

A point id is now either a non-negative integer below 2^63 or a UUID string. UUIDs are accepted in
any case, with or without hyphens, and always returned in canonical form (lowercase, hyphenated,
`8-4-4-4-12`). `7` and `"7"` are different: a string that is not a UUID is `400`. In every ordering by
id, integers come before UUIDs, and UUIDs are ordered by their canonical string. The point path is
`/v1/collections/{name}/points/{id}` with either form.

## CR-3: problem details for errors

Every error response is now an RFC 9457 (formerly 7807) problem document with
`Content-Type: application/problem+json`:

    {"type": "https://minidb.dev/problems/<slug>", "title": "<short title>", "status": <code>,
     "detail": "<explanation>", "instance": "<request path>"}

Slugs, by status: 400 `bad-request`, 401 `unauthorized`, 403 `forbidden`, 404 `not-found`,
405 `method-not-allowed`, 409 `conflict`, 411 `length-required`, 413 `payload-too-large`,
429 `too-many-requests`, 500 `internal-error`, 502 `bad-gateway`, 503 `unavailable`. The old
`{"error": {...}}` body is gone. `detail` never contains a stack trace, a file system path, a SQL
error from inside the server, or a secret.

`POST /v1/sql` is not affected: statement errors are still reported inside `results` in the engine's
format.
