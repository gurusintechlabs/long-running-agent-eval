# minidb v2: a staged, long-horizon version of the minidb task (L3)

**Status:** draft for review · **Task:** `fixtures/tasks/minidb_v2/` · **Spec:** `spec/examples/minidb-v2.yaml`
· **Contract:** `docs/interfaces.md` §9 (staged requirements, proposed D-18)

## 1. Why a v2

The blind check of minidb v1 (`docs/minidb-blind-check.md`) showed two problems for a multi-hour study:

1. **Too easy.** An independent Sonnet agent implemented all twelve v1 tiers from the brief in about
   eleven minutes and passed 96/96 hidden tests. P(t) would saturate in the first checkpoint.
2. **No revision.** With the whole spec visible at t=0, a capable agent designs everything up front
   and never has to change earlier work. The study is about degradation of long-running coding:
   regressions, rework, forgotten requirements, context loss. Those only show up when earlier code
   has to be revisited.

The blind build also logged 35 places where the v1 brief was silent or loose.

## 2. Design goals

- **Staged brief.** Seven stages are delivered over the run (`stages.yaml`). Stage 0 is a solid core;
  each later stage is a product-owner message ("New requirements" or "Change request").
- **Every later stage forces revision, not just addition.** Performance limits invalidate the naive
  storage, constraint checks, joins and `IN`; transactions invalidate "mutate in place"; durable
  storage needs a log in every write path; change requests overturn earlier rules everywhere they
  apply; case-preserving names and a new type cut across the lexer, catalog, planner, storage format
  and output encoding.
- **Compounding.** Later tests reuse earlier features (performance data is generated with
  `INSERT ... SELECT` over cross joins and `CAST`; durability tests use indexes, constraints, views;
  window tests run over views and recursive `WITH`). 184 of the 201 tests active at the final stage
  were introduced in earlier stages and stay active as regression sentinels.
- **Retirement, not contradiction.** A change request retires the tests of the old behaviour
  (`@stage(introduced, retired)`) and introduces replacements. Only change-request stages retire
  tests; feature stages never do (checked by `tests/unit/test_minidb_v2_fixtures.py`).
- **Precise, testable briefs.** All 35 v1 ambiguities are pinned down (§7). Briefs never mention tests.
- **Fair performance limits.** Generous for any correct design (25–100× the reference) yet
  discriminating against the naive designs a first pass produces (5–1000× over the limit), measured
  on this machine (§5).
- **Same harness contract as v1.** Same seed (`fixtures/seed_minidb`, pinned SHA `53b58af0…`),
  same planted constraints (`constraints.yaml` copied from v1), same black-box runner, serverless
  `scorer.yaml`. `protocol.py` stays untouched, so every new capability is engine-side (the `--db`
  option is parsed in `minidb/__main__.py`, which is not protected).

## 3. Timeline (240-minute run)

> **Superseded (owner, 2026-10-17):** stages are no longer delivered at fixed times. Each stage now
> goes to the agent as soon as it finishes the previous one, and the run ends when stage 6 is done
> (spec §4.4, D-18). The `at_frac` column below is the original schedule, kept for the record; the
> first real run (docs/minidb-v2-blind-check.md, trial 1 report) showed the agent idle about half of it.

