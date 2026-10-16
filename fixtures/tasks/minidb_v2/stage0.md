You are working in `minidb`, a small Python project in the current directory (see README.md). It
is meant to become a SQL database engine that clients drive over stdin/stdout:
`python -m minidb` reads SQL statements and answers each one with a JSON line. The wire protocol
is already implemented in `minidb/protocol.py`; the engine behind it (`minidb/engine.py`) is a
stub that rejects every statement. Your job is to build the engine.

This is a long project and the requirements arrive in stages. This brief is **stage 0: the core
engine**. While you work, the product owner will send further messages with new requirements
and change requests. Each one says precisely what is added or what changes; everything not
mentioned in a later message stays as specified here. Until a message changes it, this brief is
the specification. Where it says something is an error, return exactly the error type it names.

Work on your own, without asking questions. Keep `python -m pytest` green. Add tests for every
section as you go (the existing tests in `tests/` show the style), and commit to git with clear
messages at least once per section. Organise the code however you like; a lexer, a parser
producing an AST, and an executor in separate modules is a reasonable start. When everything in
this brief is done, keep improving correctness, test coverage and code quality while you wait for
the next message.

## 0. Protocol recap and general rules

- `minidb/protocol.py` splits stdin into statements, calls `Engine.execute(sql)` once per
  statement, and writes the JSON line. Results are dicts: `{"columns": [...], "rows": [[...]]}`
  for queries, `{"rowcount": n}` for `INSERT`/`UPDATE`/`DELETE`, and `{}` for everything else.
  Errors are raised as the `DBError` subclasses in `minidb/protocol.py`.
- Error types (the `"type"` field): `SyntaxError` (malformed or unsupported SQL), `NameError`
  (unknown, duplicate or ambiguous table/column names), `TypeError` (values or operands of the
  wrong type), `ConstraintError` (PRIMARY KEY, UNIQUE, NOT NULL violations), `RuntimeError`
  (errors while evaluating, such as division by zero). Later stages add `TransactionError` and
  `IOError`. Error messages are free text but should be helpful. `InternalError` must never occur.
- **Statement atomicity.** A statement that fails has no effect at all: no rows inserted,
  updated or deleted, no schema change. This holds for every statement, in every stage.
- **When errors are detected.** `SyntaxError` and `NameError` are detected before any row is
  processed, so they are reported even when the tables involved are empty. `TypeError` and
  `RuntimeError` are reported when the offending operation is evaluated on non-NULL operands.
  Operands are evaluated left to right, and every operand of an operator or function is evaluated
  before the operator is applied, except for these short-circuits: in `a AND b`, `b` is not
  evaluated when `a` is FALSE; in `a OR b`, `b` is not evaluated when `a` is TRUE; `COALESCE`
  stops at the first non-NULL argument. An operand that is not evaluated cannot cause an error
  (`SELECT FALSE AND 1 / 0 = 1` is FALSE). When a statement contains several errors, which one is
  reported is unspecified, except where this brief says otherwise.
- **Row order.** A table keeps its rows in insertion order. `UPDATE` does not move a row; a
  deleted row is gone, and new rows go to the end. Whenever a result's order is not fully decided
  by `ORDER BY`, rows come out in the order defined in the section that introduces the construct.
  Nothing added later (indexes, transactions, storage) may ever change a result, including its
  row order.
- **Names.** Keywords and identifiers are case-insensitive. Identifiers match
  `[A-Za-z_][A-Za-z0-9_]*` and are stored and reported in lower case: after
  `CREATE TABLE Users (Name TEXT)`, the table is `users` and `SELECT * FROM USERS` reports the
  column `name`. Reserved words cannot be used as identifiers (that is a `SyntaxError`):
  `SELECT FROM WHERE AND OR NOT NULL TRUE FALSE IS IN LIKE BETWEEN AS ORDER BY ASC DESC LIMIT
  OFFSET DISTINCT GROUP HAVING INSERT INTO VALUES UPDATE SET DELETE CREATE DROP TABLE INDEX VIEW
  UNIQUE PRIMARY KEY DEFAULT ON JOIN INNER LEFT RIGHT FULL OUTER CROSS EXISTS BEGIN COMMIT
  ROLLBACK EXPLAIN ALTER ADD COLUMN`. Type names and function names are not reserved.
