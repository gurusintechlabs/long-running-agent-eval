**Message from the product owner — stage 2: indexes, query plans and performance**

New requirements. The pilot client loaded real data and minidb became unusably slow: tens of
thousands of rows are normal for them. This stage adds indexes and a query planner, and sets
hard performance requirements. Many parts of the engine that were written for correctness first
will have to be revisited. Everything specified so far still applies, in particular: **results,
including their row order, must never depend on whether an index or a particular join strategy is
used.** Add tests, keep `python -m pytest` green, and commit at least once per section.

## 12. Indexes and EXPLAIN

- `CREATE [UNIQUE] INDEX [IF NOT EXISTS] name ON table (col)`: an ordered index on one column,
  usable for equality and range lookups. `DROP INDEX [IF EXISTS] name`. Index names have their
  own namespace (an index may share a name with a table). A duplicate index name, an unknown
  index, table or column is a `NameError` (`IF NOT EXISTS` / `IF EXISTS` turn the duplicate /
  unknown index case into a no-op, as for tables). `CREATE UNIQUE INDEX` also enforces uniqueness
  on the column exactly like the `UNIQUE` constraint, and fails with `ConstraintError` if the
  existing rows already have duplicates. Several indexes on the same column are allowed.
  `DROP TABLE` drops the table's indexes.
- **Implicit indexes.** Every `PRIMARY KEY` or `UNIQUE` column gets an index automatically when
  the table is created, named `<table>_<column>_key` (for example `emp_id_key`). It lives in the
  index namespace (if that name is already taken, `CREATE TABLE` is a `NameError`), counts as
  created at the moment its table was created, and is dropped with its table. `DROP INDEX` on an
  implicit index is a `ConstraintError`.
- Indexes must stay correct through every `INSERT`, `UPDATE` and `DELETE`. A lookup through an
  index returns exactly the rows a full scan would, in the same (table) order.
- `EXPLAIN query` does not run the query; it validates it (unknown names are still a `NameError`,
  syntax errors a `SyntaxError`) and returns the plan: columns `["plan"]`, one row per table
  reference in the `FROM` clause of the outer query, in `FROM` order; for a set operation, the rows
  of each operand in order. Subqueries (in expressions or as derived tables) add no rows, and a
  query without `FROM` has no rows. `EXPLAIN` of anything that is not a query is a `SyntaxError`.
- **Plan of the first table reference.** Consider the top-level `AND`-ed conjuncts of `WHERE`
  (a top-level `OR` gives no conjuncts). A conjunct is *usable* if it has the form
  `col op literal` or `literal op col` with `op` one of `= < <= > >=`, or
  `col BETWEEN literal AND literal`, where `col` is a column of the first table reference (written
  `col` or `x.col`) that has an index, and a literal is a number (optionally with one leading `-`
  or `+`), a string, `TRUE` or `FALSE` (not `NULL`). Then:
  1. if some usable conjunct uses `=`, take the leftmost such conjunct and report
     `SEARCH <table> USING INDEX <index> (<col> = ?)`;
  2. else, if there is any usable conjunct, take the leftmost and report
     `SEARCH <table> USING INDEX <index> (<col> RANGE)`;
  3. else report `SCAN <table>`.

  A literal whose type cannot be compared with the column still gives `SEARCH`; executing such a
  query behaves exactly like a full scan would (a `TypeError` as soon as a non-NULL value of the
  column is compared).
- **Plan of a later table reference** joined with `INNER` or `LEFT JOIN`: consider the top-level
  `AND`-ed conjuncts of its `ON` condition. A conjunct is an *equi-join conjunct* if it has the
  form `a = b` where one side is a column of this table reference and the other a column of a
  table reference to its left in the same `FROM` (plain column references, qualified or not).
  Take the leftmost such conjunct; if this reference is a table and its column has an index,
  report `SEARCH <table> USING INDEX <index> (<col> = ?)`; otherwise report
  `HASH JOIN <name> (<col>)`. Without an equi-join conjunct, and for `CROSS JOIN`, report
  `SCAN <name>`.
- In plans, `<table>` is the table's name (never its alias), `<name>` is the table's name or, for
  a derived table, its alias, and `<col>` the column's name. If a column has several indexes,
  `<index>` is the one created first. For example, with an index `idx_age` on `people(age)`,
  `EXPLAIN SELECT * FROM people WHERE name = 'x' AND age > 30` returns
  `{"ok": true, "columns": ["plan"], "rows": [["SEARCH people USING INDEX idx_age (age RANGE)"]]}`.
- A plan is a promise: a query whose plan says `SEARCH` must look its rows up through that index,
  and a `HASH JOIN` must find partner rows through a hash table of the joined side's key column,
  not by testing every pair. Rows excluded by an index lookup or a hash probe are never evaluated
  against the rest of the condition, so errors that a full scan would have raised on those rows
  are not reported. The only exception: an equi-join conjunct comparing incomparable types (an
  INTEGER key with a TEXT key, say) is a `TypeError` whenever both sides have at least one
  non-NULL key, whatever the plan. NULL keys never match.
- `UPDATE` and `DELETE` choose their rows with the same rule as the first table reference of a
  `SELECT` (they are not `EXPLAIN`-able, but the performance requirements below apply to them).

## 13. Performance

Time is measured from the moment a statement has been written to minidb's stdin until its JSON
line has been read, with the process already running (startup is not counted), on an ordinary
current laptop. When an average is given, it is the total time of a long sequence of such
statements sent back to back, divided by their number. Tables have up to 50,000 rows, with a
`PRIMARY KEY` and up to two more indexes.

| Operation | Limit |
|---|---|
| `INSERT ... SELECT` adding 50,000 rows to an indexed table (the `SELECT` being a cross join of small tables) | 10 s per statement |
| `INSERT ... VALUES` with 1,000 rows into an indexed table of 50,000 rows | 0.5 s per statement |
| point query `SELECT ... WHERE col = literal` on an indexed column (explicit or implicit index) | 5 ms on average |
| range query on an indexed column that returns at most 100 rows (`BETWEEN`, or a lower and an upper bound on that column combined with `AND`) | 10 ms on average |
| single-row `INSERT`, and `UPDATE` / `DELETE` with `WHERE pk = literal` | 2 ms on average |
| inner or left equi-join of a 50,000-row table with a 20,000-row table (no index needed), with grouping or aggregation on top | 3 s |
| `x IN (SELECT ...)` / `NOT IN` with an uncorrelated subquery, 50,000 outer rows and 20,000 subquery rows | 2 s |
| `ORDER BY` over 50,000 rows (one or two keys, with or without `LIMIT`) | 2 s |
| `GROUP BY` over 50,000 rows into 1,000 groups with several aggregates | 2 s |
| full scan with a `WHERE` condition over 50,000 rows | 1 s |
