# minidb v2: staged independent (blind) build — 2026-10-17

**What:** a Sonnet sub-agent built minidb v2 from the seed and the stage briefs only (never the
hidden tests, references or later stages), receiving stage s only after finishing stage s−1, in one
continuous session (its context grew across stages, as a real run's would). After each stage the
hidden suite was run through the real scorer at `LRAE_STAGE=s`. Not a harness run (no checkpoints,
telemetry or guardrails); it validates the task and calibrates its size.

| Stage | Kind | Agent time | Hidden tests (active at stage) | Regressions vs earlier stages |
|---|---|---|---|---|
| 0 core | feature | 5.8 min | 83/83 | – |
| 1 subqueries, CASE, set ops, INSERT…SELECT | feature | 4.5 min | 119/120 | 0 |
| 2 indexes, planner, performance limits | feature | 4.2 min | 138/139 | 0 |
| 3 CR-1..3 (NULLS LAST, `/` → REAL, ConstraintError) | change request | 1.7 min | 142/143 | 0 |
| 4 transactions, `--db` + crash recovery, ALTER | feature | 4.2 min | 163/164 | 0 |
| 5 views, WITH RECURSIVE, window functions | feature | 4.8 min | 186/187 | 0 |
| 6 CR-4 (names keep spelling) + DATE | change request | 3.4 min | 200/201 | 0 |

Total ≈ 28 minutes of agent time; final code ≈ 5,650 lines (engine + its own 350 tests), 11 commits.

**Fairness:** the only failing test across all stages (`test_t08 test_exists_and_not_exists`) traced to
a genuinely ambiguous sentence in stage 1 (output name of `NOT EXISTS`); the brief is clarified. No
other test failed an independent, brief-only implementation. Every performance and durability limit
was met by the independent build.

**Difficulty — the key finding:** even staged, with change requests and performance/durability
tiers, a strong model needs ≈ 28 minutes for the whole of v2 and regressed on nothing. In a 4-hour
run with stages every 30 minutes the agent would work ~5 minutes per window and idle (polish) the
rest. The task measures *stability over a long session with arriving requirements* (still useful:
context accumulation, compaction, idle-time churn), but it does not push the agent to the limit of
its capability, where degradation is most likely. See the options in the session summary.
