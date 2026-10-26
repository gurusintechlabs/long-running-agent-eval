"""The state behind the HTTP API: the SQL engine of a data dir and its collections.

The engine is not thread-safe, and a request must behave as if it ran alone, so every ``/v1/sql``
request runs as a whole under the exclusive side of ``RWLock``. Collections have locks of their own.
"""
from __future__ import annotations

import json
import os

from minidb import protocol
from minidb.audit import AuditLog
from minidb.auth import KeyStore
from minidb.collection.sqlfunc import Knn
from minidb.collection.store import Catalog
from minidb.datadir import DataDir
from minidb.engine import Engine
from minidb.locks import RWLock

SQL_FILE = "sql.db"


class Service:
    def __init__(self, data_dir: DataDir, admin_key: str) -> None:
        self.data_dir = data_dir
        self.keys = KeyStore(data_dir.path, admin_key)
        self.audit = AuditLog(data_dir.path)
        self.lock = RWLock()
        self.engine = Engine(str(data_dir.file(SQL_FILE)))
        if self.engine.broken:
            raise OSError(self.engine.broken)
        self.catalog = Catalog(data_dir.path)
        self.knn = Knn(self.catalog)
        self.engine.table_functions["knn"] = self.knn

    def run_sql(self, text: str, principal=None) -> list[dict]:
        """Run every statement of ``text`` as ``python -m minidb`` would; one result object each.
        A transaction left open by the request is rolled back."""
        out = []
        with self.lock.write():
            self.knn.principal = principal
            try:
                for stmt in protocol.split_statements(text):
                    out.append(json.loads(protocol.handle(self.engine, stmt)))
            finally:
                if self.engine.tx is not None:
                    self.engine.execute("ROLLBACK")
                self.knn.principal = None
        return out

    def close(self) -> None:
        self.catalog.close()
        with self.lock.write():
            store = self.engine.store
            if store is not None and store.fd is not None:
                os.close(store.fd)
                store.fd = None
