"""The minidb engine: executes one SQL statement at a time for ``minidb.protocol``.

This is a stub. Every statement is rejected until the engine is implemented.
"""
from __future__ import annotations

from minidb.protocol import NotSupportedError


class Engine:
    """One database session; state lives as long as the process.

    ``execute`` receives a single statement (no trailing ``;``, comments removed) and returns
      {"columns": [name, ...], "rows": [[value, ...], ...]}   for queries,
      {"rowcount": n}                                       for INSERT / UPDATE / DELETE,
      {}                                                    for everything else,
    with values of type None, bool, int, float or str. Errors are reported by raising a
    ``minidb.protocol.DBError`` subclass (``SQLSyntaxError``, ``SQLNameError``, ...).
    """

    def execute(self, sql: str) -> dict:
        keyword = sql.split(None, 1)[0].upper() if sql.split() else ""
        raise NotSupportedError(f"statement not supported yet: {keyword}")
