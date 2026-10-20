**Stage 4: more index types, filtered search, memory**

Clients with very large collections need indexes that trade a little recall for much less memory,
like Vearch's IVF family, and a quantised graph in the style of QSG-NGT (an ONNG-optimised graph
traversed on product-quantised codes, with exact refinement). Filtered search must also become
dependable. Everything specified so far still applies. Add tests, keep `python -m pytest` green,
commit at least once per section, and end with a STATUS block (report the targets in `targets`).

## 4.1 Index types

New index objects (validated as in 2.1; invalid ones are `400`):

- `{"type": "ivf_flat", "nlist": 256}`: points are assigned to the nearest of `nlist` centroids
  (k-means over the collection); search scans the `nprobe` nearest lists exactly.
- `{"type": "ivf_pq", "nlist": 256, "m": 16, "nbits": 8}`: as `ivf_flat`, but vectors are stored as
  product-quantisation codes (`m` sub-quantisers of `nbits` bits; `dim` must be divisible by `m`);
  candidates are re-ranked exactly.
- `{"type": "qsg", "degree": 32, "m": 16}`: a graph whose edges are optimised ONNG-style (bounded
  out-degree `degree`, in-degree adjustment, redundant-path pruning), traversed on PQ codes, with exact
  refinement.

Search params: `nprobe` (IVF, 1 to `nlist`, default 16) and `ef` (graphs). An IVF or `qsg` index is
trained when it is set (`PUT .../index`) on the current points; points upserted later are added
without retraining. Setting an index on an empty collection is allowed: it is trained when the
collection first holds at least 1,000 points, and searches are exact until then. `explain` reports
the index type and, for IVF, `nprobe`.

## 4.2 Filtered search returns k results

For every index type: when at least `k` points match the filter, a search returns exactly `k`
results. Choose the strategy by selectivity (filter first and search the matching subset exactly, or
search the index and filter, widening as needed). `explain` adds `"filter": "none" | "pre" | "post"`.

## 4.3 Hybrid queries

A table function makes collections usable from SQL:
`SELECT id, score FROM knn('<collection>', VECTOR '[...]', k)` returns the same rows as the search
endpoint (columns `id`, `score`, `payload` as TEXT JSON), in the same order, using the collection's
index. It can be joined, filtered and ordered like any table. An unknown collection is a `NameError`.

## 4.4 Targets (measured by the acceptance tests on their own data)

Data: 100,000 points of dimension 96, metric `l2`.

- `ivf_pq` with defaults, `nprobe` 16: recall@10 at least 0.85;
- memory: the server's resident memory grows by at most 35% of the raw float32 size of the vectors
  (here 38.4 MB) while the 100,000 points are loaded into an `ivf_pq` collection;
- `qsg` with defaults: recall@10 at least 0.95 at `ef` 64, using less resident memory than `hnsw` for
  the same data;
- filtered search with a filter matching 1% of the points: always `k` results, median at most 50 ms.
