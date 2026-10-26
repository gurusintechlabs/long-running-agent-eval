# Phase B6b Summary: minidb v3 references and hidden suites for stages 0–3

**Branch:** `behavior-improvements` · **Design:** `docs/minidb-v3-design.md` · **Plan:** `docs/behavior-plan.md` B6
(split in `docs/phase-B6a-summary.md`)

**B6b exit check:**
- the references `minidb_v3_s0`–`s3` build as an overlay chain;
- hidden tiers t01–t11 and exploits X01 and X08–X10 exist, each with a stage window;
- `tests/unit/test_minidb_v3_fixtures.py` is green;
- `pytest -m local tests/integration/test_minidb_v3_hidden.py` is green for stages 0–3;
- the stage-2 targets are measured;
- `pytest` and `-m local` are green.

**Met** (numbers below).

## What was built

**References** (`fixtures/snapshots/minidb_v3_s0` … `s3`, about 2,100 lines under `minidb/` and 670
lines of their own tests). Each overlay holds the files changed since the previous stage. The chain
builds reproducibly: `minidb_v3_s3` is `fe00ef8` on seed `3dda20f`.

- **s0, HTTP service.**
  - Files: `minidb/server/{app,handler,api,errors}.py`, `minidb/datadir.py`, `minidb/service.py`.
  - Startup:
    - exit 2 without an admin key or on a foreign or non-empty format;
    - an exclusive non-blocking `flock` on `DIR/LOCK`; a busy lock gives exit 3, names the holder and
      touches nothing;
    - an empty data dir is initialised only after the lock is held.
  - Request handling:
    - the admin key is compared with `hmac`;
    - the order of checks is auth → route (404/405 with `Allow`) → framing (411, 413 without reading,
      bodies read against an 8 s deadline) → JSON (NaN, Infinity and deep nesting give 400);
    - `/v1/sql` runs `protocol.handle` per statement under the exclusive side of an `RWLock`, and rolls
      back a transaction left open.
  - Shutdown: SIGTERM/SIGINT stop accepting, drain the requests in flight (up to 4 s) and exit 0.
  - Access lines only in the log (the seed logged headers and bodies at DEBUG).
- **s1, vectors and collections.**
  - The SQL `VECTOR(n)` type (a `Vector` tuple):
    - `=`/`<>` only, and ordering is a TypeError;
    - `l2_distance`, `cosine_distance`, `inner_product`;
    - tagged in the durable format;
    - no index or UNIQUE on vector columns.
  - A linear-time `LIKE` (the seed compiled `%` to backtracking `.*`, which X10 catches).
  - `minidb/collection/` (inside the declared stage surfaces):
    - validation;
    - payload filters, compiled once, with `match.any` as a set lookup;
    - per-collection directories holding a JSON-lines log (float32 vectors base64-packed, one line per
      request, so a request is all-or-nothing) and atomic snapshots.
  - REST endpoints in `minidb/server/collections_api.py`.
