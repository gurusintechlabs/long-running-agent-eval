# minidb

A small in-memory SQL database engine, written in Python, driven over stdin/stdout.

## Running

    python -m minidb < script.sql

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

## Layout

- `minidb/protocol.py`: statement splitting, JSON encoding, the stdin/stdout loop, error classes.
- `minidb/engine.py`: `Engine.execute(sql) -> dict`, called once per statement.
- `minidb/lexer.py`: SQL text -> tokens (literals, keywords, identifiers, operators).
- `minidb/nodes.py`: AST node classes.
- `minidb/parser.py`: recursive-descent parser, tokens -> AST.
- `minidb/values.py`: SQL values, operators, type rules and storage coercion.
- `minidb/catalog.py`: tables (rows in insertion order, UNIQUE key sets) and the database.
- `minidb/compiler.py`: name binding and compilation of expressions into closures; aggregates.
- `minidb/executor.py`: statement execution (DDL, INSERT/UPDATE/DELETE, SELECT pipeline).
- `tests/`: the test suite.

## Tests

    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements.lock
    python -m pytest
