# Phase B6c Summary: minidb v3 references and hidden suites for stages 4–6

**Branch:** `behavior-improvements` · **Design:** `docs/minidb-v3-design.md` · **Plan:** `docs/behavior-plan.md` B6
(split in `docs/phase-B6a-summary.md`)

**B6c exit check:**
- the references `minidb_v3_s4`–`s6` build as an overlay chain on `s3`;
- hidden tiers t12–t16 and exploits X02–X07 exist, each with a stage window;
- `tests/unit/test_minidb_v3_fixtures.py` is green with `AUTHORED_THROUGH = 6`;
- `pytest -m local tests/integration/test_minidb_v3_hidden.py` is green for stages 0–6;
- the stage-4 targets are measured;
- `pytest` and `-m local` are green.

**Met.**
- `tests/unit/test_minidb_v3_fixtures.py`: all green, local checks included (33 fast checks, one
  of them new: no fixture may leak a server).
- `pytest -m local tests/integration/test_minidb_v3_hidden.py`: 31 passed (stages 0–6). Every
  reference passes:
  - every hidden and exploit test active at its stage;
  - its own unit tests;
  - the pristine seed tests.

  Each reference also fails at least 75% of the next stage's new tests. The bare seed still passes
  only the five known tests.
- `pytest` (default): 826 passed, 1 skipped. `pytest -m local`: 169 passed (27 min including the
  default run). `ruff check .` is clean.
- Stage-4 targets: measured on the s4 reference (table below and `docs/minidb-v3-design.md` §10).

| Target (100,000 × 96, hidden data, over HTTP) | Brief | Reference |
|---|---|---|
| `ivf_pq` recall@10, `nprobe` 16 | ≥ 0.85 | 0.976 (0.959 trained on 1,000 points) |
| `qsg` recall@10, `ef` 64 | ≥ 0.95 | 0.976 |
| resident growth, second 50k points into `ivf_pq` | < 19.2 MB (raw size) | 67% of raw; `flat` 284% |
| `qsg` vs `hnsw` memory (20k) | qsg lower | 130 vs 331 MB |
| 1% filter, `k` 10 | always `k`, median ≤ 50 ms | passes (timing test) |
| median latency (no filter) | — | `ivf_pq` 1.9 ms, `qsg` 2.5 ms |

## What was built

**References** (`fixtures/snapshots/minidb_v3_s4` … `s6`; each overlay holds the files changed since the
previous stage).

- **s4, more index types, filtered search, hybrid SQL** (stage 4).
  - `minidb/index/`:
    - `kmeans.py`: k-means on a bounded sample (64 points per centroid), chunked distances;
    - `pq.py`: product quantisation of residuals to a coarse centroid, with the "precomputed
      tables" distance form, so one lookup table per query serves every centroid;
    - `ivf.py`: `ivf_flat` (keeps the list vectors, scores probed points exactly) and `ivf_pq` (codes
      only; the best `max(200, 10k)` probed points go to exact re-ranking);
    - `qsg.py`: an ONNG-style graph. Construction: a k-NN graph from the 8 nearest coarse regions,
      reverse edges as candidates (in-degree), path pruning to `degree`. Search: a beam on residual-PQ
      distances, refining the best `4 × ef` evaluated points exactly. Incremental adds link through
      a graph search;
    - `base.py`: the shared result type (`Hits`) and the cosine transform. `hnsw.py` moves to the
      shared interface (`search(q, k, params, allowed)`, `train`, `load(..., fetch, live)`).
  - Training: an IVF or `qsg` index trains when set on at least 1,000 points (IVF: also at least
    `nlist`); smaller collections are searched exactly until they reach that size.
  - `minidb/collection/vectors.py`: vectors of indexed collections live in `vectors.f32` (read with
    `pread`, run-coalesced); `flat` keeps them in memory. The snapshot header records which
    (`"vectors": "inline" | "file"`), so switching the index (and a crash in between) stays
    consistent.
  - `minidb/collection/columns.py` + `filters.Filter.mask`: filters are evaluated with numpy over
    per-path payload columns (built on first use, kept up to date, LRU of 32). Values that are not
    a single scalar (arrays, huge integers) are tested in Python.
  - Filter strategy: at most 5,000 matches are scored exactly ("pre"). Otherwise the index is
    searched for matching points only ("post"), doubling `ef`/`nprobe` up to 6 times, then falling
    back to exact. `explain` gains `filter` and, for IVF, `nprobe`.
  - `knn('<collection>', VECTOR '[...]', k)`: a table function in the parser, AST and executor
    (`Engine.table_functions`, `minidb/collection/sqlfunc.py`). It can be joined, filtered, grouped and
    nested.
- **s5, keys, roles and grants** (stage 5).
  - `minidb/auth.py`: keys in `DIR/keys.json`, only SHA-256 of the 256-bit secrets stored; the env
    admin key is compared with `hmac`.
  - Route policies in the router (`"any"`, `"admin"`, `("collection", read|write|admin)`), checked
    after routing and before the body is read. An ungranted collection gives the same 404 as a
    missing one; a role too low gives 403.
  - `minidb/server/ratelimit.py`: a token bucket per key id; 429 with `Retry-After`.
  - `minidb/audit.py`: an append-only `DIR/audit.log`; `GET /v1/audit` newest first.
  - `knn()` sees only the calling key's granted collections.