- **Values on the wire.** INTEGER is a JSON integer, REAL a JSON float (always written with a
  decimal point or exponent, so `3.0` stays `3.0`), TEXT a string, BOOLEAN `true`/`false`, NULL
  `null`. Clients compare types strictly: `1`, `1.0` and `true` are three different answers.

## 1. Foundations: tables, INSERT, SELECT *

- Lexer and parser for the statements below. Anything that does not parse is a `SyntaxError`.
- Literals: integers (`42`), reals (`3.25`: digits, a dot, digits), strings in single quotes
  (`'it''s'`), `TRUE`, `FALSE`, `NULL`. There is no exponent notation, and `.5` and `5.` are not
  numbers (all three are `SyntaxError`). A number immediately followed by a letter or `_`
  (`12abc`) is a `SyntaxError`. Negative numbers are written with unary minus (`-5`).
- An integer literal outside the 64-bit signed range is a `SyntaxError`. This is decided on the
  literal itself, before any unary minus: `-9223372036854775808` is a `SyntaxError` (write
  `-9223372036854775807 - 1`). A REAL literal too large to be a finite double is a `SyntaxError`.
- Types: `INTEGER` (alias `INT`), `REAL`, `TEXT`, `BOOLEAN` (alias `BOOL`). Any other type name
  (for example `VARCHAR`) is a `SyntaxError`. INTEGER values are 64-bit signed integers; REAL
  values are finite double-precision floats.
- `CREATE TABLE name (col type, ...)`: at least one column. Creating a table whose name already
  exists, or a table with two columns of the same name, is a `NameError`.
- `DROP TABLE name`: removes the table and its data. Unknown table: `NameError`.
- `INSERT INTO name [(col, ...)] VALUES (expr, ...)[, (expr, ...) ...]`: inserts one row per
  tuple, in order, and returns `{"rowcount": n}`. Without a column list, each tuple gives a value
  for every column in declaration order. With a column list, the columns not listed get their
  DEFAULT (section 5), else NULL. A tuple with the wrong number of values is a `SyntaxError`. An
  unknown column or table is a `NameError`; a column listed twice is a `SyntaxError`. Value
  expressions may use any operator but no column references (a column name there is a
  `NameError`) and no aggregates (`SyntaxError`). The keyword `DEFAULT` is not a value
  (`VALUES (DEFAULT)` is a `SyntaxError`).
- **INSERT error order.** Rows are processed in order. For each row, its values are evaluated
  left to right, then each value is checked against its column type in the order the values are
  written (section 5), then the row's NOT NULL constraints are checked in column declaration
  order. The first error found this way is the one reported. UNIQUE and PRIMARY KEY constraints
  are checked only after every row has passed these checks.
- `SELECT * FROM name`: all columns in declaration order, all rows in table order. A query on an
  empty table returns its columns and `"rows": []`.

## 2. Expressions and filtering

- `SELECT expr [AS alias], ... [FROM table [WHERE condition]]`. Without `FROM`, the select list
  is evaluated once over a single empty input row and gives exactly one row; the only other
  clause allowed without `FROM` is `DISTINCT` (anything else, such as `WHERE` or `ORDER BY`, is a
  `SyntaxError`).
- Output column names: an alias if given (`AS` is required for column aliases); else, for a
  column reference (`col` or `t.col`, also when parenthesised), the column's name; else, for a
  function or aggregate call, the function name in lower case (`count`, `lower`); else
  `?column?`.
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
  (no type check is done against a NULL: `NULL + 'a'` is NULL). `AND`/`OR`/`NOT` use three-valued
  logic: `FALSE AND NULL` is FALSE, `TRUE AND NULL` is NULL, `TRUE OR NULL` is TRUE,
  `FALSE OR NULL` is NULL, `NOT NULL` is NULL. `x IS NULL` / `x IS NOT NULL` are always TRUE or
  FALSE.
- Arithmetic `+ - * / %` takes INTEGER or REAL operands. INTEGER op INTEGER gives INTEGER;
  otherwise the result is REAL. Integer `/` truncates toward zero (`-7 / 2` is `-3`) and integer
  `%` takes the sign of the dividend (`-7 % 2` is `-1`); `%` with a REAL operand is a `TypeError`.
  Division or modulo by zero (`0` or `0.0`) is a `RuntimeError`, and so is an INTEGER result
  outside the 64-bit signed range or a REAL result that is not finite. Unary minus negates a
  number; unary plus returns it unchanged; both are a `TypeError` on anything but a number.
