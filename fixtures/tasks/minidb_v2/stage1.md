**Message from the product owner — stage 1: richer queries**

New requirements. Our first client wants to write real reporting queries against minidb, so the
engine needs subqueries, conditional expressions, casts, set operations, `INSERT ... SELECT` and
derived tables. Everything in the stage 0 brief still applies unless this message says
otherwise. As before: add tests, keep `python -m pytest` green, and commit at least once per
section. The section numbers continue those of the stage 0 brief.

**Reserved words.** The following words become reserved (they can no longer be identifiers):
`CASE WHEN THEN ELSE END CAST UNION INTERSECT EXCEPT ALL`. The word `IF` stays unreserved.

## 8. Subqueries

- A subquery is a parenthesised query (a `SELECT` with any of its clauses, including `ORDER BY`
  and `LIMIT`, or a set operation from section 10). It may appear wherever an expression is
  allowed except in `DEFAULT` and `GROUP BY`: in select lists, `WHERE`, `ON`, `HAVING`,
  `ORDER BY`, in `INSERT ... VALUES`, and in `UPDATE`'s `SET` and `WHERE` and `DELETE`'s `WHERE`.
  - Scalar subquery `(SELECT ...)`: must have exactly one column (else `SyntaxError`). Its value
    is the single row's value, NULL if it returns no rows; more than one row is a `RuntimeError`.
    Its output name is `?column?`.
  - `x [NOT] IN (SELECT ...)`: exactly one column (else `SyntaxError`). Same semantics as the
    `IN` list of section 2 over the subquery's values: with no rows `IN` is FALSE, and if the
    values contain a NULL, `x NOT IN (...)` is never TRUE.
  - `[NOT] EXISTS (SELECT ...)`: TRUE if the subquery returns at least one row; never NULL. The
    subquery may have any number of columns. The output name of an `EXISTS` item is `exists`;
    `NOT EXISTS (...)` is the operator `NOT` applied to it, so its output name is `?column?`.
- Correlated subqueries: a subquery may reference columns of enclosing queries. A name (bare
  `col` or qualified `x.col`) is resolved in the innermost query that has a matching column (for
  `x.col`: a table reference exposed as `x` that has that column); only if none matches in that
  query does resolution move one level out. If the innermost match is ambiguous, it is a
  `NameError` even if an outer query would match uniquely.
- Evaluation: a correlated subquery is evaluated each time the expression containing it is
  evaluated (the short-circuit rules of section 0 apply). A subquery that is not correlated is
  evaluated at most once per statement, the first time its value is needed; if it is never needed
  (for example, because the outer table is empty), it is not evaluated and cannot cause an error.
- An aggregate belongs to the query in whose select list, `HAVING` or `ORDER BY` it is written,
  even when its argument refers only to columns of an enclosing query.
- When a subquery appears in the select list, `HAVING` or `ORDER BY` of a grouped query (section
  6), the grouping rule extends into it: every reference from the subquery to a column of the
  grouped query must be a grouping column, else `SyntaxError`.
- In `UPDATE` and `DELETE`, the target table is a table reference exposed under its own name: its
  columns can be written `col` or `table.col`, and subqueries can correlate with them. Subqueries
  in `UPDATE` and `DELETE` see the table as it was before the statement (section 4).

## 9. CASE, CAST and more scalar functions

- Searched `CASE WHEN cond THEN result [WHEN cond THEN result ...] [ELSE result] END`: the result
  of the first `WHEN` whose condition is TRUE, else the `ELSE` result, else NULL. Conditions must
  be BOOLEAN or NULL (else `TypeError`). The conditions are evaluated in order until one is TRUE;
  then only that branch's result is evaluated. Nothing else is evaluated, so other branches cannot
  cause errors.
- Simple `CASE operand WHEN value THEN result ... [ELSE result] END`: the operand is evaluated
  once, then compared with `=` to each `WHEN` value in order (each evaluated only when it is
  reached) until one comparison is TRUE; NULL never matches. Comparing incomparable types is a
  `TypeError` when that comparison is made.
- The results of different branches are not type-checked against each other: a `CASE` may
  return an INTEGER for one row and a TEXT for another. The output name of a `CASE` item is
  `case`. Aggregates may appear inside `CASE` in a grouped query.