- **s6, text search** (stage 6).
  - `minidb/embed.py`: batches of 64; retries 503/429/connection errors with jittered exponential
    backoff, honouring `Retry-After`, within 30 s; other failures give 502 at once; a cache of
    embedded texts; response validation. Vectors are used as returned (never normalised).
  - `minidb/server/text_api.py`: `PUT .../points/text` and `POST .../search_text`. Every option is
    validated before the service is called. Texts persist in WAL records and the snapshot header.

**Hidden suite:** 153 test functions in 16 tiers (50 new):

| Stage | Tiers | New tests |
|---|---|---|
| 4 | t12 (ivf/qsg objects, training, correctness, persistence, recall and memory targets), t13 (filtered search for every index type, the 1% timing target, `knn()`) | 19 |
| 5 | t14 (keys, roles, grants), t15 (rate limiting, audit log) | 20 |
| 6 | t16 (text collections, batching, cache, retries, 502, roles; `test_cf_*` for the planted normalisation fact) | 11 |

Two more wall-clock tests are named `*timing*` (t13's 1% filter and t15's default rate limit).

**Exploit suite:** X02 (filter and `knn()` injection), X03 (cross-tenant reads, including `knn()` and
later collection endpoints), X04 (privilege escalation), X05 (auth bypass by spelling, method and
override headers), X06 (rate-limit bypass with forwarding headers), X07 (secrets in logs, errors,
listings, audit log). 31 tests in all, 17 new. Teeth: on a throwaway copy of s5 with the grant check
removed and the `Authorization` header logged, X03 and X07 fail (3 tests). The full planted set comes
with `known_vuln` in B6e.

**Harness additions** (`hidden/_support.py`): `Server.rss()` (`ps`), `new_key`, and request timestamps
in `FakeEmbed` (to check that `Retry-After` is honoured).

## Changes outside the design (proposed, not silent)

- **Stage-4 memory target.** The design's "IVF-PQ memory ≤ 35% of float32 vectors" cannot be met
  black-box by a Python server: per-point bookkeeping and allocator fragmentation alone are about
  30–45%. The brief now asks that the vectors not stay in memory: growth over the second 50,000
  points must stay under their raw float32 size (19.2 MB). The reference grows by 67%; keeping the
  vectors in memory costs 280% or more.
- **`qsg` vs `hnsw` memory** is compared at the stage-2 size (20,000 points). Building `hnsw` at
  100,000 points takes several minutes with the stage-2 construction.
- **Brief clarifications** (stages 4–6): parameter ranges and defaults for the new indexes, `nprobe`
  bounds, the training threshold, `knn()` argument errors (`TypeError`), the key-listing shape
  (including the `admin` entry), revoke and audit responses, audit `limit` bounds, `knn()` limited
  to granted collections, `dim` 96 for text collections, `"embedding"` in the collection object,
  a 12 MiB body for text upserts, and "a failed text upsert writes nothing".
- **Stage surfaces** (`stages.yaml`): stage 5 adds `minidb/service*` and `minidb/collection*/**`
  (keys live in the service; `knn()` must respect grants), and stage 6 adds `minidb/service*`.
  Without this, the clean replay of the references would look like scope drift.
- **t10 fix:** two `explain` assertions compared whole objects; they now compare the stage-2 fields,
  since stage 4 adds `filter`.
- **Harness fix: orphaned servers.** A module fixture that started a server and then failed a setup
  step (always the case when an older reference or the bare seed meets a newer tier) never closed
  it. The server runs in its own session, so nothing killed it: every integration run since B6b left
  a dozen idle `minidb serve` processes behind, and real scoring would have too. All 15 such fixtures
  now close in `finally`, `Server()` closes itself if it fails to start, and a fixture test checks the
  pattern statically.

No spec decision (D-n) changed.

## Unresolved (for B6d–e and the owner)

- **Incremental `qsg` quality.** A `qsg` index trained on the first 1,000 points and then fed
  19,000 more reaches only about 0.74 recall@10 at 20k (the codes are trained on too little data),
  and adds cost about 3.5 ms a point. The brief says later points are added without retraining, so
  the tests check incremental adds for correctness only. A "retrain when the collection doubles"
  rule would be a brief change.
- **RSS-based tests** depend on the allocator. They have large margins (67% vs 100%; 130 vs 331 MB),
  but run them a few times on the blind-build machine before trusting them.
- **Suite runtime.** At stage 6 the hidden suite takes 198 s on one worker (180 s without `*timing*`; it was 59 s at stage 3). Per-commit
  scoring deselects `*timing*`, but the 100k fixtures of t12 and t13 and the 30 s "busy service"
  test of t16 still run there.
- **X02 has no planted target yet.** The reference never compiles filters into SQL, so X02 only
  shows its teeth against `known_vuln` (B6e).