- `a || b`: both TEXT, result TEXT.
- Comparisons: two numbers (INTEGER and REAL compare by value, `1 = 1.0` is TRUE), two TEXT values
  (by Unicode code point, case-sensitive: `'B' < 'a'`), or two BOOLEANs (`FALSE < TRUE`). The
  result is BOOLEAN.
- `x BETWEEN a AND b` means `x >= a AND x <= b`; `x IN (a, b, ...)` means `x = a OR x = b OR ...`
  (so `1 IN (2, NULL)` is NULL); `NOT BETWEEN` and `NOT IN` are the negations of those. All
  operands of `BETWEEN` and `IN` are evaluated.
- `x LIKE pattern`: both TEXT; `%` matches any sequence of characters (also empty), `_` exactly
  one character, everything else matches itself, case-sensitively, and the whole string must
  match. There is no escape character.
- `AND`, `OR`, `NOT` take BOOLEAN (or NULL) operands.
- Any other combination of operand types (e.g. `1 + 'a'`, `'a' || 1`, `1 = 'a'`, `TRUE + 1`,
  `NOT 5`, `1 = TRUE`) is a `TypeError`.
- `WHERE condition` keeps the rows where the condition is TRUE (not FALSE, not NULL). A condition
  that evaluates to a non-BOOLEAN, non-NULL value is a `TypeError`. Unknown columns are a
  `NameError`.
- `SELECT *` may be combined with other items (`SELECT *, a + 1 AS b FROM t`). Without `FROM`,
  `*` is a `SyntaxError`.
- Rows of a single-table query come out in table order.

## 3. Shaping results: ORDER BY, LIMIT, DISTINCT, scalar functions

- Clause order: `SELECT [DISTINCT] ... FROM ... [WHERE ...] [ORDER BY ...] [LIMIT n [OFFSET m]]`
  (section 6 adds `GROUP BY`/`HAVING` before `ORDER BY`).
- `ORDER BY item [ASC | DESC], ...` (default `ASC`): sort by the first item, break ties with the
  next. Rows that tie on every item keep the order they would have had without `ORDER BY` (the
  sort is stable). NULL sorts before every non-NULL value in ascending order and after every
  non-NULL value in descending order.
- An `ORDER BY` item that is a bare unsigned integer literal `k` means the k-th output column
  (1-based; `0` or more than the number of output columns is a `SyntaxError`). Any other constant
  (`-1`, `1 + 0`, `TRUE`, `'x'`) is an ordinary expression with the same value for every row. A
  bare identifier that equals the name of exactly one output column means that output column (so
  aliases can be used, and so can the column names produced by `*`); if it equals the name of
  several output columns, it is a `NameError`. Any other item is an expression over the input row
  and may use columns that are not in the select list. With `DISTINCT`, `ORDER BY` may only refer
  to output columns (by name or position); anything else is a `SyntaxError`.
- Sorting compares the values of one `ORDER BY` item across rows. If, among the rows being
  sorted, that item has two non-NULL values of incomparable types (say an INTEGER and a TEXT), the
  query is a `TypeError`, whatever the sort algorithm would actually compare. A sort of zero or
  one row never fails.
- `LIMIT n [OFFSET m]`: `n` and `m` are non-negative integer literals (anything else is a
  `SyntaxError`; `OFFSET` without `LIMIT` too). Skip `m` rows, then return at most `n`. Applied
  last, after `ORDER BY`.
- `DISTINCT`: remove duplicate output rows, keeping the first occurrence. Two values are
  duplicates when both are NULL or when `=` would give TRUE (so `1` and `1.0` are duplicates);
  values of incomparable types are simply different (no error). It applies before `ORDER BY` and
  `LIMIT`.
- Scalar functions (names case-insensitive; an unknown function is a `NameError`, a wrong number
  of arguments a `SyntaxError`, a wrong argument type a `TypeError`; NULL arguments give NULL,
  except for `COALESCE` and `TYPEOF`):
  - `LOWER(text)`, `UPPER(text)`: TEXT.
  - `LENGTH(text)`: INTEGER, the number of characters.
  - `ABS(number)`: same type as the argument (`ABS` of the smallest INTEGER is a `RuntimeError`).
  - `COALESCE(a, b, ...)`: one or more arguments; the first that is not NULL, else NULL.
  - `TYPEOF(x)`: the type of the value as TEXT: `'INTEGER'`, `'REAL'`, `'TEXT'`, `'BOOLEAN'` or
    `'NULL'`.

