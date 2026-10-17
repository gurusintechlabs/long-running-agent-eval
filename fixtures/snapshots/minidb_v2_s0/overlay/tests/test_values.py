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
    with pytest.raises(SQLRuntimeError):
        v.arith("*", 1e300, 1e300)
    with pytest.raises(SQLTypeError):
        v.arith("%", 5, 2.0)


def test_coercion_rules():
    assert v.coerce(3, "REAL") == 3.0 and isinstance(v.coerce(3, "REAL"), float)
    assert v.coerce(None, "INTEGER") is None
    for value, col in ((1.5, "INTEGER"), ("5", "INTEGER"), (1, "TEXT"), (1, "BOOLEAN"), (True, "INTEGER")):
        with pytest.raises(SQLTypeError):
            v.coerce(value, col)


def test_comparisons_like_and_families():
    assert v.compare_op("=", 1, 1.0) is True and v.compare_op("<", "B", "a") is True
    assert v.compare_op("=", None, 1) is None
    with pytest.raises(SQLTypeError):
        v.compare(1, True)
    assert v.like("abc", "a_c") and v.like("", "%") and not v.like("abc", "A%")
    assert v.family(1) == v.family(2.5) == "num" and v.family(True) == "bool"
    assert v.hash_key(1) == v.hash_key(1.0) and v.hash_key(True) != v.hash_key(1)
