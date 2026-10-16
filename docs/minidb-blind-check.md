# minidb: independent (blind) implementation check — 2026-10-16

**What:** a Sonnet sub-agent implemented minidb from `fixtures/seed_minidb` + `fixtures/tasks/minidb/prompt.md`
only (no hidden tests, no reference), in a scratch dir. Not a harness run: no checkpoints,
telemetry or guardrails; it validates the task, not agent safety.

**Result:** all 12 tiers, ~1,900 lines (compiler 681, parser 537, engine 231, storage 176, values 128,
lexer 79, persist 74) + ~440 lines of its own tests, in ~11 minutes of agent time, 5 commits.
Hidden suite via the real scorer (`p_hidden.score_hidden`): **96/96 passed** (every tier 100%).

**Conclusions**
1. *Fairness:* no hidden test failed an independent, prompt-only implementation → no unfair or
   under-specified test found.
2. *Difficulty (important):* a capable model finished the whole ladder in minutes. In multi-hour runs P(t)
   will saturate at 1.0 early and stop discriminating; signal will come from R, C, W, cost and
   safety instead. To make minidb a real long-horizon task, consider: (a) hidden tests for the gaps
   below once the brief pins them down; (b) a performance tier (e.g. 20k x 20k join and indexed
   lookups under a time limit — the blind build's nested-loop join was quadratic); (c) more tiers
   (CASE, UNION, INSERT…SELECT, derived tables, IF NOT EXISTS, a write-ahead log) as an L3 variant.

**Ambiguity log (brief is silent or loose; the blind build's choice in brackets)** — candidates to
pin down in `prompt.md` and then test:
- `-9223372036854775808` literal [SyntaxError]; REAL inf/NaN results [RuntimeError]; `1e5` [SyntaxError].
- Short-circuit of AND/OR/COALESCE and type checks on the unevaluated side [short-circuit, no check].
- SUM overflow on intermediate vs final total [final only]; REAL accumulation order [row order].
- HAVING without aggregates makes a query grouped? [yes]; aggregates/DISTINCT without FROM [allowed].
- ORDER BY: `*`-expanded names count as output columns? [yes]; `ORDER BY 0`, `1+0`, `-1`, `TRUE`.
- Mixed-type sort keys on a one-row table [no error].
- INSERT error precedence across rows; DEFAULT keyword in VALUES [SyntaxError].
- `COMMIT/ROLLBACK TRANSACTION` [SyntaxError]; `BEGIN TRANSACTION` [accepted].
- Index plans: literal of the wrong type still SEARCH?; `EXPLAIN SELECT 1` [0 rows]; `+5` usable?
- Table aliases in UPDATE/DELETE, derived tables, comma joins [SyntaxError]; ON referencing a later table [NameError].
- Aggregates in ON/UPDATE/INSERT [SyntaxError]; `SUM(DISTINCT x)` [SyntaxError].
- SAVE atomicity on an existing file (temp+rename?); LOAD validation strictness; table/view name clash on LOAD.
- Correlated subquery referencing a non-grouped column of a grouped outer query [first row of group].
- Output name of `(a)` [a]; tier 6 vs tier 8 wording on outer references [innermost-first].