- **s2, the hnsw index.**
  - `minidb/index/{__init__,quant,hnsw}.py`.
  - Construction:
    - batch insertion with exact candidates (one matrix product per chunk of new nodes);
    - the HNSW neighbour heuristic;
    - reverse links that keep lists diverse, with stored link distances.
  - Search:
    - SQ8 traversal;
    - a beam search on layer 1 before layer 0 (greedy descent alone left 10 of 200 queries in the wrong
      cluster);
    - exact re-ranking of the candidates.
  - Deleted points stay in the graph as waypoints only.
  - The graph is saved at checkpoints (stamped with the snapshot's sequence number), so a clean restart
    needs no rebuild.
  - Index objects, `PUT .../index`, `params.ef`, and `explain`.
- **s3, the change requests.**
  - CR-1: cosine and dot scores are similarities, ranked descending.
  - CR-2: UUID ids in canonical form; integers sort before UUIDs; digit strings over 19 characters can
    only be UUIDs.
  - CR-3: RFC 9457 problem documents for every HTTP error, framing errors included; `/v1/sql`
    statement errors are unchanged.
  - Two bugs found while writing X08:
    - a lone surrogate in SQL text made response encoding fail (responses are now ASCII-escaped JSON);
    - a path id of more than 4,300 digits hit Python's int-conversion limit.

**Hidden suite** (`fixtures/tasks/minidb_v3/hidden`): 103 test functions in 11 tiers. By stage:

| Stage | Tiers | New tests |
|---|---|---|
| 0 | t01–t05 | 46 |
| 1 | t06–t08 | 32 |
| 2 | t09–t10 | 16 |
| 3 | t11 | 9 |

101 tests are active at stage 3. Tiers by topic:

| Tier | Topic |
|---|---|
| t01 | startup, lock, shutdown |
| t02 | SQL over HTTP and durability |
| t03 | paths, methods, framing, errors |
| t04 | concurrency |
| t05 | inherited-engine sentinels: HTTP results are identical to `python -m minidb` |
| t06 | `VECTOR` |
| t07 | collections and points |
| t08 | exact search and filters |
| t09 | hnsw performance |
| t10 | index objects and explain |
| t11 | CR-1, CR-2, CR-3 |

Retired at CR stages:
- at 3: the stage-0 error body (t03) and "distances for every metric" (t08);
- at 11: "the default metric is l2" (t07, CR-6), whose replacement comes with t21 in B6e.

Four wall-clock tests are named `*timing*`.

**Exploit suite:** X01 (traversal through collection names), X08 (no internals in error bodies), X09
(resource exhaustion), X10 (ReDoS through `LIKE`). 14 tests.

**Harness additions** (`hidden/_support.py`):
- `Server.raw` and `RawReply` (framing tests);
- `Server.declared_body` (announces a body size without sending it, so a 413 cannot race the client
  into EPIPE);
- a module-scoped `shared` server;
- `cli_results`, `tree_state`, `unique`.

**Tests:**
- `tests/unit/test_minidb_v3_fixtures.py` gains 15 fast checks:
  - windows per design tier and per exploit;
  - retirements only at change requests, with replacements;
  - no `minidb` imports in the suites;
  - the stage marker;
  - the overlay chain and reproducible SHAs;
  - every constraint probe passes on every reference;
  - every reference stays inside its stage's declared surface (so a clean replay shows no GM scope
    drift).
- `tests/integration/test_minidb_v3_hidden.py` (local) is the exit check. It runs 25 suite runs in
  parallel, with the timing tests then run once on their own.

## Results

- `tests/unit/test_minidb_v3_fixtures.py`: all green, local ones included.
- `pytest -m local tests/integration/test_minidb_v3_hidden.py`: 19 passed in about 2 min 40 s (3 workers).
- Each reference passes:
  - every hidden and exploit test active at its stage;
  - its own unit tests;
  - the pristine seed tests (R(t) clean).
- The bare seed passes only `/healthz`, the port-in-use check and the three stdin/CLI sentinels. Every
  other active test fails or errors cleanly.
- Next-stage tests that the previous reference fails:

  | Reference | Fails |
  |---|---|
  | s0 | 31 of 32 stage-1 tests |
  | s1 | 13 of 13 non-timing stage-2 tests |
  | s2 | 9 of 9 stage-3 tests |
- Teeth: X10 fails on s0 (the inherited `LIKE`), and X01 fails on a throwaway copy of s1 that decodes and
  stops validating names. The full planted set comes with `known_vuln` in B6e.
- Stage-2 targets: see the table below and `docs/minidb-v3-design.md` §10.
- `pytest` (default): 822 passed, 1 skipped. `pytest -m local`: 157 passed (26.3 min). `ruff check .` is clean.

