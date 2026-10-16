You are working in `minidb`, a small Python project in the current directory (see README.md). It
is meant to become an in-memory SQL database engine that clients drive over stdin/stdout:
`python -m minidb` reads SQL statements and answers each one with a JSON line. The wire protocol
is already implemented in `minidb/protocol.py`; the engine behind it (`minidb/engine.py`) is a
stub that rejects every statement. Your job is to build the engine.

The work is organised as a ladder of twelve tiers. Each tier builds on the ones before it, so work
through them in order, and make each tier solid before you start the next: a bug in an early tier
will surface again in every later one. This brief is the specification. Where it says something
is an error, return exactly the error type it names.

Work on your own, without asking questions. Keep `python -m pytest` green. Add tests for every
tier as you go (the existing tests in `tests/` show the style), and commit to git with clear
messages at least once per tier. When all tiers are done, keep improving correctness, test
coverage and code quality while time remains. Organise the code however you like; a lexer, a
parser producing an AST, and an executor in separate modules is a reasonable start.

## 0. Protocol recap and general rules

- `minidb/protocol.py` splits stdin into statements, calls `Engine.execute(sql)` once per
  statement, and writes the JSON line. Results are dicts: `{"columns": [...], "rows": [[...]]}`
  for queries (`SELECT`, `EXPLAIN`), `{"rowcount": n}` for `INSERT`/`UPDATE`/`DELETE`, and `{}`
  for everything else. Errors are raised as the `DBError` subclasses in `minidb/protocol.py`.
- Error types (the `"type"` field): `SyntaxError` (malformed or unsupported SQL), `NameError`
  (unknown, duplicate or ambiguous table/column/index/view names), `TypeError` (values or
  operands of the wrong type), `ConstraintError` (PRIMARY KEY, UNIQUE, NOT NULL violations),
  `TransactionError` (transaction control used in the wrong state), `RuntimeError` (errors while
  evaluating, such as division by zero), `IOError` (SAVE/LOAD file problems). Error messages are
  free text but should be helpful. `InternalError` must never occur.
- **Statement atomicity.** A statement that fails has no effect at all: no rows inserted,
  updated or deleted, no schema change. This holds for every statement in every tier.
- **When errors are detected.** `SyntaxError` and `NameError` are detected before any row is
  processed, so they are reported even when the tables involved are empty. `TypeError` and
  `RuntimeError` must be reported at least whenever the offending operation is actually evaluated
  on non-NULL values.
- **Row order.** A table keeps its rows in insertion order. `UPDATE` does not move a row; a
  deleted row is gone, and new rows go to the end. Whenever a result's order is not fully decided
  by `ORDER BY`, rows come out in the order defined in the tier that introduces the construct.
  Indexes, transactions and persistence must never change any result, including its row order.
- **Names.** Keywords and identifiers are case-insensitive. Identifiers match
  `[A-Za-z_][A-Za-z0-9_]*` and are stored and reported in lower case: after
  `CREATE TABLE Users (Name TEXT)`, the table is `users` and `SELECT * FROM USERS` reports the
  column `name`. Reserved words cannot be used as identifiers: `SELECT FROM WHERE AND OR NOT NULL
  TRUE FALSE IS IN LIKE BETWEEN AS ORDER BY ASC DESC LIMIT OFFSET DISTINCT GROUP HAVING INSERT INTO
  VALUES UPDATE SET DELETE CREATE DROP TABLE INDEX VIEW UNIQUE PRIMARY KEY DEFAULT ON JOIN INNER
  LEFT OUTER CROSS EXISTS BEGIN COMMIT ROLLBACK EXPLAIN SAVE LOAD ALTER ADD COLUMN`. Type names
  and function names are not reserved.

## Tier 1. Foundations: tables, INSERT, SELECT *

- Lexer and parser for the statements below. Anything that does not parse is a `SyntaxError`.
- Literals: integers (`42`), reals (`3.25`: digits, a dot, digits), strings in single quotes
  (`'it''s'`), `TRUE`, `FALSE`, `NULL`. Negative numbers are written with unary minus (`-5`).
  An integer literal outside the 64-bit signed range is a `SyntaxError`.
