"""CR-4: names are matched case-insensitively and reported with their defined spelling."""
from minidb.names import Ident
from tests.test_storage import session


def test_output_names_use_the_defined_spelling(db):
    db.run("CREATE TABLE Users (Id INT PRIMARY KEY, Name TEXT, Age INT)")
    db.run("INSERT INTO users VALUES (1, 'Ann', 30)")
    assert db.columns("SELECT NAME FROM users") == ["Name"]
    assert db.columns("SELECT * FROM USERS") == ["Id", "Name", "Age"]
    assert db.columns("SELECT u.AGE, (U.name), users.* FROM users JOIN users u ON u.id = users.ID"
                      ) == ["Age", "Name", "Id", "Name", "Age"]
    assert db.columns("SELECT name AS Total, AGE AS AGE, id + 1, COUNT(*), LOWER(name), "
                      "ROW_NUMBER() OVER (), CASE WHEN TRUE THEN 1 END, CAST(1 AS TEXT), "
                      "EXISTS (SELECT 1) FROM users GROUP BY id, name, age") == [
        "Total", "AGE", "?column?", "count", "lower", "row_number", "case", "cast", "exists"]
    # correlated references report the outer column's spelling
    assert db.columns("SELECT (SELECT NAME), u.ID FROM users u") == ["?column?", "Id"]
    assert db.columns("SELECT x.NaMe FROM users x WHERE EXISTS (SELECT AGE)") == ["Name"]


def test_columns_of_views_derived_tables_and_with(db):
    db.run("CREATE TABLE Users (Id INT, Name TEXT)", "INSERT INTO users VALUES (1, 'a')")
    db.run("CREATE VIEW Names (Who) AS SELECT name FROM users")
    db.run("CREATE VIEW Plain AS SELECT NAME, id AS Code FROM USERS")
    assert db.columns("SELECT * FROM names") == ["Who"]
    assert db.columns("SELECT WHO FROM NAMES") == ["Who"]
    assert db.columns("SELECT * FROM plain") == ["Name", "Code"]
    assert db.columns("SELECT code FROM plain") == ["Code"]
    assert db.columns("SELECT * FROM (SELECT ID AS Num, name FROM users) AS D") == ["Num", "Name"]
    assert db.columns("SELECT d.NUM FROM (SELECT ID AS Num FROM users) AS D") == ["Num"]
    assert db.columns("WITH Cte (First, Second) AS (SELECT id, name FROM users) "
                      "SELECT * FROM cte") == ["First", "Second"]
    assert db.columns("WITH Cte AS (SELECT id AS Ident FROM users) SELECT IDENT FROM CTE") == [
        "Ident"]
    assert db.columns("SELECT Id AS A FROM users UNION SELECT 2") == ["A"]


def test_plans_use_defined_spellings(db):
    db.run("CREATE TABLE Users (Id INT PRIMARY KEY, Age INT, Email TEXT UNIQUE)")
    db.run("CREATE INDEX Users_Age ON USERS (AGE)")
    db.expect("EXPLAIN SELECT * FROM users WHERE age > 3",
              [["SEARCH Users USING INDEX Users_Age (Age RANGE)"]])
    db.expect("EXPLAIN SELECT * FROM USERS u WHERE U.ID = 1",
              [["SEARCH Users USING INDEX Users_Id_key (Id = ?)"]])
    db.expect("EXPLAIN SELECT * FROM users WHERE EMAIL = 'x'",
              [["SEARCH Users USING INDEX Users_Email_key (Email = ?)"]])
    db.run("CREATE VIEW AllUsers AS SELECT id AS UserId FROM users")
    db.expect("EXPLAIN WITH Recent AS (SELECT id AS Rid FROM users) SELECT * FROM recent "
              "JOIN allusers ON ALLUSERS.userid = recent.rid JOIN (SELECT Age AS A FROM users) "
              "AS Dt ON dt.a = recent.RID",
              [["SCAN Recent"], ["HASH JOIN AllUsers (UserId)"], ["HASH JOIN Dt (A)"]])
    assert db.error("DROP INDEX users_id_KEY") == "ConstraintError"  # matched regardless of case
    db.run("DROP INDEX USERS_AGE")


def test_matching_and_duplicates_are_case_insensitive(db):
    db.run("CREATE TABLE Users (Name TEXT)")
    for sql in ("CREATE TABLE USERS (x INT)", "CREATE TABLE t (a INT, A INT)",
                "CREATE VIEW users AS SELECT 1", "ALTER TABLE users ADD NAME INT",
                "INSERT INTO users (name, NAME) VALUES (1, 2)",
                "CREATE VIEW v (a, A) AS SELECT 1, 2",
                "WITH c AS (SELECT 1), C AS (SELECT 2) SELECT 1"):
        assert db.error(sql) in ("NameError", "SyntaxError"), sql
    db.run("CREATE INDEX Idx ON users (name)")
    assert db.error("CREATE INDEX IDX ON users (name)") == "NameError"
    assert db.run("CREATE TABLE IF NOT EXISTS USERS (z INT)") == {}
    assert db.columns("SELECT * FROM users") == ["Name"]
    db.run("INSERT INTO uSeRs VALUES ('Bob')")
    db.expect("SELECT NAME FROM USERS WHERE name = 'Bob'", [["Bob"]])
    db.expect("SELECT name FROM users WHERE name = 'bob'", [])  # data stays case-sensitive