- `CAST(expr AS type)`, with the type names of section 1 (unknown type: `SyntaxError`); output
  name `cast`. NULL stays NULL, and a value of the target type is returned unchanged. Otherwise:

  | from \ to | INTEGER | REAL | TEXT | BOOLEAN |
  |---|---|---|---|---|
  | INTEGER | | nearest double | decimal digits, `-` if negative | `0` is FALSE, anything else TRUE |
  | REAL | truncated toward zero; `RuntimeError` if out of range | | see below | `TypeError` |
  | TEXT | see below | see below | | `'true'`/`'false'` in any case, else `RuntimeError` |
  | BOOLEAN | TRUE is `1`, FALSE `0` | `TypeError` | `'TRUE'` / `'FALSE'` | |

  - REAL to TEXT gives the shortest decimal string that reads back as the same double, as
    Python's `repr()` writes it: `2.5` gives `'2.5'`, `3.0` gives `'3.0'`, `0.1` gives `'0.1'`.
  - TEXT to INTEGER and TEXT to REAL first remove leading and trailing spaces (only the space
    character). TEXT to INTEGER then accepts an optional sign followed by digits; TEXT to REAL
    accepts an optional sign, digits, and optionally a dot followed by digits. Anything else, an
    INTEGER outside 64 bits, or a REAL that is not finite, is a `RuntimeError`. TEXT to BOOLEAN
    also ignores leading and trailing spaces.
- New scalar functions (the general rules of section 3 apply: NULL arguments give NULL, wrong
  types are a `TypeError`, wrong argument counts a `SyntaxError`):
  - `SUBSTR(text, start [, length])`: `start` and `length` are INTEGER. The result consists of
    the characters at the 1-based positions `p` with `start <= p < start + length` (no upper
    bound without `length`) that exist in the string: `SUBSTR('hello', 2, 3)` is `'ell'`,
    `SUBSTR('hello', 0, 2)` is `'h'`, `SUBSTR('hello', 9)` is `''`. A negative `length` is a
    `RuntimeError`.
  - `ROUND(number [, digits])`: `digits` is a non-negative INTEGER (default 0; negative is a
    `RuntimeError`). An INTEGER `number` is returned unchanged. A REAL `number` is rounded to
    `digits` decimal places, half away from zero, working on its decimal representation as
    `CAST(number AS TEXT)` gives it, and the result is REAL: `ROUND(2.675, 2)` is `2.68`,
    `ROUND(-0.5)` is `-1.0`.
  - `NULLIF(a, b)`: NULL if `a = b` is TRUE, else `a` (`TypeError` for incomparable non-NULL
    values). The general NULL rule does not apply here: `NULLIF('a', NULL)` is `'a'`.
  - `REPLACE(text, from, to)`: every non-overlapping occurrence of `from`, scanning left to
    right, replaced by `to`; an empty `from` returns `text` unchanged.
  - `TRIM(text)`: removes leading and trailing spaces (only the space character).

## 10. Set operations

- `query UNION [ALL] query`, `query INTERSECT query`, `query EXCEPT query`, where each operand is
  a `SELECT` without `ORDER BY` and `LIMIT` (in an operand they are a `SyntaxError`; operands
  cannot be parenthesised). `INTERSECT` binds tighter than `UNION` and `EXCEPT`, which have equal
  precedence and associate to the left. `INTERSECT ALL` and `EXCEPT ALL` are a `SyntaxError`.
- All operands must have the same number of columns (else `SyntaxError`). The result's column
  names are those of the first operand. Values are not type-checked across operands. Rows are
  duplicates under the rule of `DISTINCT` (section 3).
- Result order (before any `ORDER BY`): `A UNION ALL B` is the rows of `A` followed by those of
  `B`; `A UNION B` is the same with every row that duplicates an earlier one removed; `A INTERSECT
  B` is the rows of `A` that also occur in `B`, and `A EXCEPT B` the rows of `A` that do not occur
  in `B`, both without duplicates (first occurrences kept) and in the order of `A`.
- An `ORDER BY` and/or `LIMIT` after the last operand applies to the whole result. Its items must
  be output column positions or output column names (else `SyntaxError`; a name matching several
  output columns is a `NameError`).
- A set operation can be used wherever a `SELECT` can: as a statement, in subqueries, in
  `INSERT ... SELECT` and as a derived table.

## 11. INSERT ... SELECT, derived tables, IF [NOT] EXISTS

- `INSERT INTO name [(col, ...)] query`: inserts the query's rows, in the order the query returns
  them, and returns the number of rows inserted. The query must produce as many columns as are
  being filled (else `SyntaxError`). The query is evaluated completely before any row is inserted,
  so `INSERT INTO t SELECT * FROM t` doubles `t`. Then each row is stored exactly as a `VALUES`
  row would be (defaults, type rules, NOT NULL in the error order of section 1, UNIQUE and
  PRIMARY KEY after all rows).
- Derived tables: `FROM (query) [AS] alias`, in any table-reference position (first or joined).
  The alias is required (else `SyntaxError`) and is the reference's exposed name. Its columns are
  the query's output names; if several share a name, referring to that name is a `NameError`
  (`*` still works). Its rows are in the order the query returns them (its "table order"). The
  query of a derived table cannot see the other table references of the `FROM` clause it appears
  in; like any subquery, it may refer to columns of enclosing queries.
- `CREATE TABLE IF NOT EXISTS name (...)` does nothing (result `{}`) if a table with that name
  already exists; the column definitions are still parsed but not compared with the existing
  table. `DROP TABLE IF EXISTS name` does nothing if there is no such table.
