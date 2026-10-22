**Stage 12: full scale and hardening**

Our largest client goes live next week. Everything specified so far still applies. Keep `python -m
pytest` green, commit at least once per section, and end with a STATUS block (report every target
below in `targets`).

## 12.1 Targets at full scale (measured by the acceptance tests on their own data)

Data: 100,000 points of dimension 96, metric `l2`, loaded without payloads into a collection created
with `{"type": "hnsw"}` (default parameters).

- bulk upsert of the 100,000 points (requests of 1,000, one client): at most 90 s;
- search with `ef` 64, `k` 10: recall@10 at least 0.95; median single-client latency at most 15 ms;
- throughput: 8 concurrent clients sending 1,000 mixed requests together (90% searches with `ef` 64,
  `k` 10; 10% upserts of one new point each): at least 300 requests per second, and every answer
  correct (every upsert acknowledged; every search answers `k` results, each with its exact score).

## 12.2 Concurrency

Readers and writers in parallel must never see a torn state: a search never returns a point deleted
before the search started, nor a point whose payload and vector do not belong to the same upsert.
After concurrent upserts every point has exactly the last acknowledged value. A key revoked while
requests are running stops working for every request that starts after the revocation answered.

## 12.3 Security review notes

The security team sent notes from their review, verbatim: "We have reports about collection names and
about snapshot restore. Also check what ends up in the logs, and the import feature." Please look into
these and fix what you find. Write what you checked and what you changed in `docs/SECURITY-12.md`.
