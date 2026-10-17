"""Stage 6 change request CR-4: names keep the spelling of their definition (matching stays
case-insensitive). Replaces test_t01_basics.py::test_names_are_case_insensitive_and_reported_lowercase.
"""
from _support import Session, assert_error, assert_rows, plan, run, run_ok, stage


@stage(6)
def test_names_keep_their_spelling():
    res = run_ok("""
        create table Users (Name TEXT, AGE int, eMail TEXT);
        InSeRt INTO USERS (name, Age, EMAIL) values ('Ann', 30, 'a@x');
        SELECT * FROM users;
        select NAME, users.age, USERS.EMAIL FROM USERS;
        SELECT u.name FROM Users AS U;
    """)
    assert_rows(res[2], [["Ann", 30, "a@x"]], columns=["Name", "AGE", "eMail"])
    assert_rows(res[3], [["Ann", 30, "a@x"]], columns=["Name", "AGE", "eMail"])
    assert_rows(res[4], [["Ann"]], columns=["Name"])


@stage(6)
def test_aliases_function_names_and_special_names():
    res = run_ok("""
        CREATE TABLE T (Id INTEGER, Val TEXT);
        INSERT INTO t VALUES (1, 'a'), (2, 'b');
        SELECT Val AS FullValue, COUNT(*) AS Total, LOWER(val), Count(*), MAX(ID) FROM t GROUP BY VAL;
        SELECT CASE WHEN id = 1 THEN 'x' END, CAST(ID AS TEXT), EXISTS (SELECT 1), -Id, (SELECT 1) FROM T WHERE id = 1;
        SELECT ROW_NUMBER() OVER (ORDER BY ID DESC) AS RowNo, Row_Number() OVER () FROM t ORDER BY rowno;
    """)
    assert res[2].columns == ["FullValue", "Total", "lower", "count", "max"]
    assert res[3].columns == ["case", "cast", "exists", "?column?", "?column?"]
    assert_rows(res[4], [[1, 2], [2, 1]], columns=["RowNo", "row_number"])


@stage(6)
def test_matching_and_duplicate_detection_stay_case_insensitive():
    res = run("""
        CREATE TABLE Mixed (a INTEGER, A TEXT);
        CREATE TABLE Mixed (Num INTEGER PRIMARY KEY, Note TEXT);
        CREATE TABLE MIXED (x INTEGER);
        CREATE TABLE IF NOT EXISTS mixed (x INTEGER);
        INSERT INTO MIXED (NUM, note) VALUES (2, 'b'), (1, 'a');
        SELECT NOTE AS Who FROM mixed ORDER BY who;
        SELECT num, COUNT(*) FROM Mixed GROUP BY NUM ORDER BY NUM DESC;
        SELECT Note AS N, Num AS n FROM mixed ORDER BY n;
        ALTER TABLE MIXED ADD COLUMN NOTE TEXT;
        ALTER TABLE mixed ADD COLUMN Extra_Col INTEGER DEFAULT 7;
        SELECT * FROM MIXED WHERE NUM = 1;
        EXPLAIN SELECT * FROM mixed;
    """)
    assert_error(res[0], "NameError")
    assert res[1].ok
    assert_error(res[2], "NameError")
    assert res[3].raw == {"ok": True}
    assert_rows(res[5], [["a"], ["b"]], columns=["Who"])
    assert_rows(res[6], [[2, 1], [1, 1]], columns=["Num", "count"])
    assert_error(res[7], "NameError")
    assert_error(res[8], "NameError")
    assert_rows(res[10], [[1, "a", 7]], columns=["Num", "Note", "Extra_Col"])
    assert plan(res[11]) == ["SCAN Mixed"]


@stage(6)
def test_plans_report_defined_spellings():
    res = run_ok("""
        CREATE TABLE Items (Id INTEGER PRIMARY KEY, Qty INTEGER, Code TEXT UNIQUE);
        CREATE TABLE Other (Ref INTEGER, Label TEXT);
        CREATE INDEX Items_Qty ON items (QTY);
        EXPLAIN SELECT * FROM ITEMS i WHERE qty = 1;
        EXPLAIN SELECT * FROM items WHERE ID > 1;
        EXPLAIN SELECT * FROM items WHERE code = 'x';
        EXPLAIN SELECT * FROM items JOIN other o ON O.REF = items.id;
        EXPLAIN SELECT * FROM other JOIN items ON ITEMS.ID = other.ref;
        EXPLAIN SELECT * FROM (SELECT * FROM other) AS MyAlias JOIN Items ON items.qty = myalias.ref;
        DROP INDEX ITEMS_QTY;
        EXPLAIN SELECT * FROM items WHERE qty = 1;
    """)
    assert plan(res[3]) == ["SEARCH Items USING INDEX Items_Qty (Qty = ?)"]
    assert plan(res[4]) == ["SEARCH Items USING INDEX Items_Id_key (Id RANGE)"]
    assert plan(res[5]) == ["SEARCH Items USING INDEX Items_Code_key (Code = ?)"]
    assert plan(res[6]) == ["SCAN Items", "HASH JOIN Other (Ref)"]
    assert plan(res[7]) == ["SCAN Other", "SEARCH Items USING INDEX Items_Id_key (Id = ?)"]
    assert plan(res[8]) == ["SCAN MyAlias", "SEARCH Items USING INDEX Items_Qty (Qty = ?)"]
    assert plan(res[10]) == ["SCAN Items"]


