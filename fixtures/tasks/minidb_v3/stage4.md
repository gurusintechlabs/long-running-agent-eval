**Stage 4: more index types, filtered search, memory**

Clients with very large collections need indexes that trade a little recall for much less memory,
like Vearch's IVF family, and a quantised graph in the style of QSG-NGT (an ONNG-optimised graph
traversed on product-quantised codes, with exact refinement). Filtered search must also become
dependable. Everything specified so far still applies. Add tests, keep `python -m pytest` green,
commit at least once per section, and end with a STATUS block (report the targets in `targets`).

## 4.1 Index types

New index objects (validated as in 2.1; invalid ones are `400`):

- `{"type": "ivf_flat", "nlist": 256}`: points are assigned to the nearest of `nlist` centroids
  (k-means over the collection); search scans the `nprobe` nearest lists exactly. `nlist` 1 to
  4,096 (default 256).
- `{"type": "ivf_pq", "nlist": 256, "m": 16, "nbits": 8}`: as `ivf_flat`, but vectors are stored as
  product-quantisation codes (`m` sub-quantisers of `nbits` bits; `m` 1 to 4,096, default 16, and
  `dim` must be divisible by `m`; `nbits` 4 to 8, default 8); candidates are re-ranked exactly.
- `{"type": "qsg", "degree": 32, "m": 16}`: a graph whose edges are optimised ONNG-style (bounded
  out-degree `degree`, 8 to 128, default 32; in-degree adjustment; redundant-path pruning), traversed
  on PQ codes (`m` as for `ivf_pq`, 8 bits), with exact refinement.

Missing parameters take their defaults (the collection object shows them all); unknown parameters
and values out of range are `400`.

Search params: `nprobe` (IVF, 1 to `nlist`, default 16, or `nlist` if smaller; `400` outside that
range) and `ef` (graphs, as in 2.2). An IVF or `qsg` index is trained when it is set
(`PUT .../index`) on the current points; points upserted later are added without retraining.
Setting an index on a collection with fewer than 1,000 points (or, for IVF, fewer than `nlist`) is
allowed: it is trained as soon as the collection holds that many, and searches are exact until then.
`explain` reports the index type (with `"exact": true` while untrained) and, for IVF, `nprobe`.
Search results keep every rule of 1.4, 2.2 and CR-1 (exact scores, no deleted or unmatched points).

## 4.2 Filtered search returns k results

For every index type: when at least `k` points match the filter, a search returns exactly `k`
results. Choose the strategy by selectivity (filter first and search the matching subset exactly, or
search the index and filter, widening as needed). `explain` adds `"filter": "none" | "pre" | "post"`.
Filtered results are measured against an exact search of the matching points: at the default search
parameters (`ef`, `nprobe`), every index type keeps a recall@k of at least 0.85, and at least 0.9 for
`k` = 10 when the filter matches half of the points or more (`flat` is exact).

## 4.3 Hybrid queries

A table function makes collections usable from SQL:
`SELECT id, score FROM knn('<collection>', VECTOR '[...]', k)` returns the same rows as the search
endpoint (columns `id`, `score`, `payload` as TEXT JSON, `NULL` for none), in the same order, using
the collection's index with its default parameters. It can be joined, filtered and ordered like any
table. An unknown collection is a `NameError`; other bad arguments (not a TEXT name, not a VECTOR of
the collection's dimension, `k` not an integer from 1 to 1,000) are a `TypeError`.

## 4.4 Targets (measured by the acceptance tests on their own data)

Data: 100,000 points of dimension 96, metric `l2`.

- `ivf_pq` with defaults, `nprobe` 16: recall@10 at least 0.85;
- memory: while the 100,000 points are loaded (in requests of 1,000, without payloads) into a
  collection created with an `ivf_pq` index, the server's resident memory grows by less than the raw
  float32 size of the vectors loaded: the vectors themselves must not stay in memory (measured over
  the second 50,000 points: less than 19.2 MB);
- `qsg` with defaults, set on the loaded collection: recall@10 at least 0.95 at `ef` 64;
- `qsg` uses less resident memory than `hnsw` for the same data (the 20,000 points of 2.3, with the
  index set on the loaded collection);
- filtered search with a filter matching 1% of the points: always `k` results, median at most 50 ms.
