"""The state behind the HTTP API: the SQL engine of a data dir, and the lock that serialises it.

The engine is not thread-safe, and a request must behave as if it ran alone, so every ``/v1/sql``
request runs as a whole under the exclusive side of ``RWLock``.
"""
from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager

from minidb import protocol
from minidb.datadir import DataDir
from minidb.engine import Engine

SQL_FILE = "sql.db"


class RWLock:
    """Many readers or one writer; a waiting writer blocks new readers (no writer starvation)."""

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False
        self._waiting = 0

    @contextmanager
    def read(self):
        with self._cond:
            while self._writer or self._waiting:
                self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if not self._readers:
                    self._cond.notify_all()

    @contextmanager
    def write(self):
        with self._cond:
            self._waiting += 1
            while self._writer or self._readers:
                self._cond.wait()
            self._waiting -= 1
            self._writer = True
        try:
            yield
        finally:
            with self._cond:
                self._writer = False
                self._cond.notify_all()


class Service:
    def __init__(self, data_dir: DataDir) -> None:
        self.data_dir = data_dir
        self.lock = RWLock()
        self.engine = Engine(str(data_dir.file(SQL_FILE)))
        if self.engine.broken:
            raise OSError(self.engine.broken)

    def run_sql(self, text: str) -> list[dict]:
        """Run every statement of ``text`` as ``python -m minidb`` would; one result object each.
        A transaction left open by the request is rolled back."""
        out = []
        with self.lock.write():
            try:
                for stmt in protocol.split_statements(text):
                    out.append(json.loads(protocol.handle(self.engine, stmt)))
            finally:
                if self.engine.tx is not None:
                    self.engine.execute("ROLLBACK")
        return out

    def close(self) -> None:
        with self.lock.write():
            store = self.engine.store
            if store is not None and store.fd is not None:
                os.close(store.fd)
                store.fd = None