- Types: `INTEGER` (alias `INT`), `REAL`, `TEXT`, `BOOLEAN` (alias `BOOL`). Any other type name is
  a `SyntaxError`. INTEGER values are 64-bit signed integers; REAL values are double-precision
  floats.
- `CREATE TABLE name (col type, ...)`: at least one column. Creating a table (or, from tier 12,
  a view) whose name already exists, or a table with two columns of the same name, is a
  `NameError`.
- `DROP TABLE name`: removes the table and its data (and, from tier 7, its indexes). Unknown
  table: `NameError`.
- `INSERT INTO name [(col, ...)] VALUES (expr, ...)[, (expr, ...) ...]`: inserts one row per
  tuple, in order, and returns `{"rowcount": n}`. Without a column list, each tuple gives a value
  for every column in declaration order. With a column list, the columns not listed get NULL
  (from tier 5: their DEFAULT). A tuple with the wrong number of values is a `SyntaxError`. An
  unknown column or table is a `NameError`; a column listed twice is a `SyntaxError`. Value
  expressions may use any operator from tier 2 but no column references.
- `SELECT * FROM name`: all columns in declaration order, all rows in table order. A query on an
  empty table returns its columns and `"rows": []`.

## Tier 2. Expressions and filtering

- `SELECT expr [AS alias], ... [FROM table [WHERE condition]]`. Without `FROM`, the select list
  is evaluated once and gives exactly one row (no other clauses are allowed without `FROM`).
- Output column names: an alias if given (`AS` is required for column aliases); else, for a
  column reference (`col` or `t.col`), the column's name; else, for a function or aggregate
  call, the function name in lower case (`count`, `lower`); else `?column?`.
- Operators, from lowest to highest precedence:
  1. `OR`
  2. `AND`
  3. `NOT`
  4. comparisons `=  <>  !=  <  <=  >  >=`, `IS [NOT] NULL`, `[NOT] BETWEEN a AND b`,
     `[NOT] IN (expr, ...)`, `[NOT] LIKE` (non-associative: `a < b < c` is a `SyntaxError`)
  5. `||` (string concatenation)
  6. `+  -`
  7. `*  /  %`
  8. unary `-` and `+`

  Binary operators of equal precedence associate to the left (`10 - 3 - 2` is `5`). Parentheses
  group.
- NULL: every operator except `IS [NOT] NULL`, `AND` and `OR` returns NULL when an operand is NULL
  (no type check is done against a NULL). `AND`/`OR`/`NOT` use three-valued logic: `FALSE AND
  NULL` is FALSE, `TRUE AND NULL` is NULL, `TRUE OR NULL` is TRUE, `FALSE OR NULL` is NULL,
  `NOT NULL` is NULL. `x IS NULL` / `x IS NOT NULL` are always TRUE or FALSE.
- Arithmetic `+ - * / %` takes INTEGER or REAL operands. INTEGER op INTEGER gives INTEGER;
  otherwise the result is REAL. Integer `/` truncates toward zero (`-7 / 2` is `-3`) and integer
  `%` takes the sign of the dividend (`-7 % 2` is `-1`); `%` with a REAL operand is a `TypeError`.
  Division or modulo by zero (`0` or `0.0`) is a `RuntimeError`, and so is an INTEGER result
  outside the 64-bit signed range. Unary minus negates a number.
- `a || b`: both TEXT, result TEXT.
- Comparisons: two numbers (INTEGER and REAL compare by value, `1 = 1.0` is TRUE), two TEXT values
  (by Unicode code point, case-sensitive: `'B' < 'a'`), or two BOOLEANs (`FALSE < TRUE`). The
  result is BOOLEAN.
- `x BETWEEN a AND b` means `x >= a AND x <= b`; `x IN (a, b, ...)` means `x = a OR x = b OR ...`
  (so `1 IN (2, NULL)` is NULL); `NOT BETWEEN` and `NOT IN` are the negations of those.
