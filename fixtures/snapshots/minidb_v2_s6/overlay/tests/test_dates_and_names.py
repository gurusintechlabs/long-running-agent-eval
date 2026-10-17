import datetime

import pytest

from minidb import durable
from minidb.engine import Engine, run_sql
from minidb.protocol import ConstraintError, SQLRuntimeError, SQLTypeError
from minidb.storage import CIDict
from minidb.values import arith, parse_date, to_wire


def test_date_values():
    d = parse_date("2024-02-29")
    assert arith("+", d, 1) == datetime.date(2024, 3, 1) and arith("-", datetime.date(2024, 3, 1), d) == 1
    assert to_wire(d) == "2024-02-29" and durable.decode_value(durable.encode_value(d)) == d
    for bad in ("2023-02-29", "2023-1-5", "0000-01-01"):
        with pytest.raises(ValueError):
            parse_date(bad)
    with pytest.raises(SQLRuntimeError):
        arith("+", datetime.date(9999, 12, 31), 1)
    with pytest.raises(SQLTypeError):
        arith("+", d, d)


def test_dates_in_tables_and_names_keep_spellings():
    e = Engine()
    res = run_sql(e, """
        CREATE TABLE Ev (Day DATE, Title TEXT);
        INSERT INTO ev VALUES (DATE '2024-01-02', 'b'), (DATE '2023-12-31', 'a');
        SELECT TITLE, day + 1 AS Next FROM EV ORDER BY DAY;
        INSERT INTO ev VALUES ('2024-01-01', 'text');
    """)
    assert res[2] == {"columns": ["Title", "Next"], "rows": [["a", "2024-01-01"], ["b", "2024-01-03"]]}
    assert isinstance(res[3], ConstraintError)


def test_case_insensitive_catalog():
    d = CIDict()
    d["Users"] = 1
    assert "USERS" in d and d["users"] == 1 and d.get("uSeRs") == 1 and list(d.copy()) == ["users"]
    del d["USERS"]
    assert "users" not in d
