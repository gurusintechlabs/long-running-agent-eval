**Stage 1: vectors and collections**

minidb now stores vectors: as a SQL type, and as **collections** of points served over REST. Search
in this stage is exact. Everything specified so far still applies. Add tests, keep `python -m
pytest` green, commit at least once per section, and end with a STATUS block.

## 1.1 The `VECTOR` SQL type

- Column type `VECTOR(n)`, 1 <= n <= 4096. A literal is `VECTOR '[1, 2.5, -3]'` (a JSON array of
  numbers inside a string). On the wire a vector is a JSON array of floats (`[1.0, 2.5, -3.0]`).
  Storing a vector of another length in a `VECTOR(n)` column is a `TypeError`; so is a malformed
  literal or an empty array.
- Functions `l2_distance(a, b)` (Euclidean distance), `cosine_distance(a, b)` (`1 - cos(a, b)`) and
  `inner_product(a, b)`, all returning `REAL`. Different lengths, or a non-vector argument, are a
  `TypeError`; `NULL` in gives `NULL`; `cosine_distance` with a zero vector is a `RuntimeError`.
- Vectors support `=`, `<>`, `IS [NOT] NULL` and the functions above. Ordering comparisons and
  arithmetic on vectors are a `TypeError`. `ORDER BY l2_distance(v, VECTOR '[...]') LIMIT k` must
  work and be exact.
- Vectors survive `--db` durability and `sql.db` like every other value.

## 1.2 Collections

A collection holds points `{"id", "vector", "payload"}` of one dimension and one metric.

- `PUT /v1/collections/{name}` with `{"dim": n, "metric": "l2" | "cosine" | "dot"}` (metric
  optional, default `l2`) creates it: `201` with the collection object
  `{"name", "dim", "metric", "points": 0}`. An existing name is `409`.
- Names match `^[a-z0-9][a-z0-9_-]{0,63}$`; anything else is `400`. `dim` is 1 to 4096.
- `GET /v1/collections` answers `{"collections": [...]}` sorted by name; `GET /v1/collections/{name}`
  answers the collection object (with the current point count); `DELETE /v1/collections/{name}`
  deletes it and its points (`200` `{"deleted": true}`). Unknown names are `404`.
- Collections and their points live in the data dir and survive a restart and a crash, like SQL data.

## 1.3 Points

- `PUT /v1/collections/{name}/points` with `{"points": [{"id": 7, "vector": [...], "payload": {...}}]}`
  inserts or replaces points: `200` `{"upserted": n}`. Ids are non-negative integers below 2^63.
  `payload` is a JSON object or `null`/absent (stored as `null`), at most 65,536 bytes as JSON. At most
  1,000 points per request. A request is validated as a whole: if any point is invalid (wrong
  dimension, bad id, non-finite number, oversized payload, a duplicate id within the request, a zero
  vector in a `cosine` collection), it is `400` and nothing is written.
- `GET /v1/collections/{name}/points/{id}` answers the point; an unknown id is `404`.
- `POST /v1/collections/{name}/points/delete` with `{"ids": [...]}` deletes them (unknown ids are
  ignored): `200` `{"deleted": <number actually deleted>}`.

## 1.4 Search

`POST /v1/collections/{name}/search` with
`{"vector": [...], "k": 10, "filter": {...}, "with_payload": false, "with_vector": false}` answers
`{"results": [{"id": 7, "score": 0.25}, ...]}` (plus `payload` / `vector` per result when asked).

- `k` is 1 to 1,000 (default 10). The result has `min(k, matching points)` entries.
- `score` is a distance for every metric: `l2` the Euclidean distance; `cosine` `1 - cos`; `dot` the
  negated inner product. Results are ordered by score ascending, ties by id ascending. Search is exact
  in this stage.
- **Filters** select points by payload:
  - a filter is an object with any of `must`, `should`, `must_not`, each a list of conditions. `must`:
    all hold; `should`: at least one holds (if the list is non-empty); `must_not`: none holds. `{}` and
    an absent filter match every point;
  - a condition is a nested filter, or
    `{"key": "a.b", "match": {"value": v}}` (equal; numbers compare by value, so `1` matches `1.0`;
    `true` does not match `1`), `{"key": ..., "match": {"any": [v, ...]}}`,
    `{"key": ..., "range": {"gt" | "gte" | "lt" | "lte": number, ...}}` (numbers only), or
    `{"has_id": [ids]}`;
  - `key` is a dotted path into the payload. If the value at the path is an array, the condition
    holds when it holds for any element. A missing key, or `null`, satisfies no `match` or `range`;
  - filters nest at most 8 levels; deeper, or malformed, is `400`.

## 1.5 Notes

`docs/LEGACY_API.md` is the previous team's design note. Check what it says against this brief and
the systems you talk to before relying on it.