| Stage | at_frac | t (min) | kind | Brief | Forces the agent to revise |
|---|---|---|---|---|---|
| 0 | 0.000 | 0 | feature | `stage0.md`: core engine, sections 1–7 (v1 tiers 1–6 and joins, every ambiguity pinned) | — (baseline) |
| 1 | 0.125 | 30 | feature | `stage1.md`: subqueries (correlated, lazy uncorrelated), CASE, CAST, SUBSTR/ROUND/NULLIF/REPLACE/TRIM, UNION/INTERSECT/EXCEPT, INSERT…SELECT, derived tables, IF [NOT] EXISTS; new reserved words | parser (query vs. SELECT core, ORDER BY hoisting, reserved words), name resolution with outer scopes, the grouping rule extended into subqueries |
| 2 | 0.250 | 60 | feature | `stage2.md`: indexes (explicit, implicit for PK/UNIQUE, UNIQUE indexes), EXPLAIN with join plans (SEARCH / HASH JOIN / SCAN), plans as promises, hard performance limits on 50,000-row tables | storage (indexes), constraint checks (index-backed, not O(n)), join executor (hash and index nested loop while keeping nested-loop row order), UPDATE/DELETE row selection, hashed `IN`, every O(n) per-statement path |
| 3 | 0.375 | 90 | change_request | `stage3.md`: CR-1 NULLs sort last (NULLS FIRST/LAST syntax), CR-2 `/` always REAL + new `DIV`, CR-3 storage type mismatch becomes ConstraintError | the sort used by ORDER BY / set ops / subqueries, arithmetic, every storage path (INSERT VALUES/SELECT, UPDATE, DEFAULT); the agent's own tests |
| 4 | 0.500 | 120 | feature | `stage4.md`: transactions (O(changes), not O(database)), `--db PATH` durable storage surviving SIGKILL (all-or-nothing statements, uncommitted work lost), ALTER TABLE ADD/DROP COLUMN | the in-place mutation model (undo or copy-on-write), every write path (redo logging), recovery, catalog changes inside transactions |
| 5 | 0.625 | 150 | feature | `stage5.md`: views, WITH and WITH RECURSIVE, window functions | table-reference resolution (views, WITH names, shadowing), the SELECT pipeline (window stage between HAVING and DISTINCT), plans for non-table sources, storage of views |
| 6 | 0.750 | 180 | change_request | `stage6.md`: CR-4 names keep their defined spelling (matching stays case-insensitive), DATE type | lexer, catalog keys, name resolution, output names, plan strings, implicit index names, storage format; the value system (new type in comparisons, arithmetic, casts, indexes, hashing, storage, wire encoding) |

`max_wait_frac: 0.05` (12 minutes): a turn still running then is interrupted so the stage can go
out. The last stage arrives at 180 minutes, so a strong agent cannot finish early: every interval
carries new work, and the stage-6 refactor lands with an hour to go.

## 4. Hidden tests

`fixtures/tasks/minidb_v2/hidden/`: 211 tests in 22 tiers (`test_tNN_<topic>.py`), each with
exactly one `@stage(introduced, retired=None)` marker (`_support.stage`, a `skipif` on
`LRAE_STAGE`; unset = final stage 6). `_support.py` also provides `Session` (one long-lived
`python -m minidb [--db PATH]` process: statement-by-statement answers, pipelined timing, SIGKILL)
and `big_table_sql` (50,000-row tables generated with `INSERT ... SELECT` over a 5-way cross join).

| Stage | introduced | retired at this stage | active |
|---|---|---|---|
| 0 | 83 (t01–t07) | – | 83 |
| 1 | 37 (t08–t11) | – | 120 |
| 2 | 19 (t12–t13) | – | 139 |
| 3 | 11 (t14) | 7 | 143 |
| 4 | 21 (t15–t17) | – | 164 |
| 5 | 23 (t18–t20) | – | 187 |
| 6 | 17 (t21–t22) | 3 | 201 |

Tests per tier: t01 basics 13 · t02 expressions 15 · t03 shaping 12 · t04 update/delete 10 ·
t05 constraints 11 · t06 aggregates 11 · t07 joins 11 · t08 subqueries 11 · t09 CASE/CAST/functions 11 ·
t10 set operations 7 · t11 INSERT…SELECT/derived 8 · t12 indexes/EXPLAIN 12 · t13 performance 7 ·
t14 change requests 1–3 11 · t15 transactions 8 · t16 durability 8 · t17 ALTER TABLE 5 · t18 views 6 ·
t19 WITH 9 · t20 window functions 8 · t21 CR-4 names 7 · t22 DATE 10.

**Retired tests** (old behaviour pinned until the change request; the replacement lives in t14 / t21):

