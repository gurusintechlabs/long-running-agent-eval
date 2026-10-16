import pytest
from minidb import values as v
from minidb.protocol import SQLRuntimeError, SQLTypeError


def test_integer_arithmetic_truncates_and_checks_overflow():
    assert v.arith("/", -7, 2) == -3 and v.arith("%", -7, 2) == -1 and v.arith("%", 7, -2) == 1
    assert v.arith("/", 7, 2.0) == 3.5 and isinstance(v.arith("*", 2, 1.5), float)
    with pytest.raises(SQLRuntimeError):
        v.arith("+", 2 ** 63 - 1, 1)
    with pytest.raises(SQLRuntimeError):
        v.arith("/", 1.5, 0)
    with pytest.raises(SQLTypeError):
        v.arith("%", 5, 2.0)


def test_coercion_rules():
    assert v.coerce(3, "REAL") == 3.0 and isinstance(v.coerce(3, "REAL"), float)
    assert v.coerce(None, "INTEGER") is None
    for value, col in ((1.5, "INTEGER"), ("5", "INTEGER"), (1, "TEXT"), (1, "BOOLEAN"), (True, "INTEGER")):
        with pytest.raises(SQLTypeError):
            v.coerce(value, col)


def test_comparisons_and_like():
    assert v.compare_op("=", 1, 1.0) is True and v.compare_op("<", "B", "a") is True
    assert v.compare_op("=", None, 1) is None
    with pytest.raises(SQLTypeError):
        v.compare(1, True)
    assert v.like("abc", "a_c") and v.like("", "%") and not v.like("abc", "A%")
    assert v.like("a.c", "a.c") and not v.like("abc", "a.c")


def test_sort_compare_puts_null_first():
    assert v.sort_compare(None, 1) == -1 and v.sort_compare("a", None) == 1 and v.sort_compare(None, None) == 0