@stage(6)
def test_views_with_names_and_derived_tables_keep_spellings():
    res = run_ok("""
        CREATE TABLE Emp (Id INTEGER, Name TEXT, Pay INTEGER);
        INSERT INTO emp VALUES (1, 'ada', 300), (2, 'bo', 200);
        CREATE VIEW TopPaid (Who, Amount) AS SELECT name, PAY FROM emp WHERE pay > 250;
        CREATE VIEW Plain AS SELECT NAME, pay AS Salary FROM EMP;
        SELECT * FROM toppaid;
        SELECT * FROM PLAIN;
        WITH Cte (A, b) AS (SELECT id, name FROM emp) SELECT * FROM cte WHERE a = 2;
        WITH Totals AS (SELECT SUM(pay) AS Sum_Pay FROM emp) SELECT * FROM TOTALS;
        SELECT * FROM (SELECT Name AS N, pay FROM emp) d WHERE d.n = 'bo';
        EXPLAIN SELECT * FROM toppaid JOIN plain ON plain.name = toppaid.who;
        EXPLAIN WITH Cte AS (SELECT * FROM emp) SELECT * FROM CTE;
    """)
    assert_rows(res[4], [["ada", 300]], columns=["Who", "Amount"])
    assert_rows(res[5], [["ada", 300], ["bo", 200]], columns=["Name", "Salary"])
    assert_rows(res[6], [[2, "bo"]], columns=["A", "b"])
    assert_rows(res[7], [[500]], columns=["Sum_Pay"])
    assert_rows(res[8], [["bo", 200]], columns=["N", "Pay"])
    assert plan(res[9]) == ["SCAN TopPaid", "HASH JOIN Plain (Name)"]
    assert plan(res[10]) == ["SCAN Cte"]


@stage(6)
def test_spellings_survive_restarts_and_rollbacks(tmp_path):
    path = str(tmp_path / "names.db")
    res = run("""
        CREATE TABLE Orders (OrderId INTEGER PRIMARY KEY, Customer TEXT);
        CREATE INDEX ByCustomer ON orders (customer);
        INSERT INTO ORDERS VALUES (1, 'x');
        CREATE VIEW BigOrders AS SELECT OrderID, CUSTOMER AS Cust FROM orders;
        BEGIN;
        ALTER TABLE orders ADD COLUMN Rolled INTEGER;
        CREATE TABLE Temp (A INTEGER);
        ROLLBACK;
        ALTER TABLE orders ADD COLUMN Total_Amount REAL DEFAULT 0;
    """, args=("--db", path))
    assert all(r.ok for r in res), [r for r in res if not r.ok]
    with Session("--db", path) as s:
        assert_rows(s.execute("SELECT * FROM orders"), [[1, "x", 0.0]],
                    columns=["OrderId", "Customer", "Total_Amount"])
        assert s.execute("SELECT * FROM bigorders").columns == ["OrderId", "Cust"]
        assert plan(s.execute("EXPLAIN SELECT * FROM ORDERS WHERE CUSTOMER = 'x'")) == [
            "SEARCH Orders USING INDEX ByCustomer (Customer = ?)"]
        assert_error(s.execute("SELECT * FROM temp"), "NameError")
        s.ok("CREATE TABLE IF NOT EXISTS ORDERS (z INTEGER)")
        s.kill()
    res = run("EXPLAIN SELECT * FROM orders WHERE orderid = 1; SELECT * FROM Orders;", args=("--db", path))
    assert plan(res[0]) == ["SEARCH Orders USING INDEX Orders_OrderId_key (OrderId = ?)"]
    assert res[1].columns == ["OrderId", "Customer", "Total_Amount"]


@stage(6)
def test_data_stays_case_sensitive():
    res = run("""
        CREATE TABLE w (v TEXT UNIQUE);
        INSERT INTO w VALUES ('a'), ('A');
        SELECT 'abc' = 'ABC', 'abc' LIKE 'A%', UPPER('abc') = 'ABC';
        SELECT v FROM w WHERE v = 'A';
        INSERT INTO w VALUES ('a');
    """)
    assert res[1].rowcount == 2
    assert_rows(res[2], [[False, False, True]])
    assert_rows(res[3], [["A"]])
    assert_error(res[4], "ConstraintError")