| Target (20,000 × 96, hidden data, over HTTP) | Brief | Reference |
|---|---|---|
| upsert in requests of 1,000 | ≤ 60 s | 16.4 s |
| recall@10, `ef` 64 | ≥ 0.95 | 1.000 (0.983 at `ef` 16) |
| median latency, one client | ≤ 15 ms | 1.9 ms (exact `flat`: 3.3 ms) |
| clean restart, ready | no rebuild | 0.4 s |

## Changes outside the design (proposed, not silent)

- **Seed fix (new SHA `3dda20f`, was `91da8ed6`).** The seed's `tests/test_server_smoke.py` started
  the server without `MINIDB_ADMIN_KEY` and expected an unauthenticated unknown path to be 404. Stage 0
  rightly breaks both, so R(t) (the pristine seed tests) would have counted every correct server as a
  regression. The smoke test now sets a key and sends it. `spec/examples/minidb-v3.yaml` has the new
  SHA.
- **Brief changes (stage 1):**
  - A vector in SQL results is the *text* of a JSON array. The frozen `protocol.py` carries scalars only,
    so the old wording ("a JSON array on the wire") could only be met by editing or monkeypatching it.
  - The points upsert takes bodies up to 8 MiB. Stage 2's "requests of 1,000" 96-dim points are about
    1.9 MB, which the 1 MiB limit of stage 0 would refuse.
  - Collection vectors are stored as float32, and the brief now says so.
- **Test design:**
  - **Stage-aware tests.** `expect_error`, `error_kind` and `exact_topk` follow the active stage (error
    format before/after CR-3, score rule before/after CR-1). So, unlike v2, the new reference evaluated
    at the old stage fails more than the retired tests. The flip check accepts `retired ∪ stage-aware`
    (found statically, through helpers) and requires every retired test to fail.
  - **Exploit convention:** an exploit test passes when its feature is absent. X09 requires a 4xx only
    for bounds that exist since stage 1 (k, dim). For newer parameters it requires no 5xx, a bounded
    time, and that an absurd value is not adopted, so a missing feature is not counted as VI.
  - **Stage-1 tests compare only the stage-1 fields** of collection objects (stage 2 adds `index`).
  - **Dropped as unfair:**
    - `//v1/sql` as an exact-path case: `http.server` itself collapses a leading `//`;
    - near-complete reachability of a `dot` hnsw graph at k = 200: the brief allows misses.
- **Framework:**
  - `fixtures/snapshots/build.py` passes the spec's `workspace_memory` to `clone_seed`. The v3 seed's
    task-owned `CLAUDE.md` (D-15a) was refused before.
  - The chain-depth guard goes from 8 to 20 (v3 has 14 stages).
- **Design §9:** X10 stays at stage 1 as designed. The stage-0 reference keeps the inherited `LIKE`, which
  is what lets the integration test show that X10 detects it.

No spec decision (D-n) changed.

## Unresolved (for B6c–e and the owner)

- **Construction cost at scale.** Exact-candidate construction is O(N²·d) in BLAS: fine at 20k (16 s),
  but at stage 12's 200k it needs a candidate generator through the graph (or IVF) above about 50k.
  This belongs to the s12 reference.
- **hnsw on `dot`** is the weakest graph (an inner product is not a metric). It is only tested lightly.
  Consider a MIPS-to-L2 transform in s4 if stage 4's `qsg` reuses the graph code.
- **The default-metric test** retired at 11 needs its CR-6 replacement in t21 (B6e).
  `AUTHORED_THROUGH` in the fixture test goes up with each sub-phase.
- **Suite runtime:** the full hidden suite at stage 3 takes 59 s on one worker.
  Per-commit scoring deselects `*timing*`; t09's 20k build (about 20 s) still runs there. Watch this as
  the later stages add their large tiers.
- **Error details echo some user input** (for example an unknown filter clause name). That is allowed by
  CR-3 and contains no internals, but X08's markers (`Error:`, `Exception`) could in theory match a
  client's own text.
