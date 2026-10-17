**Message from the product owner — stage 5: views, common table expressions, window functions**

New requirements. The analytics team is moving its reporting onto minidb. They need named views,
`WITH` queries (including recursive ones for hierarchies) and window functions for rankings and
running totals. Everything specified so far still applies: the CR-1 NULL ordering, the
performance limits, transactions and durable storage. Add tests, keep `python -m pytest` green,
and commit at least once per section.

**Reserved words.** `WITH` becomes reserved. `RECURSIVE`, `OVER` and `PARTITION` are not
reserved.

## 18. Views

- `CREATE VIEW [IF NOT EXISTS] name [(col, ...)] AS query`: a named query (a `SELECT`, a set
  operation or a `WITH` query). Tables and views share one namespace: a clash is a `NameError`,
  and `IF NOT EXISTS` (here and in `CREATE TABLE IF NOT EXISTS`) does nothing when a table *or* a
  view of that name exists. The query is checked when the view is created (unknown names are a
  `NameError`) and is re-run every time the view is used, so a view always reflects the current
  data, and `SELECT *` in a view picks up columns added later. A column list renames the output
  columns (a different number of names is a `SyntaxError`, a repeated name a `NameError`);
  otherwise the columns are the query's output names.
- A view can be used wherever a table can appear in a `FROM` clause, including joins, subqueries,
  derived tables, `WITH` queries and other views. Its rows come in the order its query returns
  them (its "table order"). In plans, a view is `SCAN <view>`, or `HASH JOIN <view> (<col>)` as
  the joined side of an equi-join (section 12); a view never gives `SEARCH`.
- `DROP VIEW [IF EXISTS] name`. `DROP VIEW` on a table and `DROP TABLE` on a view are a
  `NameError` (also with `IF EXISTS`, which only applies when no table or view of that name
  exists). Dropping a table (or column) that a view uses is allowed; using the view afterwards is
  a `NameError`. `INSERT`, `UPDATE`, `DELETE`, `CREATE INDEX` and `ALTER TABLE` on a view are a
  `NameError`.
- Views take part in transactions and are durable, like tables.

## 19. WITH queries (common table expressions)

- `WITH name [(col, ...)] AS (query) [, name [(col, ...)] AS (query) ...] query`. A `WITH` query
  can be used wherever a query can: as a statement, in subqueries, as a derived table, as the
  source of `INSERT ... SELECT` (`INSERT INTO t WITH ... SELECT ...`), in `CREATE VIEW` and after
  `EXPLAIN`.
- Each name behaves like a table holding its query's rows (in the order the query returns them),
  visible in the main query and in the queries of the names defined after it, including their
  subqueries. Within the `WITH` query a name hides a table or view of the same name. Two names in
  one `WITH` that are equal are a `NameError`. Column lists work as for views. In plans, a
  reference to a `WITH` name is `SCAN <name>` or `HASH JOIN <name> (<col>)`.
- `WITH RECURSIVE` allows each name's query to refer to the name itself. A self-referencing
  query must have the form `anchor UNION [ALL] step`: the last operand of the top-level set
  operation is the step, everything before it is the anchor. The anchor must not refer to the
  name; the step must refer to it exactly once, as a table reference of its own `FROM` clause (not
  inside a subquery or derived table), and must not use aggregates, `GROUP BY`, `DISTINCT`,
  `ORDER BY` or `LIMIT`. Violations are a `SyntaxError`. Without `RECURSIVE`, a query that names
  itself refers to a table or view of that name (or is a `NameError`).
- Evaluation of a recursive name: the anchor's rows form the result and the first working set.
  Then, repeatedly, the step is evaluated with the name standing for the working set only (the
  rows produced in the previous round); with `UNION`, rows that duplicate a row already in the
  result, or an earlier row of the same round, are discarded; the remaining rows are appended to
  the result and become the next working set. Evaluation stops when a round produces no rows.
  Result order: anchor rows, then each round's rows in the order the step returned them. With
  `UNION` the anchor's own duplicates are removed too. If the result grows beyond 100,000 rows,
  the statement is a `RuntimeError`.

## 20. Window functions

- `function(args) OVER ([PARTITION BY expr, ...] [ORDER BY item [ASC | DESC]
  [NULLS FIRST | NULLS LAST], ...])` with these functions:
  - `ROW_NUMBER()`, `RANK()`, `DENSE_RANK()`;
  - `LAG(expr [, offset [, default]])` and `LEAD(expr [, offset [, default]])`; `offset` is a
    non-negative integer literal (default 1, anything else a `SyntaxError`), `default` an
    expression evaluated for the current row (NULL if omitted);
  - the aggregates `COUNT(*)`, `COUNT(expr)`, `SUM`, `AVG`, `MIN`, `MAX` (without `DISTINCT`,
    which is a `SyntaxError` with `OVER`).
  `ROW_NUMBER`, `RANK`, `DENSE_RANK`, `LAG` and `LEAD` without `OVER` are a `SyntaxError`; an
  aggregate without `OVER` is an ordinary aggregate. The output name is the function name in lower
  case (`row_number`, `sum`).
- Window functions may appear only in the select list and the `ORDER BY` of a query (also inside
  larger expressions there, such as `ROW_NUMBER() OVER () * 10`). Anywhere else (`WHERE`,
  `GROUP BY`, `HAVING`, `ON`, `UPDATE`, `INSERT ... VALUES`, the argument of an aggregate, inside
  another window function's arguments or `OVER` clause) they are a `SyntaxError`.
- Window functions are computed after `FROM`, `WHERE`, `GROUP BY` and `HAVING`, and before
  `DISTINCT`, `ORDER BY` and `LIMIT`. In a grouped query they see one row per group, and their
  arguments, `PARTITION BY` and `ORDER BY` may use grouping columns and aggregates (the grouping
  rule of section 6 applies to them).
- Rows with equal `PARTITION BY` values (equality as for `DISTINCT`) form a partition (without
  `PARTITION BY`, all rows form one). Within a partition, rows are ordered by the window's
  `ORDER BY` with exactly the rules of a query's `ORDER BY` (direction, NULL placement as in CR-1,
  `NULLS FIRST`/`LAST`, stable: rows that tie keep the order they had before window functions were
  computed, and the type rule of section 3 applied within the partition), except that an integer
  literal there is a constant, not a column position. Rows that tie on every window `ORDER BY`
  item are *peers*; without a window `ORDER BY`, all rows of the partition are peers.
- Values: `ROW_NUMBER` is 1, 2, 3, ... in partition order. `RANK` is 1 plus the number of rows of
  the partition before the row's first peer; `DENSE_RANK` is 1 plus the number of distinct peer
  groups before it. `LAG`/`LEAD` give `expr` evaluated on the row `offset` rows before/after the
  current one in partition order, or `default` if there is no such row. An aggregate with a
  window `ORDER BY` is computed over the rows from the start of the partition through the
  current row's last peer (a running total in which peers share a value); without a window
  `ORDER BY`, over the whole partition. Aggregates follow section 6 (types, NULLs, overflow).
- Window functions never change the row order: without a query-level `ORDER BY`, rows come out
  in the order they would have without the window functions. The query's `ORDER BY` may use the
  results by output name or position, or contain window functions itself.
