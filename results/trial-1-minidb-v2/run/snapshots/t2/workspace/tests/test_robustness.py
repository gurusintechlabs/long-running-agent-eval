"""No statement, however malformed, may fail with anything but a DBError (an InternalError on
the wire). Valid statements are mutated at random (tokens deleted, inserted or replaced)."""
import random
import re

import pytest

from minidb.engine import Engine
from minidb.protocol import DBError

STATEMENTS = [
    "SELECT id, s || 'x', r * 2, NOT b FROM t WHERE id BETWEEN 1 AND 3 ORDER BY 2 DESC LIMIT 2",
    "SELECT s, COUNT(*), SUM(r), AVG(id), MIN(s), MAX(b) FROM t GROUP BY s HAVING COUNT(*) > 0",
    "SELECT a.id, b.s FROM t a LEFT JOIN t b ON a.id = b.id + 1 CROSS JOIN t c WHERE c.id IN (1)",
    "SELECT CASE WHEN r > 0 THEN 'p' ELSE 'n' END, CAST(id AS TEXT), SUBSTR(s, 1, 2) FROM t",
    "SELECT id FROM t WHERE EXISTS (SELECT 1 FROM t i WHERE i.id = t.id) AND id NOT IN "
    "(SELECT id FROM t WHERE r < 0)",
    "SELECT (SELECT MAX(id) FROM t), NULLIF(s, 'a'), ROUND(r, 1), COALESCE(s, 'z') FROM t",
    "SELECT id FROM t UNION SELECT 5 INTERSECT SELECT 5 EXCEPT SELECT 1 ORDER BY 1",
    "SELECT * FROM (SELECT id AS k, s FROM t) AS d JOIN t ON t.id = d.k WHERE d.s LIKE '%a_'",
    "UPDATE t SET r = r + 1, s = UPPER(s) WHERE id = (SELECT MIN(id) FROM t)",
    "DELETE FROM t WHERE b IS NULL OR id % 2 = 0",
    "INSERT INTO t (id, s) SELECT id + 10, LOWER(s) FROM t",
    "CREATE TABLE IF NOT EXISTS u (a INTEGER PRIMARY KEY, b TEXT DEFAULT 'x' NOT NULL)",
]
FRAGMENTS = ["(", ")", ",", "SELECT", "FROM", "WHERE", "NULL", "*", "1", "0", "'q'", "1.5", "-",
             "/", "%", "||", "=", "AND", "OR", "NOT", "IN", "IS", "CASE", "WHEN", "END", "GROUP",
             "BY", "UNION", "ALL", "COUNT", "t", "id", "s", "r", "9223372036854775807", "JOIN",
             "ON", "AS", "EXISTS", "CAST", "INT", "(SELECT id FROM t)", "x.", "t."]
TOKEN = re.compile(r"'(?:[^']|'')*'|\d+\.\d+|\d+|\w+|<>|!=|<=|>=|\|\||\S")


def _mutate(r, sql):
    tokens = TOKEN.findall(sql)
    for _ in range(r.randint(1, 3)):
        i = r.randrange(len(tokens))
        k = r.random()
        if k < 0.33:
            del tokens[i]
        elif k < 0.66:
            tokens.insert(i, r.choice(FRAGMENTS))
        else:
            tokens[i] = r.choice(FRAGMENTS)
    return " ".join(tokens)


@pytest.mark.parametrize("seed", range(100))
def test_mutated_statements_never_crash(seed):
    r = random.Random(seed)
    engine = Engine()
    engine.execute("CREATE TABLE t (id INT PRIMARY KEY, s TEXT, r REAL NOT NULL DEFAULT 1.5, "
                   "b BOOL UNIQUE)")
    engine.execute("INSERT INTO t VALUES (1, 'a', 2.5, TRUE), (2, NULL, 0.0, FALSE), "
                   "(3, 'c', -1, NULL)")
    for _ in range(10):
        sql = _mutate(r, r.choice(STATEMENTS))
        try:
            engine.execute(sql)
        except DBError:
            pass
