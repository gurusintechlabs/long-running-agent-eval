"""Shared fixtures: a fresh engine per test, with helpers for results and errors."""
import pytest

from minidb.engine import Engine
from minidb.protocol import DBError


class DB:
    def __init__(self) -> None:
        self.engine = Engine()

    def run(self, *statements: str) -> dict:
        """Execute statements in order; return the result of the last one."""
        result = None
        for sql in statements:
            result = self.engine.execute(sql)
        return result

    def rows(self, sql: str) -> list:
        return self.engine.execute(sql)["rows"]

    def one(self, sql: str):
        """The single value of a one-row, one-column query."""
        rows = self.rows(sql)
        assert len(rows) == 1 and len(rows[0]) == 1, rows
        return rows[0][0]

    def expect(self, sql: str, expected: list) -> None:
        """Assert the query's rows equal ``expected``, comparing value types strictly."""
        rows = self.rows(sql)
        assert same(rows, expected), f"{rows!r} != {expected!r}"

    def columns(self, sql: str) -> list:
        return self.engine.execute(sql)["columns"]

    def error(self, sql: str) -> str:
        """Execute a statement that must fail; return the wire error type."""
        with pytest.raises(DBError) as info:
            self.engine.execute(sql)
        assert type(info.value) is not DBError, "InternalError-like base DBError raised"
        assert str(info.value)
        return info.value.type_name


@pytest.fixture
def db() -> DB:
    return DB()


def same(a, b) -> bool:
    """Strict equality as a client sees it: 1, 1.0 and True are all different."""
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b
