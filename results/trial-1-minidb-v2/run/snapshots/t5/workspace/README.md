# minidb

A small in-memory SQL database engine, written in Python, driven over stdin/stdout.

## Running

    python -m minidb < script.sql               # in memory
    python -m minidb --db PATH < script.sql     # kept in the file PATH

minidb needs Python 3.9 or later and only the standard library (the test suite's pinned pytest
needs Python 3.10 or later).

`python -m minidb` (run from the repository root) reads SQL statements from stdin and writes one
JSON line per statement to stdout. One process is one database session. Without `--db`, the
database starts empty and lives until the process exits. With `--db PATH`, it is kept in `PATH`
(plus `PATH-wal` and, briefly, `PATH-tmp`): every statement executed outside a transaction and
every `COMMIT` is durable once its answer has been written, even if the process is killed right
after. A transaction still open at the end of input is rolled back. Running two processes on
the same `PATH` at once is not supported.

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
- `BEGIN` / `COMMIT` / `ROLLBACK` `[TRANSACTION]`; `ALTER TABLE t ADD [COLUMN] col type [NOT NULL]
  [DEFAULT literal]` and `ALTER TABLE t DROP [COLUMN] col`.
- `CREATE VIEW [IF NOT EXISTS] v [(cols)] AS query`, `DROP VIEW [IF EXISTS] v`; views share the
  namespace of tables and re-run their query on every use.
- `WITH [RECURSIVE] name [(cols)] AS (query), ... query`, usable wherever a query is.
- Window functions `ROW_NUMBER`, `RANK`, `DENSE_RANK`, `LAG`, `LEAD` and the aggregates with
  `OVER ([PARTITION BY ...] [ORDER BY ...])`, in the select list and `ORDER BY`.
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
- `minidb/planner.py`: query plans: SELECT (joins, derived tables, views, grouping, window
  functions, sorting), set operations and WITH queries (including recursive ones).
- `minidb/windows.py`: window function evaluation (partitions, peers, running aggregates).
- `minidb/sorting.py`: the stable multi-key sort of ORDER BY and window ORDER BY.
- `minidb/executor.py`: statement execution (DDL, INSERT/UPDATE/DELETE, queries).
- `minidb/journal.py`: undo actions and redo operations of every change (transactions,
  statement atomicity, the durable log).
- `minidb/storage.py`: the database file: a snapshot plus a write-ahead log, recovery and
  checkpoints.
- `tests/`: the test suite.

## Benchmark

    python benchmarks/bench.py

runs every operation of the performance tables (50,000-row indexed tables) against a running
`python -m minidb`, timing each statement from writing it to reading its JSON line, and prints
each result next to its limit; `--db DIR` runs it with a database file (and adds the commit and
opening-time limits). `tests/test_performance.py` runs both as part of the test suite.

## Tests

    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements.lock
    python -m pytest