def test_order_by_names_match_output_names_case_insensitively(db):
    db.run("CREATE TABLE T (Score INT)", "INSERT INTO t VALUES (2), (1)")
    db.expect("SELECT score AS Points FROM t ORDER BY POINTS", [[1], [2]])
    db.expect("SELECT COUNT(*) FROM t ORDER BY COUNT", [[2]])
    db.expect("SELECT * FROM t ORDER BY SCORE DESC", [[2], [1]])


def test_keywords_and_function_names_are_case_insensitive(db):
    db.run("create table t (a int)", "insert into t values (1)")
    assert db.columns("select Count(*), SUM(a), Row_Number() Over () from t") == [
        "count", "sum", "row_number"]


def test_spellings_are_durable(tmp_path):
    path = tmp_path / "db"
    session(path, """
        CREATE TABLE Users (Id INT PRIMARY KEY, FullName TEXT);
        CREATE INDEX ByName ON users (fullname);
        CREATE VIEW Short (Who) AS SELECT FULLNAME FROM users;
        INSERT INTO users VALUES (1, 'Ann');
        ALTER TABLE USERS ADD COLUMN JoinedOn TEXT;
    """)
    res = session(path, """
        SELECT * FROM users;
        SELECT * FROM short;
        EXPLAIN SELECT * FROM users WHERE fullname = 'x';
        EXPLAIN SELECT * FROM users WHERE id = 1;
        DROP INDEX byname;
    """)
    assert res[0]["columns"] == ["Id", "FullName", "JoinedOn"]
    assert res[1]["columns"] == ["Who"]
    assert res[2]["rows"] == [["SEARCH Users USING INDEX ByName (FullName = ?)"]]
    assert res[3]["rows"] == [["SEARCH Users USING INDEX Users_Id_key (Id = ?)"]]
    assert res[4] == {"ok": True}


def test_ident():
    name = Ident("Users")
    assert name == "USERS" and "users" == name and str(name) == "Users"
    assert {name: 1}[Ident("uSeRs")] == 1 and {"users": 1}[name] == 1
    assert name != "Other" and hash(name) == hash(Ident("USERS"))


def test_every_logged_operation_replays_with_mixed_case_names(tmp_path):
    """Every kind of log record, with names spelled differently where defined and where used;
    restarting after each statement must not change anything, spellings included."""
    from minidb.engine import Engine
    from tests.test_storage import observable

    script = [
        "CREATE TABLE MixedCase (Id INT PRIMARY KEY, Val TEXT UNIQUE, Num INT)",
        "INSERT INTO mixedcase VALUES (1, 'a', 10), (2, 'b', 20)",
        "CREATE INDEX ByNum ON MIXEDCASE (NUM)",
        "UPDATE MixedCASE SET num = NUM + 1 WHERE ID = 1",
        "DELETE FROM mixedcase WHERE VAL = 'b'",
        "ALTER TABLE mixedcase ADD COLUMN Extra TEXT DEFAULT 'e'",
        "ALTER TABLE MIXEDCASE DROP COLUMN VAL",
        "CREATE VIEW TheView (Alpha) AS SELECT EXTRA FROM MixedCase",
        "BEGIN", "INSERT INTO MIXEDCASE (ID, num) VALUES (3, 30)", "DROP INDEX bynum",
        "CREATE INDEX ByExtra ON mixedcase (EXTRA)", "COMMIT",
        "CREATE TABLE Other (X INT)", "DROP TABLE OTHER", "DROP VIEW theview",
        "CREATE VIEW TheView (Beta) AS SELECT ID FROM MIXEDCASE",
    ]
    path = str(tmp_path / "db")
    reference = Engine()
    for sql in script:
        durable = Engine(path)
        assert durable.execute(sql) == reference.execute(sql), sql
        durable.close()
        if sql not in ("BEGIN",) and not reference.in_transaction:
            reopened = Engine(path)
            state = observable(reopened)
            assert state == observable(reference), sql
            assert [str(t.name) for t in reopened.db.tables.values()] == \
                [str(t.name) for t in reference.db.tables.values()]
            reopened.close()
    final = Engine(path)
    assert final.execute("SELECT * FROM mixedcase")["columns"] == ["Id", "Num", "Extra"]
    assert final.execute("SELECT * FROM theview")["columns"] == ["Beta"]
    assert sorted(map(str, final.db.indexes)) == ["ByExtra", "MixedCase_Id_key"]
