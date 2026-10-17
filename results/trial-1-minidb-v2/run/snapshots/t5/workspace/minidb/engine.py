"""The minidb engine: executes one SQL statement at a time for ``minidb.protocol``."""
from __future__ import annotations

import sys
from typing import Optional

from minidb import nodes as n
from minidb.catalog import Database
from minidb.executor import Executor
from minidb.parser import parse
from minidb.protocol import SQLIOError, SQLRuntimeError, SQLSyntaxError, TransactionError
from minidb.storage import Storage, StorageError

# Parsing, binding and evaluating expressions is recursive; allow deeply nested expressions
# (and long operator chains), and turn the rare RecursionError into an ordinary SQL error.
_RECURSION_LIMIT = 20000


class Engine:
    """One database session; state lives as long as the process, or in the file ``path``.

    ``execute`` receives a single statement (no trailing ``;``, comments removed) and returns
      {"columns": [name, ...], "rows": [[value, ...], ...]}   for queries,
      {"rowcount": n}                                       for INSERT / UPDATE / DELETE,
      {}                                                    for everything else,
    with values of type None, bool, int, float or str. Errors are reported by raising a
    ``minidb.protocol.DBError`` subclass (``SQLSyntaxError``, ``SQLNameError``, ...).

    Every change is recorded in the database's journal. A failing statement is undone from it;
    outside a transaction, a successful statement's changes are written to the log (with
    ``path``) and then forgotten; inside one, they are kept until COMMIT (written as one log
    record) or ROLLBACK (undone).
    """

    def __init__(self, path: Optional[str] = None) -> None:
        if sys.getrecursionlimit() < _RECURSION_LIMIT:
            sys.setrecursionlimit(_RECURSION_LIMIT)
        self.db = Database()
        self.executor = Executor(self.db)
        self.in_transaction = False
        self.storage: Optional[Storage] = None
        self.broken: Optional[str] = None  # why the database file cannot be used
        if path is not None:
            storage = Storage(path)
            try:
                storage.open(self.db)
                self.storage = storage
            except (OSError, StorageError) as exc:
                self.broken = f"cannot use database {path}: {exc}"

    def execute(self, sql: str) -> dict:
        if self.broken is not None:
            raise SQLIOError(self.broken)
        try:
            stmt = parse(sql)
        except RecursionError:
            raise SQLSyntaxError("statement is nested too deeply") from None
        if isinstance(stmt, n.Transaction):
            return self._transaction(stmt.action)
        journal = self.db.journal
        mark = journal.mark()
        try:
            result = self.executor.execute(stmt)
        except RecursionError:
            journal.undo_to(mark)
            raise SQLRuntimeError("expression is nested too deeply") from None
        except BaseException:
            journal.undo_to(mark)  # statement atomicity, whatever went wrong
            raise
        if not self.in_transaction:
            self._persist(mark)
        return result

    def _persist(self, mark: int, undo_on_failure: bool = True) -> None:
        """Make the changes recorded since ``mark`` durable, then forget them. If they cannot
        be written: a statement is undone; a COMMIT keeps its transaction open, unchanged."""
        journal = self.db.journal
        ops = journal.redo_since(mark)
        if ops and self.storage is not None:
            try:
                self.storage.append(ops)
            except OSError as exc:
                if undo_on_failure:
                    journal.undo_to(mark)
                raise SQLIOError(f"cannot write to the database: {exc}") from None
            self.storage.maybe_checkpoint(self.db)
        journal.clear()

    def _transaction(self, action: str) -> dict:
        if action == "BEGIN":
            if self.in_transaction:
                raise TransactionError("a transaction is already active")
            self.in_transaction = True
            return {}
        if not self.in_transaction:
            raise TransactionError(f"{action} without an active transaction")
        if action == "COMMIT":
            self._persist(0, undo_on_failure=False)
        else:
            self.db.journal.undo_to(0)
            self.db.journal.clear()
        self.in_transaction = False
        return {}

    def close(self) -> None:
        """End of the session: an open transaction is rolled back."""
        if self.in_transaction:
            self._transaction("ROLLBACK")
        if self.storage is not None:
            self.storage.close()