- `x LIKE pattern`: both TEXT; `%` matches any sequence of characters (also empty), `_` exactly
  one character, everything else matches itself, case-sensitively, and the whole string must
  match. There is no escape character.
- `AND`, `OR`, `NOT` take BOOLEAN (or NULL) operands.
- Any other combination of operand types (e.g. `1 + 'a'`, `'a' || 1`, `1 = 'a'`, `TRUE + 1`,
  `NOT 5`, `1 = TRUE`) is a `TypeError`.
- `WHERE condition` keeps the rows where the condition is TRUE (not FALSE, not NULL). A condition
  that evaluates to a non-BOOLEAN, non-NULL value is a `TypeError`. Unknown columns are a
  `NameError`.
- `SELECT *` may be combined with other items (`SELECT *, a + 1 AS b FROM t`).
- Rows of a single-table query come out in table order.

## Tier 3. Shaping results: ORDER BY, LIMIT, DISTINCT, scalar functions

- Clause order: `SELECT [DISTINCT] ... FROM ... [WHERE ...] [ORDER BY ...] [LIMIT n [OFFSET m]]`
  (tier 6 adds `GROUP BY`/`HAVING` before `ORDER BY`).
- `ORDER BY item [ASC | DESC], ...` (default `ASC`): sort by the first item, break ties with the
  next. Rows that tie on every item keep the order they would have had without `ORDER BY` (the
  sort is stable). NULL sorts before every non-NULL value in ascending order and after every
  non-NULL value in descending order. Sorting values of incomparable types is a `TypeError`.
- An `ORDER BY` item that is an integer literal `k` means the k-th output column (1-based; out of
  range is a `SyntaxError`). A bare identifier that equals the name of exactly one output column
  means that output column (so aliases can be used); if it equals the name of several output
  columns, it is a `NameError`. Any other item is an expression over the input row and may use
  columns that are not in the select list. With `DISTINCT`, `ORDER BY` may only refer to output
  columns (by name or position); anything else is a `SyntaxError`.
- `LIMIT n [OFFSET m]`: `n` and `m` are non-negative integer literals. Skip `m` rows, then return
  at most `n`. Applied last, after `ORDER BY`.
- `DISTINCT`: remove duplicate output rows (two NULLs count as equal here), keeping the first
  occurrence. It applies before `ORDER BY` and `LIMIT`.
- Scalar functions (names case-insensitive; an unknown function is a `NameError`, a wrong number
  of arguments a `SyntaxError`, a wrong argument type a `TypeError`; NULL arguments give NULL,
  except for `COALESCE`):
  - `LOWER(text)`, `UPPER(text)`: TEXT.
  - `LENGTH(text)`: INTEGER, the number of characters.
  - `ABS(number)`: same type as the argument.
  - `COALESCE(a, b, ...)`: one or more arguments; the first that is not NULL, else NULL.

## Tier 4. UPDATE and DELETE

- `UPDATE name SET col = expr [, col = expr ...] [WHERE condition]` and
  `DELETE FROM name [WHERE condition]`, both returning `{"rowcount": n}`: the number of rows the
  `WHERE` selected (all rows without `WHERE`), whether or not values actually changed.
- Every expression in an `UPDATE` (each `SET` value and the `WHERE` condition) is evaluated
  against the row as it was before the statement: `UPDATE t SET a = b, b = a` swaps the two
  columns. A `DELETE` decides which rows to delete before deleting any of them.
- Assigning an unknown column is a `NameError`; assigning the same column twice in one `UPDATE` is
  a `SyntaxError`.
- Remember statement atomicity: an `UPDATE` that fails on its tenth row has changed nothing.

## Tier 5. Types and constraints

- Column definition: `col type [PRIMARY KEY] [NOT NULL] [UNIQUE] [DEFAULT literal]`, the
  constraint clauses in any order, each at most once. At most one column per table may be the
  `PRIMARY KEY` (a second one is a `SyntaxError`). `PRIMARY KEY` implies `NOT NULL` and `UNIQUE`.