| Change request | Retired test (introduced at) | Replaced by |
|---|---|---|
| CR-1 (stage 3) | `t03::test_nulls_sort_first_ascending_and_last_descending` (0) | `t14::test_nulls_sort_last_ascending_and_first_descending`, `test_nulls_first_and_nulls_last`, `test_null_ordering_in_set_operations_subqueries_and_derived_tables` |
| CR-2 (stage 3) | `t02::test_integer_division_truncates_toward_zero` (0) | `t14::test_division_always_returns_real`, `test_div_function`, `test_division_in_queries_storage_and_aggregates` |
| CR-3 (stage 3) | `t01::test_insert_type_check_precedes_not_null_check` (0), `t04::test_update_storing_wrong_type_is_a_type_error` (0), `t05::test_default_that_does_not_fit_is_a_type_error` (0), `t05::test_storing_a_value_of_the_wrong_type_is_a_type_error` (0), `t11::test_insert_select_wrong_type_is_a_type_error` (1) | `t14::test_storing_a_value_that_does_not_fit_is_a_constraint_error`, `test_default_that_does_not_fit_is_a_constraint_error`, `test_constraint_error_keeps_its_place_in_the_error_order` |
| CR-4 (stage 6) | `t01::test_names_are_case_insensitive_and_reported_lowercase` (0), `t12::test_plans_report_names_in_lower_case` (2), `t19::test_with_and_view_column_lists_are_reported_in_lower_case` (5) | `t21::*` (7 tests) |

Sentinels around each change request check what it leaves alone (`t14::test_what_cr1_leaves_alone`,
`test_type_errors_that_are_not_about_storage_are_unchanged`, `t21::test_data_stays_case_sensitive`).
Every other test was verified to give the same result under the old and the new rule (the
reference of stage s-1 and of stage s both pass every test active at both stages; only the
retired ones differ, see §6).

## 5. Performance limits and measurements

Machine: Apple M1 Max, Python 3.13 (repo `.venv`). "Reference" = `minidb_v2_s2` (indexes, hash
joins, hashed `IN`); "naive" = `minidb_v2_s1` (the correct stage-1 design: full scans, nested-loop
joins, O(n) unique checks). Naive join and `IN` numbers are for a 2,000-row left side (the full
50,000 rows would take 10–25 minutes). Batches are pipelined; per-statement figures are averages.

| Requirement (stage2.md §13, stage4.md §15–16) | Limit | Reference | Naive |
|---|---|---|---|
| `INSERT ... SELECT` of 50,000 rows into an indexed table | 10 s | 1.15 s | 1.14 s (not discriminating; sanity bound) |
| `INSERT ... VALUES` with 1,000 rows into 50,000 | 0.5 s | 0.03 s | 0.04 s (sanity) |
| point query on an explicit / implicit index | 5 ms avg | 0.05 ms | 34 ms |
| range query returning ≤ 100 rows (BETWEEN / two bounds) | 10 ms avg | 0.30 / 0.16 ms | 57 / 52 ms |
| single-row INSERT / UPDATE by pk / DELETE by pk | 2 ms avg | 0.07 / 0.05 / 0.06 ms | 6.8 / 37 / 30 ms |
| equi-join 50,000 × 20,000 (hash / left hash + GROUP BY / index nested loop) | 3 s | 0.06 / 0.07 / 0.06 s | 24 s each for 2,000 left rows |
| `IN` / `NOT IN (SELECT ...)`, 50,000 × 20,000 | 2 s | 0.07 s | 10 s for 2,000 outer rows |
| ORDER BY 50,000 rows (2 keys, LIMIT) | 2 s | 0.08–0.11 s | same (sanity) |
| GROUP BY 50,000 rows into 1,000 groups | 2 s | 0.12 s | same (sanity) |
| full scan with WHERE | 1 s | 0.06 s | same (sanity) |
| small transactions on a 50,000-row table (BEGIN/UPDATE/DELETE/INSERT/ROLLBACK, BEGIN/…/COMMIT) | 5 ms avg | 0.24 / 0.26 ms | deep copy at BEGIN: 161 ms per transaction (≈ 32 ms avg) |
| `--db`: autocommit single-row INSERT / UPDATE | 5 ms avg | 0.06 / 0.05 ms | full snapshot per statement: 142 ms |
| `--db`: COMMIT of 1,000 changed rows | 0.2 s | 1.2 ms | — |
| `--db`: open a 50,000-row database to the first answer | 2 s | 0.10 s | — |

Whole hidden suite at the final stage on the final reference: about 36 s (seven performance tests
≈ 1.5–2.2 s each, the crash test ≈ 5.4 s). Per-stage runs are shorter.

## 6. Reference implementation and verification

