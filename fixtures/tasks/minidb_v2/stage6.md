**Message from the product owner — stage 6: change request on names, and a DATE type**

Change request and one new feature. Our clients generate schemas from their application models
and complain that every name comes back in lower case; and almost every real table has dates in
it. The change request below **replaces** the naming rule of section 0 everywhere names are
reported; update your own tests to match. Everything not mentioned here stays as it is (CR-1 to
CR-3, performance limits, transactions, durable storage, views, `WITH`, window functions). Keep
`python -m pytest` green and commit the change request and the new feature separately.

## CR-4. Names keep their spelling

- *Old rule (section 0):* identifiers are stored and reported in lower case.
- *New rule:* identifiers are still matched case-insensitively (`users`, `USERS` and `Users` name
  the same table, and duplicates are still detected case-insensitively), but every name keeps the
  spelling it was given where it was defined, and is reported with that spelling:
  - a column reference's output name is the spelling of the column's definition (in
    `CREATE TABLE`, `ALTER TABLE ... ADD`, or a view's or `WITH` name's column list), not the
    spelling used in the query: after `CREATE TABLE Users (Name TEXT)`, `SELECT NAME FROM users`
    reports the column `Name`, and so does `SELECT *`;
  - an alias (`AS Total`) is reported as written; the columns of a view, derived table or `WITH`
    name are the output names of its query (or its column list), with their spellings;
  - plans report table, view, index, `WITH` and derived-table names and column names with the
    spelling of their definition (`SCAN Users`, `SEARCH Users USING INDEX Users_Age (Age = ?)`),
    and an implicit index is named from the defined spellings (`Users_Id_key`);
  - spellings are durable: they are the same after a restart with `--db`.
- Unchanged: keywords and function names are case-insensitive; the output name of a function
  call is still the function name in lower case (`count`, `row_number`), and `?column?`, `case`,
  `cast` and `exists` stay as they are. Data is unaffected: TEXT values keep comparing
  case-sensitively. `CREATE TABLE IF NOT EXISTS USERS (...)` on an existing `Users` does nothing
  and keeps the spelling `Users`.

## 22. The DATE type

- New column type `DATE` (not a reserved word). A DATE value is a calendar date between
  `0001-01-01` and `9999-12-31` (proleptic Gregorian calendar). On the wire it is a string
  `'YYYY-MM-DD'` (four-digit year), but inside minidb it is a type of its own: `TYPEOF` gives
  `'DATE'`, and a DATE is never equal or comparable to a TEXT.
- Literal: `DATE 'YYYY-MM-DD'` (the word `DATE` followed by a string literal), with exactly that
  shape and a valid date; anything else (`DATE '2023-02-29'`, `DATE '2023-1-5'`) is a
  `SyntaxError`. A `DEFAULT` may be a DATE literal.
- Comparisons (`= <> < <= > >=`, `BETWEEN`, `IN`) work between two DATEs, by calendar order; a
  DATE compared with any other type is a `TypeError`.
- Arithmetic: `DATE + INTEGER`, `INTEGER + DATE` and `DATE - INTEGER` give the DATE that many
  days later/earlier; `DATE - DATE` gives the INTEGER number of days between them
  (`DATE '2024-03-01' - DATE '2024-02-01'` is `29`). Any other arithmetic with a DATE (including
  unary minus) is a `TypeError`; a result outside the DATE range is a `RuntimeError`.
- Functions: `YEAR(d)`, `MONTH(d)`, `DAY(d)` return INTEGER parts of a DATE (`TypeError` for
  anything else). `CAST(text AS DATE)` accepts exactly `YYYY-MM-DD` of a valid date after
  removing leading and trailing spaces (anything else is a `RuntimeError`); `CAST(date AS TEXT)`
  gives `'YYYY-MM-DD'`. Casts between DATE and any other type are a `TypeError`. Text functions
  (`LOWER`, `LENGTH`, `SUBSTR`, `||`, `LIKE`, ...) and `ABS`/`ROUND` on a DATE are a `TypeError`.
- Storage: a DATE column accepts only DATE values (and NULL); anything else, including a TEXT
  that looks like a date, is a `ConstraintError` (CR-3), and so is storing a DATE in a column of
  another type.
- DATE values work everywhere values do: `ORDER BY`, `DISTINCT`, `GROUP BY`, set operations,
  joins (including hash joins), `MIN`/`MAX`/`COUNT` (`SUM` and `AVG` are a `TypeError`), window
  functions, views, `WITH` queries, `CASE`, transactions and durable storage (a DATE is still a
  DATE after a restart). DATE columns can be indexed, and a DATE literal is a literal for the plan
  rules of section 12.