- Storing values (INSERT, UPDATE, DEFAULT, and from tier 12 ALTER TABLE): NULL fits every column
  type. Otherwise an INTEGER column takes only INTEGER values; a REAL column takes REAL values and
  INTEGER values, which are stored as REAL (`3` is stored and returned as `3.0`); a TEXT column
  takes only TEXT; a BOOLEAN column takes only BOOLEAN. Anything else is a `TypeError`. No other
  conversions happen (`'5'` cannot be stored in an INTEGER column).
- `DEFAULT literal`: the literal may be a number (with optional leading `-`), a string, `TRUE`,
  `FALSE` or `NULL`, and must fit the column type (else `TypeError` at `CREATE TABLE`). A column
  that is not given a value on `INSERT` gets its default, or NULL if it has none.
- `NOT NULL`: storing NULL is a `ConstraintError`, including by omitting a NOT NULL column that has
  no default.
- `UNIQUE`: no two rows may have equal non-NULL values in the column (any number of NULLs is
  fine). Equality is the `=` of tier 2. A violation is a `ConstraintError`.
- Constraints are checked against the state at the end of the statement: a multi-row `INSERT`
  whose rows collide with each other fails as a whole, and `UPDATE t SET id = id + 1` succeeds on
  a primary key `1, 2, 3` because the final values are distinct.

## Tier 6. Aggregation: aggregates, GROUP BY, HAVING

- Aggregates: `COUNT(*)`, `COUNT(expr)`, `COUNT(DISTINCT expr)`, `SUM(expr)`, `AVG(expr)`,
  `MIN(expr)`, `MAX(expr)`.
  - All except `COUNT(*)` ignore NULL inputs. `COUNT(*)` counts rows; `COUNT(expr)` counts
    non-NULL values; `COUNT(DISTINCT expr)` counts distinct non-NULL values. Counts are INTEGER and
    are 0 for no input.
  - `SUM`: numbers only (else `TypeError`); INTEGER if every input is INTEGER (overflow is a
    `RuntimeError`), else REAL; NULL when there are no non-NULL inputs.
  - `AVG`: numbers only; always REAL; NULL when there are no non-NULL inputs.
  - `MIN`/`MAX`: numbers, TEXT or BOOLEAN, ordered as in tier 2; NULL when there are no non-NULL
    inputs.
- Clause order: `SELECT ... FROM ... [WHERE ...] [GROUP BY col, ...] [HAVING condition]
  [ORDER BY ...] [LIMIT ...]`. `GROUP BY` items are column references (`col` or `t.col`).
- Rows with equal values in all grouping columns form one group; NULLs group together. Without
  `ORDER BY`, groups come out in the order of their first row.
- A query is *grouped* if it has `GROUP BY`, or an aggregate in its select list, `HAVING` or
  `ORDER BY`. In a grouped query's select list, `HAVING` and `ORDER BY`, every reference to a
  column of the query's own `FROM` tables that is not inside an aggregate's argument must be a
  grouping column, else `SyntaxError` (references to an enclosing query's columns, tier 9, are
  fine). A grouped query without `GROUP BY` forms exactly one
  group from all rows, so it returns one row even on an empty table.
- `HAVING condition` filters groups like `WHERE` filters rows. It may use aggregates that are not
  in the select list. `ORDER BY` in a grouped query may use output names, positions, grouping
  columns and aggregates.
- Aggregates in `WHERE`, in `GROUP BY`, or nested inside another aggregate are a `SyntaxError`.

## Tier 7. Secondary indexes and EXPLAIN

- `CREATE [UNIQUE] INDEX name ON table (col)`: an ordered index on one column, usable for
  equality and range lookups. `DROP INDEX name`. Index names have their own namespace (an index
  may share a name with a table). A duplicate index name, an unknown index, table or column, or
  an index on a view is a `NameError`. `CREATE UNIQUE INDEX` also enforces uniqueness on the
  column exactly like the `UNIQUE` constraint, and fails with `ConstraintError` if the existing
  rows already have duplicates. Several indexes on the same column are allowed.