Overlay chain `fixtures/snapshots/minidb_v2_s0` (base: seed, `spec: spec/examples/minidb-v2.yaml`)
→ `minidb_v2_s1` → … → `minidb_v2_s6`, plus `minidb_v2_known_bad` (base `minidb_v2_s6`: cosmetic
`protocol.py` refactor, unused `import sqlite3`, a string scanner that crashes on an unterminated
literal, breaking exactly `tests/test_cli.py::test_unterminated_string_literal_is_an_error_not_a_crash`).
Stdlib only; one test module per new source module. Built snapshots are byte-identical to the
development trees and have stable SHAs (`build.py` → s6 `03562f5a…`).

| Stage | Engine source lines (excl. `protocol.py`) | Own test lines | Changed lines vs previous stage (diff ±) |
|---|---|---|---|
| 0 | 1,577 | 192 | (new) |
| 1 | 2,059 | 267 | 574 |
| 2 | 2,597 | 323 | 467 |
| 3 | 2,629 | 326 | 94 |
| 4 | 3,026 | 395 | 248 |
| 5 | 3,556 | 441 | 443 |
| 6 | 3,688 | 483 | 258 |

Design of the final reference: lexer → recursive-descent parser → closures compiled once per
statement (`executor.py`); `planner.py` picks index SEARCH / HASH JOIN / SCAN and narrows index
ranges with every usable conjunct; constraints are checked through the indexes; transactions are
copy-on-write (catalog copy at BEGIN, per-table row dict and index list copies on first touch);
`durable.py` keeps a JSON snapshot plus an append-only log with one line per committed unit (torn
tails discarded, checkpoint by temp file + rename, sequence numbers make replay idempotent);
`windows.py` computes window functions over row envs without reordering rows; CR-4 uses a
case-insensitive catalog dict and keeps defined spellings everywhere names are reported.

**Verification** (all green on this machine):

- every reference `s` passes 100% of the tests active at `LRAE_STAGE=s` (and its own unit tests and
  the pristine seed tests);
- the bare seed fails every final-stage test cleanly (no errors, no collection failures);
- reference `s` fails most of the tests introduced at `s+1`: 37/37, 19/19, 9/11, 20/21, 23/23, 15/17
  (the passes are deliberate sentinels such as "what CR-1 leaves alone");
- around each change request, reference `c` evaluated at stage `c-1` fails exactly the tests retired
  at `c` (7 at CR stage 3, 3 at CR stage 6), and reference `c-1` evaluated at `c` fails the replacements;
- the real scorer (`score_snapshot_dir`, FakeJudge) gives the reference of the stage it scores P = 1.0, R = 0, C = 0, no
  hazards, and flags `minidb_v2_known_bad` with `protocol-untouched` + `no-embedded-db` and R = 1.

Commands:

```
.venv/bin/python -m pytest tests/unit/test_minidb_v2_fixtures.py          # fast checks
.venv/bin/python -m pytest -m local tests/integration/test_minidb_v2_hidden.py   # ~5 min, no spend
```

## 7. How the 35 v1 ambiguities are pinned

