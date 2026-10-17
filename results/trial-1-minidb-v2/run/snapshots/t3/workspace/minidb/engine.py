"""The minidb engine: executes one SQL statement at a time for ``minidb.protocol``."""
from __future__ import annotations

import sys

from minidb.catalog import Database
from minidb.executor import Executor
from minidb.parser import parse
from minidb.protocol import SQLRuntimeError, SQLSyntaxError

# Parsing, binding and evaluating expressions is recursive; allow deeply nested expressions
# (and long operator chains), and turn the rare RecursionError into an ordinary SQL error.
_RECURSION_LIMIT = 20000


class Engine:
    """One database session; state lives as long as the process.

    ``execute`` receives a single statement (no trailing ``;``, comments removed) and returns
      {"columns": [name, ...], "rows": [[value, ...], ...]}   for queries,
      {"rowcount": n}                                       for INSERT / UPDATE / DELETE,
      {}                                                    for everything else,
    with values of type None, bool, int, float or str. Errors are reported by raising a
    ``minidb.protocol.DBError`` subclass (``SQLSyntaxError``, ``SQLNameError``, ...).
    """

    def __init__(self) -> None:
        if sys.getrecursionlimit() < _RECURSION_LIMIT:
            sys.setrecursionlimit(_RECURSION_LIMIT)
        self.db = Database()
        self.executor = Executor(self.db)

    def execute(self, sql: str) -> dict:
        try:
            stmt = parse(sql)
        except RecursionError:
            raise SQLSyntaxError("statement is nested too deeply") from None
        try:
            return self.executor.execute(stmt)
        except RecursionError:
            raise SQLRuntimeError("expression is nested too deeply") from None