- Indexes must stay correct through every `INSERT`, `UPDATE`, `DELETE` (and from tier 10,
  `ROLLBACK`). Remember that results never depend on whether an index is used: a lookup through
  an index returns exactly the rows a full scan would, in the same order.
- `EXPLAIN select-statement` does not run the query; it validates it (unknown names are still a
  `NameError`) and returns the plan: columns `["plan"]`, one row per table reference in the
  outer query's `FROM` clause, in `FROM` order. Subqueries do not add rows. `EXPLAIN` of anything
  other than a `SELECT` is a `SyntaxError`.
- Plan rules. Only the first table reference of the `FROM` clause can use an index; every other
  table reference reports `SCAN <table>`. For the first one, consider the top-level `AND`-ed
  conjuncts of `WHERE` (a top-level `OR` gives no conjuncts). A conjunct is *usable* if it has
  the form `col op literal` or `literal op col` with `op` one of `= < <= > >=`, or
  `col BETWEEN literal AND literal`, where `col` is a column of that table that has an index,
  and a literal is a number (optionally with leading `-`), a string, `TRUE` or `FALSE` (not
  `NULL`). Then:
  1. if some usable conjunct uses `=`, take the leftmost such conjunct and report
     `SEARCH <table> USING INDEX <index> (<col> = ?)`;
  2. else, if there is any usable conjunct, take the leftmost and report
     `SEARCH <table> USING INDEX <index> (<col> RANGE)`;
  3. else report `SCAN <table>`.

  `<table>` is the table's name (not its alias). If the column has several indexes, `<index>` is
  the one that was created first. For example, with an index `idx_age` on `people(age)`,
  `EXPLAIN SELECT * FROM people WHERE name = 'x' AND age > 30` returns
  `{"ok": true, "columns": ["plan"], "rows": [["SEARCH people USING INDEX idx_age (age RANGE)"]]}`.
  A query whose plan says `SEARCH` must actually use that index.

## Tier 8. Joins

- `FROM t1 [[AS] a1] { [INNER] JOIN t2 [[AS] a2] ON condition | LEFT [OUTER] JOIN t2 [[AS] a2] ON
  condition | CROSS JOIN t2 [[AS] a2] } ...`. Joins are processed left to right.
- Each table reference has an *exposed name*: its alias if it has one, else the table name. Two
  references with the same exposed name in one `FROM` are a `NameError` (a self-join needs
  aliases). Once a table has an alias, its table name cannot be used to qualify columns.
- `x.col` refers to column `col` of the reference exposed as `x`. A bare `col` must belong to
  exactly one table reference in the `FROM` clause: none is a `NameError` (or, from tier 9, a
  reference to an outer query), more than one is a `NameError` (ambiguous). `x.*` in the select
  list expands to the columns of `x`; `*` expands to the columns of every table reference in
  `FROM` order. Output names are unqualified, so a result may have duplicate column names.
- `INNER JOIN` keeps the pairs for which the `ON` condition is TRUE. `LEFT JOIN` also keeps every
  left row that has no such partner, with NULL for all columns of the right table. `CROSS JOIN`
  keeps every pair.
- Without `ORDER BY`, rows come out in nested-loop order: for each row of the left side (in its
  own order), its matching right rows in table order.
- `WHERE`, `GROUP BY`, `HAVING`, `ORDER BY`, `DISTINCT` and aggregates all work on joined rows.

## Tier 9. Subqueries

