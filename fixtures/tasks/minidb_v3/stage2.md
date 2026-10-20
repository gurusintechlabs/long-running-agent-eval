**Stage 2: a graph index, and performance**

Our first client loads tens of thousands of 96-dimensional vectors and needs fast search. Exact
search does not scale, so this stage adds a graph index in the style of GLASS: an HNSW graph traversed
on scalar-quantised (int8) vectors, with the candidates re-ranked by exact distance. There is now a
shared benchmark in `bench/` (`python -m bench.run --size small`); it is a convenience, not the
acceptance test. Everything specified so far still applies. Add tests, keep `python -m pytest`
green, commit at least once per section, and end with a STATUS block (report the targets of 2.3 in
`targets`).

## 2.1 Index configuration

- A collection has an index: `{"type": "flat"}` (exact search, the default) or
  `{"type": "hnsw", "m": 16, "ef_construction": 200}` (`m` 4 to 64, default 16; `ef_construction`
  16 to 1,000, default 200). It is given at creation (`"index": {...}` in the body of
  `PUT /v1/collections/{name}`) or replaced later with `PUT /v1/collections/{name}/index` and the
  index object (`200`, the collection object). The collection object now includes `"index"`.
- The index is maintained through every upsert and delete, and it survives a restart without a full
  rebuild of the graph.
- Invalid index objects are `400`.

## 2.2 Searching an index

- Search accepts `"params": {"ef": n}` (default 64; 1 to 2,000; an `ef` below `k` is raised to `k`).
  `flat` ignores it.
- An `hnsw` search is approximate: it may miss true neighbours. It never returns a point that does
  not match the filter, never returns a deleted point, and returns scores computed exactly (the
  same numbers an exact search would give for those points). With a filter, it may return fewer than
  `k` results in this stage.
- `"explain": true` adds `"explain": {"index": "flat" | "hnsw", "exact": bool, "ef": n | null,
  "candidates": n}` to the response (`candidates`: how many points were scored exactly).

## 2.3 Targets (on this machine, measured by the acceptance tests on their own data)

Data: 20,000 points of dimension 96 (clustered, like `bench/`), metric `l2`, `hnsw` with defaults.

- recall@10 at `ef` 64: at least 0.95 (the share of the true 10 nearest neighbours found);
- search latency, one client, `ef` 64, no filter: median at most 15 ms (measured over HTTP);
- upserting the 20,000 points in requests of 1,000: at most 60 s in total.