## 4. UPDATE and DELETE

- `UPDATE name SET col = expr [, col = expr ...] [WHERE condition]` and
  `DELETE FROM name [WHERE condition]`, both returning `{"rowcount": n}`: the number of rows the
  `WHERE` selected (all rows without `WHERE`), whether or not values actually changed.
- The target table cannot have an alias (`UPDATE t AS x ...` and `UPDATE t x ...` are a
  `SyntaxError`). Expressions may refer to its columns as `col` or `name.col`; a `SET` target is
  a bare column name (`SET t.a = 1` is a `SyntaxError`).
- Every expression in an `UPDATE` (each `SET` value and the `WHERE` condition) is evaluated
  against the row as it was before the statement: `UPDATE t SET a = b, b = a` swaps the two
  columns. A `DELETE` decides which rows to delete before deleting any of them.
- Assigning an unknown column is a `NameError`; assigning the same column twice in one `UPDATE` is
  a `SyntaxError`. Aggregates in `SET` or `WHERE` are a `SyntaxError`.
- **UPDATE error order.** Rows are processed in table order, exactly like `INSERT` rows: for each
  selected row, the `SET` values are evaluated left to right, then type-checked in the order of
  the assignments, then the row's NOT NULL constraints are checked in column order. UNIQUE and
  PRIMARY KEY are checked after every row has passed.
- Remember statement atomicity: an `UPDATE` that fails on its tenth row has changed nothing.

## 5. Types and constraints

- Column definition: `col type [PRIMARY KEY] [NOT NULL] [UNIQUE] [DEFAULT literal]`, the
  constraint clauses in any order, each at most once (a repeat is a `SyntaxError`). At most one
  column per table may be the `PRIMARY KEY` (a second one is a `SyntaxError`). `PRIMARY KEY`
  implies `NOT NULL` and `UNIQUE`.
- Storing values (INSERT and UPDATE): NULL fits every column type. Otherwise an INTEGER column
  takes only INTEGER values; a REAL column takes REAL values and INTEGER values, which are stored
  as REAL (`3` is stored and returned as `3.0`); a TEXT column takes only TEXT; a BOOLEAN column
  takes only BOOLEAN. Anything else is a `TypeError`. No other conversions happen (`'5'` cannot
  be stored in an INTEGER column).
- `DEFAULT literal`: the literal may be a number (with an optional leading `-`), a string,
  `TRUE`, `FALSE` or `NULL`, and must fit the column type by the rules above (else `TypeError` at
  `CREATE TABLE`). A column that is not given a value on `INSERT` gets its default, or NULL if it
  has none.
- `NOT NULL`: storing NULL is a `ConstraintError`, including by omitting a NOT NULL column that has
  no default (or whose default is NULL).
- `UNIQUE`: no two rows may have equal non-NULL values in the column (any number of NULLs is
  fine). Equality is the `=` of section 2. A violation is a `ConstraintError`.
- Constraints are checked against the state at the end of the statement: a multi-row `INSERT`
  whose rows collide with each other fails as a whole, and `UPDATE t SET id = id + 1` succeeds on
  a primary key `1, 2, 3` because the final values are distinct.

## 6. Aggregation: aggregates, GROUP BY, HAVING