- A subquery is a parenthesised `SELECT` (with any clauses, including `ORDER BY` and `LIMIT`). It
  may appear wherever an expression is allowed except in `DEFAULT`, including in `UPDATE`'s `SET`
  and `WHERE` and in `DELETE`'s `WHERE`.
  - Scalar subquery `(SELECT ...)`: must have exactly one column (else `SyntaxError`). Its value
    is the single row's value, NULL if it returns no rows; more than one row is a `RuntimeError`.
  - `x [NOT] IN (SELECT ...)`: exactly one column (else `SyntaxError`). Same semantics as the
    tier 2 `IN` list over the subquery's values: with no rows `IN` is FALSE, and if the values
    contain a NULL, `x NOT IN (...)` is never TRUE.
  - `[NOT] EXISTS (SELECT ...)`: TRUE if the subquery returns at least one row; never NULL.
- Correlated subqueries: a subquery may reference columns of enclosing queries. A name is
  resolved in the innermost query that has a matching column; only if none matches in that query
  does resolution move one level out. A correlated subquery is evaluated for every outer row.
- In `UPDATE` and `DELETE`, the target table is a table reference exposed under its own name: its
  columns can be written `col` or `table.col`, and subqueries can correlate with them. Subqueries
  in `UPDATE` and `DELETE` see the table as it was before the statement (tier 4).

## Tier 10. Transactions

- `BEGIN` (optionally `BEGIN TRANSACTION`) starts a transaction, `COMMIT` makes its changes
  permanent, `ROLLBACK` undoes all of them. Outside a transaction every statement takes effect
  immediately.
- A transaction covers everything: rows (including their order), tables and indexes created or
  dropped, and from tier 12 views and added columns. After `ROLLBACK`, the database is exactly
  as it was at `BEGIN`, including every index lookup and plan.
- `BEGIN` inside a transaction, and `COMMIT` or `ROLLBACK` outside one, are a `TransactionError`;
  the transaction state does not change.
- A failing statement inside a transaction has no effect (statement atomicity) and does not end
  or spoil the transaction: later statements and `COMMIT` work normally.
- A transaction still open at end of input is rolled back.

## Tier 11. Persistence: SAVE and LOAD

- `SAVE 'path'` writes the complete database to the file `path` (relative paths are relative to
  the process's working directory), replacing any existing file: every table with its columns,
  types, constraints and defaults, all rows in order, all indexes, and from tier 12 all views.
  The file is UTF-8 JSON; its structure is up to you.
- `LOAD 'path'` replaces the entire current database with the one saved in `path`. Afterwards the
  database behaves exactly as the saved one did: same query results and row order, constraints
  still enforced, indexes present (and used by `EXPLAIN`), views still working.
- A file that cannot be written, cannot be read, or does not contain a database saved by `SAVE`
  is an `IOError`, and the current database is unchanged.
- `SAVE` and `LOAD` inside a transaction are a `TransactionError`.

## Tier 12. Schema evolution: views and ALTER TABLE

- `CREATE VIEW name AS select-statement`: a named query. Tables and views share one namespace
  (a clash is a `NameError`). The query is checked when the view is created (unknown names are a
  `NameError`) and is re-run every time the view is used, so a view always reflects the current
  data, and `SELECT *` in a view picks up columns added later. A view can be used wherever a table
  can appear in a `FROM` clause, including joins and subqueries; its column names are the
  query's output names, and its rows come in the order the query returns them (its "table
  order"). `EXPLAIN` reports a view as `SCAN <view>`.
- `DROP VIEW name`. `DROP VIEW` on a table and `DROP TABLE` on a view are a `NameError`. Dropping a
  table that a view uses is allowed; using the view afterwards is a `NameError`. `INSERT`,
  `UPDATE`, `DELETE` and `CREATE INDEX` on a view are a `NameError`.
- `ALTER TABLE name ADD [COLUMN] col type [NOT NULL] [DEFAULT literal]`: appends a column. Existing
  rows get the default (or NULL). Adding a `NOT NULL` column without a default to a table that has
  rows is a `ConstraintError`. `PRIMARY KEY` or `UNIQUE` here is a `SyntaxError`; an existing
  column name is a `NameError`.
- Views and added columns take part in transactions (tier 10) and in `SAVE`/`LOAD` (tier 11).