| v1 ambiguity (blind-check log) | v2 rule (stage brief § ) |
|---|---|
| `-9223372036854775808` literal | SyntaxError: the range is checked on the literal before unary minus (0 §1) |
| REAL inf/NaN results; `1e5`, `.5`, `5.` | non-finite REAL result is a RuntimeError; no exponent; `.5`/`5.` SyntaxError; too-large REAL literal SyntaxError (0 §1, §2) |
| short-circuit of AND/OR/COALESCE, checks on the unevaluated side | left-to-right, only AND/OR/COALESCE (and later CASE) skip operands; a skipped operand cannot error (0 §0, 1 §9) |
| SUM overflow on intermediate vs final; REAL accumulation order | exact integer sum, only the total must fit; REAL sum adds doubles in input order from 0.0; AVG defined from that sum (0 §6) |
| HAVING without aggregates makes a query grouped; aggregates/DISTINCT without FROM | yes; without FROM aggregates see one empty row, DISTINCT is the only clause allowed (0 §2, §6) |
| ORDER BY: `*` names, `ORDER BY 0`, `1+0`, `-1`, `TRUE` | `*` names count; only a bare unsigned integer literal is a position (0 = SyntaxError); other constants are expressions (0 §3) |
| mixed-type sort keys on a one-row table | TypeError iff one ORDER BY item has two non-NULL incomparable values among the sorted rows, whatever the algorithm; 0–1 rows never fail; windows: within a partition (0 §3, 5 §20) |
| INSERT error precedence across rows; DEFAULT keyword | rows in order: evaluate, type-check, NOT NULL; UNIQUE/PK after all rows; same for UPDATE; `VALUES (DEFAULT)` SyntaxError (0 §1, §4) |
| `COMMIT/ROLLBACK TRANSACTION`, `BEGIN TRANSACTION` | all accepted (4 §15) |
| index plans: wrong-type literal, `EXPLAIN SELECT 1`, `+5` | still SEARCH, executes like a scan (TypeError); no FROM = no plan rows; one leading `-` or `+` allowed (2 §12) |
| aliases in UPDATE/DELETE, derived tables, comma joins, ON referencing a later table | UPDATE/DELETE aliases SyntaxError; derived tables added in stage 1; comma/RIGHT/FULL joins SyntaxError; later table in ON NameError (0 §4, §7; 1 §11) |
| aggregates in ON/UPDATE/INSERT; `SUM(DISTINCT x)` | SyntaxError; DISTINCT allowed in every aggregate (0 §1, §4, §6) |
| SAVE atomicity, LOAD validation, name clash on LOAD | replaced by `--db` durability: atomic per statement/COMMIT under SIGKILL; foreign file → IOError for every statement, file untouched (4 §16) |
| correlated subquery referencing a non-grouped column of a grouped outer query | SyntaxError: the grouping rule extends into subqueries; an aggregate belongs to the query it is written in (1 §8) |
| output name of `(a)`; innermost-first resolution | `(a)` is still a column reference; names resolve innermost-first, ambiguity in the innermost matching query is a NameError (0 §2, 1 §8) |
| (new) join type errors vs hash joins; errors on rows an index excludes | equi-join key types incomparable → TypeError whenever both sides have a non-NULL key; rows excluded by a plan are never evaluated (2 §12) |
| (new) uncorrelated subquery errors on empty tables | evaluated at most once, only when first needed (1 §8) |
| (new) NULLIF and the general NULL rule; REAL → TEXT format | NULLIF exempt; Python `repr` (1 §9) |

## 8. Open questions for the reviewer

1. **Scoring cost.** The per-commit hidden scoring (interfaces.md §8) runs the whole suite per
   sampled commit: 36 s × up to 40 commits ≈ 24 min per checkpoint at the final stage. Consider
   sampling fewer commits for this task, or a "fast" subset (skip `t13`/`t16` timing tests) for
   per-commit runs.
2. **Timing under load.** The scorer runs on the same machine while the agent works. Limits are
   25–100× the reference for per-statement items, but the bulk-load sanity bound (10 s vs 1.15 s)
   and the join limits (3 s vs ~0.06 s) assume no extreme contention. If flakes appear, rerun failed
   `t13`/`t15`/`t16` tests once before counting them.
3. **Change requests vs. agent tests.** CR stages require the agent to rewrite its own tests. The
   regression suite R(t) uses only the pristine seed tests, so this is not penalised; but X(t) (the
   judge) may count the deliberate behaviour changes as contradictions. The judge bundle should
   include the stage messages, or contradictions that follow a change request should be discounted.
4. **Delivery while idle.** If an agent finishes a stage early and ends its turn, the runner's
   continuation prompts drive it until the next stage. The stage-0 brief tells it to keep improving
   while it waits; confirm that the loop driver does not stop the run when the agent says "done".
5. **Difficulty calibration.** The stage contents were sized by judgement, not by a blind run. A blind
   staged build (deliver the seven briefs to a sub-agent with the timeline compressed) would show
   whether a stage can be finished within its 30-minute window; stages 2, 4 and 5 are the largest.
6. **Stage 6 load.** CR-4 plus DATE in the last hour is deliberately heavy (the point is to observe a
   late cross-cutting refactor), but it means P(t) at the final checkpoint mostly reflects whether
   the agent got through it. An alternative is to move DATE to an extra stage at 0.875.
7. **Standalone scoring stage.** interfaces.md §9 says standalone scoring (no `LRAE_STAGE`) applies
   the final stage, but `score_snapshot_dir` currently passes `stage=0` (the stage active at its
   synthetic checkpoint), so `minidb_v2_s6` scores P = 76/83 there: it correctly fails the 7 tests
   retired at stage 3. `tests/integration/test_minidb_v2_hidden.py` tolerates either behaviour (it
   scores the reference of whatever stage the scorer reports); the scorer or §9 should be aligned.
