# minidb

A small in-memory SQL database engine, written in Python, driven over stdin/stdout.

## Running

    python -m minidb < script.sql

minidb needs Python 3.9 or later and only the standard library (the test suite's pinned pytest
needs Python 3.10 or later).

`python -m minidb` (run from the repository root) reads SQL statements from stdin and writes one
JSON line per statement to stdout. One process is one database session: the database starts
empty and lives until the process exits.

## Wire protocol

Input: SQL statements, each terminated by `;`.

- A `;` inside a single-quoted string literal does not end a statement; `''` inside a literal is
  an escaped single quote (`'it''s'`).
- `--` starts a comment that runs to the end of the line.
- Empty statements (`;;`) are skipped and produce no output. Text after the last `;` at end of
  input is executed as a final statement.

Output: for every statement, exactly one JSON line, flushed immediately:

| Statement | Output |
|---|---|
| query (`SELECT`, `EXPLAIN`) | `{"ok": true, "columns": ["a", "b"], "rows": [[1, "x"], [2, null]]}` |
| `INSERT` / `UPDATE` / `DELETE` | `{"ok": true, "rowcount": 2}` |
| anything else | `{"ok": true}` |
| error | `{"ok": false, "error": {"type": "NameError", "message": "no such table: t"}}` |

Values: INTEGER -> JSON integer, REAL -> JSON float, TEXT -> string, BOOLEAN -> `true`/`false`,
NULL -> `null`. After an error, processing continues with the next statement.

Error types, and the exception classes in `minidb/protocol.py` that produce them:

| Wire type | Class |
|---|---|
| `SyntaxError` | `SQLSyntaxError` |
| `NameError` | `SQLNameError` |
| `TypeError` | `SQLTypeError` |
| `ConstraintError` | `ConstraintError` |
| `TransactionError` | `TransactionError` |
| `RuntimeError` | `SQLRuntimeError` |
| `IOError` | `SQLIOError` |
| `NotImplementedError` | `NotSupportedError` |
| `InternalError` | any other exception (a bug) |

## SQL dialect (summary)

Statements:

- `CREATE TABLE [IF NOT EXISTS] t (col type [PRIMARY KEY] [NOT NULL] [UNIQUE] [DEFAULT literal], ...)`
  with types `INTEGER`/`INT`, `REAL`, `TEXT`, `BOOLEAN`/`BOOL`; `DROP TABLE [IF EXISTS] t`.
- `CREATE [UNIQUE] INDEX [IF NOT EXISTS] i ON t (col)`, `DROP INDEX [IF EXISTS] i`.
  `PRIMARY KEY` / `UNIQUE` columns get an implicit index `<table>_<column>_key`.
- `INSERT INTO t [(cols)] VALUES (...), ...` or `INSERT INTO t [(cols)] query`;
  `UPDATE t SET col = expr, ... [WHERE ...]`; `DELETE FROM t [WHERE ...]`.
- Queries: `SELECT [DISTINCT] ... FROM ... [WHERE] [GROUP BY] [HAVING] [ORDER BY] [LIMIT n
  [OFFSET m]]`, with `[INNER] JOIN`, `LEFT [OUTER] JOIN`, `CROSS JOIN`, derived tables
  `(query) AS alias`, `UNION [ALL]`, `INTERSECT`, `EXCEPT`, and scalar / `IN` / `EXISTS`
  subqueries (correlated or not).
- `EXPLAIN query` returns the access plan: one `SCAN` / `SEARCH ... USING INDEX` /
  `HASH JOIN` line per table reference.

Points worth knowing when porting queries:

- Values are strictly typed and never converted implicitly: `1 = 'a'` is a `TypeError`, and a
  value that does not fit a column is a `ConstraintError` (use `CAST(x AS type)`). INTEGER
  values are stored as REAL in REAL columns.
- `/` always returns REAL (`7 / 2` is `3.5`); `DIV(a, b)` is truncating integer division.
- NULL sorts as if larger than any value (last ascending, first descending); `ORDER BY` items
  accept `NULLS FIRST` / `NULLS LAST`.
- Scalar functions: `LOWER`, `UPPER`, `LENGTH`, `ABS`, `COALESCE`, `TYPEOF`, `SUBSTR`, `ROUND`,
  `NULLIF`, `REPLACE`, `TRIM`, `DIV`; expressions `CASE` (searched and simple) and `CAST`.
  Aggregates: `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, each also with `DISTINCT`.
- `LIKE` is case-sensitive with `%` and `_` and has no escape character.
- Results never depend on indexes or join strategy, including row order: without `ORDER BY`,
  rows come out in table (insertion) order, joins in nested-loop order.

## Layout

- `minidb/protocol.py`: statement splitting, JSON encoding, the stdin/stdout loop, error classes.
- `minidb/engine.py`: `Engine.execute(sql) -> dict`, called once per statement.
- `minidb/lexer.py`: SQL text -> tokens (literals, keywords, identifiers, operators).
- `minidb/nodes.py`: AST node classes.
- `minidb/parser.py`: recursive-descent parser, tokens -> AST.
- `minidb/values.py`: SQL values, operators, type rules and storage coercion.
- `minidb/catalog.py`: tables (rows keyed by increasing rowid, so iteration is table order),
  ordered indexes, UNIQUE key sets, and the database (table and index namespaces).
- `minidb/access.py`: access paths: index lookups for the first table reference and for
  UPDATE/DELETE, equi-join detection for index or hash probes (the plan rules of EXPLAIN).
- `minidb/functions.py`: scalar functions and CAST.
- `minidb/compiler.py`: name binding (including correlated references to enclosing queries) and
  compilation of expressions into closures; aggregates; subquery evaluation.
- `minidb/planner.py`: query plans: SELECT (joins, derived tables, grouping, sorting) and set
  operations.
- `minidb/executor.py`: statement execution (DDL, INSERT/UPDATE/DELETE, queries).
- `tests/`: the test suite.

## Benchmark

    python benchmarks/bench.py

runs every operation of the performance table (50,000-row indexed tables) against a running
`python -m minidb`, timing each statement from writing it to reading its JSON line, and prints
each result next to its limit. `tests/test_performance.py` runs it as part of the test suite.

## Tests

    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements.lock
    python -m pytest
