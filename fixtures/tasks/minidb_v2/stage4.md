**Message from the product owner — stage 4: transactions, durable storage, schema changes**

New requirements. minidb is going into production as an embedded store, so data must survive
restarts and crashes, clients need transactions, and schemas must be changeable without
recreating tables. Everything specified so far still applies, including the performance limits
of section 13 and the rule that nothing may change query results or their row order. This adds
the error type `TransactionError` (transaction control used in the wrong state) and `IOError`
(database file problems). Add tests, keep `python -m pytest` green, and commit at least once per
section.

## 15. Transactions

- `BEGIN [TRANSACTION]` starts a transaction, `COMMIT [TRANSACTION]` makes its changes permanent,
  `ROLLBACK [TRANSACTION]` undoes all of them. (`TRANSACTION` is not a reserved word.) Outside a
  transaction every statement takes effect immediately, as before.
- A transaction covers everything: rows (including their order), tables and indexes created or
  dropped, columns added or dropped (section 17), and the contents of every index. After
  `ROLLBACK`, the database is exactly as it was at `BEGIN`: same query results, same row order,
  same plans; rows inserted afterwards go to the end as usual.
- `BEGIN` inside a transaction, and `COMMIT` or `ROLLBACK` outside one, are a `TransactionError`;
  the transaction state does not change.
- A failing statement inside a transaction has no effect (statement atomicity) and does not end
  or spoil the transaction: later statements and `COMMIT` work normally.
- A transaction still open at the end of input is rolled back.
- Performance: the cost of `BEGIN`, `COMMIT` and `ROLLBACK` must not grow with the size of the
  database. On a database with a 50,000-row table, a transaction that changes a handful of rows
  must keep every statement in it, including `BEGIN`, `COMMIT` and `ROLLBACK`, within 5 ms on
  average (measured as in section 13). The limits of section 13 also hold inside transactions.

## 16. Durable storage

- `python -m minidb --db PATH` keeps the database in the file `PATH` (and, if you want, in other
  files whose names start with `PATH`, such as `PATH-wal`; nothing else). If `PATH` does not exist,
  minidb starts with an empty database and creates it. Without `--db`, minidb behaves as before:
  in memory, empty at start, gone at exit. `minidb/protocol.py` still constructs `Engine()`
  without arguments; handle the option in `minidb/__main__.py`.
- **Durability.** Once the JSON line of a successful statement executed outside a transaction,
  or of a successful `COMMIT`, has been written to stdout, its effects must survive the process
  being killed at any later moment (`SIGKILL`: no shutdown code runs) and must be visible when
  minidb is started again with the same `PATH`. Changes of a transaction that was not committed
  are gone after a restart, and so is every trace of failed statements. If the process is killed
  while a statement or a `COMMIT` is executing, then after a restart its effects are either
  completely present or completely absent. Surviving a power failure or an operating-system crash
  is not required (you do not need `fsync`).
- Everything is preserved across restarts: tables with their columns, types, constraints and
  defaults; all rows and their order; explicit and implicit indexes (plans stay the same). Rows
  inserted after a restart go after the existing ones.
- Errors: if `PATH` exists but is not a minidb database, or the files cannot be read or written
  (for example, `PATH` is in a directory that does not exist), minidb still starts and reads its
  input, but every statement fails with `IOError`, and existing files are left untouched. Running
  two processes on the same `PATH` at the same time is not supported.
- Performance, in `--db` mode:
  - The limits of section 13 still hold, except that single-row `INSERT`, `UPDATE` and `DELETE`
    statements outside a transaction on a 50,000-row table may take up to 5 ms on average (instead
    of 2 ms), so a statement must not rewrite the whole database.
  - `COMMIT` of a transaction that changed up to 1,000 rows takes at most 0.2 s.
  - Opening a database that holds a 50,000-row table, however many statements produced it,
    takes at most 2 s from process start until the first statement has been answered.

## 17. ALTER TABLE

- `ALTER TABLE name ADD [COLUMN] col type [NOT NULL] [DEFAULT literal]`: appends a column.
  Existing rows get the default (or NULL). Adding a `NOT NULL` column without a non-NULL default
  to a table that has rows is a `ConstraintError`. `PRIMARY KEY` or `UNIQUE` here is a
  `SyntaxError`; an unknown table or an existing column name is a `NameError`; a default that does
  not fit the type is a `ConstraintError` (as in CR-3).
- `ALTER TABLE name DROP [COLUMN] col`: removes the column and its values; every index on that
  column (explicit, or implicit for a `UNIQUE` column) is dropped with it. Dropping the
  `PRIMARY KEY` column, or the table's only column, is a `ConstraintError`; an unknown table or
  column is a `NameError`.
- Both take part in transactions (section 15) and are durable (section 16). `SELECT *` reflects the
  current columns.