- Aggregates: `COUNT(*)`, `COUNT(expr)`, `SUM(expr)`, `AVG(expr)`, `MIN(expr)`, `MAX(expr)`, and
  the same with `DISTINCT` before the argument (`COUNT(DISTINCT x)`, `SUM(DISTINCT x)`, ...),
  which first removes duplicate values (duplicates as for `DISTINCT` in section 3).
  - All except `COUNT(*)` ignore NULL inputs. `COUNT(*)` counts rows; `COUNT(expr)` counts
    non-NULL values. Counts are INTEGER and are 0 for no input.
  - `SUM`: numbers only (else `TypeError`); NULL when there are no non-NULL inputs. If every
    input is INTEGER the result is INTEGER, computed exactly: only the final total must fit in 64
    bits (else `RuntimeError`). Otherwise the result is REAL, computed by adding the values as
    doubles one by one, in input order, starting from `0.0`.
  - `AVG`: numbers only; always REAL; NULL when there are no non-NULL inputs. It is the `SUM`
    defined above divided by the number of non-NULL inputs (an all-INTEGER sum is converted to
    REAL by that division, with a single rounding).
  - `MIN`/`MAX`: numbers, TEXT or BOOLEAN, ordered as in section 2; two non-NULL inputs of
    incomparable types are a `TypeError`. Among equal values the first in input order is returned
    (so `MIN` over `1.0, 1` gives `1.0`). NULL when there are no non-NULL inputs.
  - The input order of an aggregate is the order of the rows after `WHERE` (table order, or the
    join order of section 7).
- Clause order: `SELECT ... FROM ... [WHERE ...] [GROUP BY col, ...] [HAVING condition]
  [ORDER BY ...] [LIMIT ...]`. `GROUP BY` items are column references (`col` or `t.col`);
  anything else, including a number, is a `SyntaxError`.
- Rows with equal values in all grouping columns form one group (equality as for `DISTINCT`;
  NULLs group together). A group reports the grouping values of its first row. Without
  `ORDER BY`, groups come out in the order of their first row.
- A query is *grouped* if it has `GROUP BY`, `HAVING`, or an aggregate in its select list or
  `ORDER BY`. In a grouped query's select list, `HAVING` and `ORDER BY`, every reference to a
  column of the query's `FROM` tables that is not inside an aggregate's argument must be a
  grouping column, else `SyntaxError`. `*` in a grouped query is a `SyntaxError`. A grouped query
  without `GROUP BY` forms exactly one group from all rows, so it returns one row even on an empty
  table. Without `FROM`, aggregates see the single empty row (`SELECT COUNT(*)` is `1`).
- `HAVING condition` filters groups like `WHERE` filters rows. It may use aggregates that are not
  in the select list. `ORDER BY` in a grouped query may use output names, positions, grouping
  columns and aggregates.
- Aggregates in `WHERE`, in `GROUP BY`, in a join's `ON`, or nested inside another aggregate are
  a `SyntaxError`.

## 7. Joins

- `FROM t1 [[AS] a1] { [INNER] JOIN t2 [[AS] a2] ON condition | LEFT [OUTER] JOIN t2 [[AS] a2] ON
  condition | CROSS JOIN t2 [[AS] a2] } ...`. Joins are processed left to right. `INNER`/`LEFT`
  joins require `ON`; `CROSS JOIN` must not have one. Comma-separated tables (`FROM a, b`),
  `RIGHT` and `FULL` joins are a `SyntaxError`.
- Each table reference has an *exposed name*: its alias if it has one, else the table name. Two
  references with the same exposed name in one `FROM` are a `NameError` (a self-join needs
  aliases). Once a table has an alias, its table name cannot be used to qualify columns.
- `x.col` refers to column `col` of the reference exposed as `x`. A bare `col` must belong to
  exactly one table reference in the `FROM` clause: none is a `NameError`, more than one is a
  `NameError` (ambiguous). `x.*` in the select list expands to the columns of `x`; `*` expands to
  the columns of every table reference in `FROM` order. Output names are unqualified, so a result
  may have duplicate column names.
- An `ON` condition may refer only to the table references joined so far, including the one it
  belongs to; a reference to a table joined later is a `NameError`.
- `INNER JOIN` keeps the pairs for which the `ON` condition is TRUE. `LEFT JOIN` also keeps every
  left row that has no such partner, with NULL for all columns of the right table. `CROSS JOIN`
  keeps every pair. A non-BOOLEAN, non-NULL `ON` result is a `TypeError`.
- Without `ORDER BY`, rows come out in nested-loop order: for each row of the left side (in its
  own order), its matching right rows in table order. The `ON` condition is evaluated in that
  order, for every pair (so `ON a.n = b.s`, with `a.n` INTEGER and `b.s` TEXT, is a `TypeError`
  as soon as both tables have a non-NULL value in those columns).
- `WHERE`, `GROUP BY`, `HAVING`, `ORDER BY`, `DISTINCT` and aggregates all work on joined rows.
