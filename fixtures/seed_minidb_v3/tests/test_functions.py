import pytest

from minidb import functions as f
from minidb.protocol import SQLRuntimeError, SQLTypeError


def test_cast_table():
    assert f.cast(2.5, "TEXT") == "2.5" and f.cast(3.0, "TEXT") == "3.0" and f.cast(True, "TEXT") == "TRUE"
    assert f.cast(" 42 ", "INTEGER") == 42 and f.cast(-3.9, "INTEGER") == -3 and f.cast(True, "INTEGER") == 1
    assert f.cast(" 2.50 ", "REAL") == 2.5 and f.cast(0, "BOOLEAN") is False and f.cast(" True ", "BOOLEAN") is True
    assert f.cast(None, "INTEGER") is None
    for value, ty, err in (("4.5", "INTEGER", SQLRuntimeError), ("1e5", "REAL", SQLRuntimeError),
                           (1.5, "BOOLEAN", SQLTypeError), (True, "REAL", SQLTypeError),
                           (1e19, "INTEGER", SQLRuntimeError), ("yes", "BOOLEAN", SQLRuntimeError)):
        with pytest.raises(err):
            f.cast(value, ty)


def test_substr_round_nullif_replace():
    substr = f.SCALARS["substr"][2]
    assert substr("hello", 2, 3) == "ell" and substr("hello", 0, 2) == "h" and substr("hello", 9) == ""
    assert substr("hello", -1, 3) == "h"
    with pytest.raises(SQLRuntimeError):
        substr("hello", 2, -1)
    rnd = f.SCALARS["round"][2]
    assert rnd(2.675, 2) == 2.68 and rnd(-0.5) == -1.0 and rnd(7, 2) == 7
    assert f.SCALARS["nullif"][2]("a", None) == "a" and f.SCALARS["nullif"][2](2, 2.0) is None
    assert f.SCALARS["replace"][2]("aaa", "aa", "b") == "ba" and f.SCALARS["replace"][2]("abc", "", "x") == "abc"
