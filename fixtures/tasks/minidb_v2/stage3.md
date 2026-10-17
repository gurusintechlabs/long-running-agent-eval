**Message from the product owner — stage 3: change requests**

Change request. Our clients are porting queries from other databases, and three of our early
decisions turned out to be wrong for them. The changes below **replace** the corresponding rules
of the earlier briefs; existing behaviour that contradicts them must change, everywhere it
occurs (queries, subqueries, set operations, `INSERT ... SELECT`, derived tables, and every path
that stores values), and your own tests must be updated to match. Everything not mentioned here
stays as it is. Keep `python -m pytest` green and commit each change request separately.

## CR-1. NULL ordering and NULLS FIRST / NULLS LAST

- *Old rule (section 3):* NULL sorts before every non-NULL value in ascending order and after
  every non-NULL value in descending order.
- *New rule:* NULL sorts **after** every non-NULL value in ascending order and **before** every
  non-NULL value in descending order (NULL behaves as if it were larger than any value).
- New syntax: an `ORDER BY` item may end with `NULLS FIRST` or `NULLS LAST` (after `ASC` / `DESC`
  if present), which places the NULLs of that item explicitly, independently of the direction:
  `ORDER BY a DESC NULLS LAST`. The words `NULLS`, `FIRST` and `LAST` are not reserved.
- This applies to every `ORDER BY` (including those of set operations and subqueries). It does
  not change `MIN`/`MAX`, comparisons, `DISTINCT`, grouping, or which rows an index lookup finds.

## CR-2. Division

- *Old rule (section 2):* INTEGER `/` INTEGER gives an INTEGER, truncated toward zero.
- *New rule:* `/` always returns REAL. For two INTEGER operands the result is the exact quotient
  rounded once to a double: `7 / 2` is `3.5`, `-7 / 2` is `-3.5`, `4 / 2` is `2.0`. Division by
  zero is still a `RuntimeError`. The other arithmetic operators are unchanged, including `%`.
- Truncating integer division moves to a new scalar function `DIV(a, b)` (output name `div`):
  INTEGER arguments only (anything else non-NULL is a `TypeError`), NULL if an argument is NULL,
  truncates toward zero (`DIV(-7, 2)` is `-3`), and is a `RuntimeError` on division by zero or
  when the result does not fit in 64 bits (`DIV(-9223372036854775807 - 1, -1)`).
- `AVG` is unaffected.

## CR-3. Values that do not fit a column

- *Old rule (section 5):* storing a value that does not fit the column's type is a `TypeError`.
- *New rule:* it is a `ConstraintError` (a type constraint violation). This covers every place a
  value is stored: `INSERT ... VALUES`, `INSERT ... SELECT`, `UPDATE ... SET`, and a `DEFAULT`
  literal that does not fit its column at `CREATE TABLE`. The check keeps its place in the error
  order of sections 1 and 4 (after evaluating the row's values, before its NOT NULL checks).
- `TypeError` stays for everything that is not storing a value: operators, functions, `CAST`,
  conditions, sorting, aggregates.
