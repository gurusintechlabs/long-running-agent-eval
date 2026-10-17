"""Durable storage: a snapshot file plus a write-ahead log.

Files (all names start with the database path ``PATH``):

* ``PATH``      the snapshot: a header line, then the whole database as JSON, including the
                sequence number of the last log record it contains.
* ``PATH-wal``  the log: one line per committed change (a statement outside a transaction, or a
                whole transaction at COMMIT): ``<crc32 hex> <json>``, the JSON holding the record's
                sequence number and its redo operations (``minidb.journal``).
* ``PATH-tmp``  a snapshot being written; it replaces ``PATH`` atomically (rename) when complete.

A record is appended with a single unbuffered write before the statement's answer is sent, so
it survives the process being killed. On opening, the snapshot is loaded and the log records
that follow it are replayed; a record that is incomplete or fails its checksum (the process was
killed while writing it) ends the log and is cut off, so every statement and every COMMIT is
either completely present or completely absent.

When the log has grown larger than the snapshot, a new snapshot is written and the log is
emptied (a checkpoint). This bounds the time to open the database, and its cost, linear in the
size of the database, is spread over at least as many bytes of log records.
"""
from __future__ import annotations

import json
import os
import zlib
from typing import Any

from minidb.catalog import Database, Index, Table, column_from_spec, column_spec

MAGIC = b"MINIDB-SNAPSHOT 1\n"
_MIN_LOG_BYTES = 1 << 20  # never checkpoint before the log reaches this size


class StorageError(Exception):
    """The file exists but is not a minidb database."""


class Storage:
    def __init__(self, path: str) -> None:
        self.path = path
        self.wal_path = path + "-wal"
        self.tmp_path = path + "-tmp"
        self.seq = 0               # sequence number of the last record applied
        self.log_bytes = 0
        self.snapshot_bytes = 0
        self._log: Any = None      # the log, open for appending (unbuffered)

    # ------------------------------------------------------------ opening

    def open(self, db: Database) -> None:
        """Load the database into the empty ``db``, creating the files if ``PATH`` does not
        exist. Raises OSError (files cannot be read or written) or StorageError."""
        db.journal.enabled = False
        try:
            if os.path.exists(self.path):
                self._load_snapshot(db)
                self._replay_log(db)
            else:
                self._write_snapshot(db)
                if os.path.exists(self.wal_path):  # left over from a deleted database
                    os.remove(self.wal_path)
            self._log = open(self.wal_path, "ab", buffering=0)
        finally:
            db.journal.enabled = True
            db.journal.clear()

    def _load_snapshot(self, db: Database) -> None:
        with open(self.path, "rb") as f:
            data = f.read()
        if not data.startswith(MAGIC):
            raise StorageError(f"{self.path} is not a minidb database")
        try:
            doc = json.loads(data[len(MAGIC):])
            self.seq = doc["seq"]
            for t in doc["tables"]:
                table = Table(t["name"], [column_from_spec(c) for c in t["columns"]])
                db.add_table(table)
                table._apply_insert([(rid, tuple(row)) for rid, row in t["rows"]])
                table.next_rid = max(table.next_rid, t["next_rid"])
            for name, table_name, column, unique in doc["indexes"]:
                table = db.tables[table_name]
                db.add_index(Index(name, table, table.column_index(column), unique=unique))
        except Exception as exc:  # any malformed content: not (or no longer) a minidb database
            raise StorageError(f"{self.path} is not a valid minidb database ({exc})") from None
        self.snapshot_bytes = len(data)

    def _replay_log(self, db: Database) -> None:
        if not os.path.exists(self.wal_path):
            return
        with open(self.wal_path, "rb") as f:
            data = f.read()
        pos = 0
        while True:
            end = data.find(b"\n", pos)
            if end < 0:
                break
            record = _decode(data[pos:end])
            if record is None:
                break  # incomplete or damaged: the process died while writing it
            seq = record["seq"]
            if seq > self.seq + 1:
                break
            if seq == self.seq + 1:  # (records up to self.seq are already in the snapshot)
                try:
                    for op in record["ops"]:
                        db.apply_redo(op)
                except Exception as exc:
                    raise StorageError(f"{self.wal_path} cannot be replayed ({exc})") from None
                self.seq = seq
            pos = end + 1
        if pos < len(data):
            with open(self.wal_path, "r+b") as f:
                f.truncate(pos)
        self.log_bytes = pos

    # ------------------------------------------------------------ writing

    def append(self, ops: list) -> None:
        """Durably log one committed change. Raises OSError (and logs nothing) on failure."""
        payload = json.dumps({"seq": self.seq + 1, "ops": ops}, separators=(",", ":"))
        line = f"{zlib.crc32(payload.encode()):08x} {payload}\n".encode()
        try:
            written = self._log.write(line)
            while written < len(line):  # a raw file may write partially
                more = self._log.write(line[written:])
                if not more:
                    raise OSError("short write to the database log")
                written += more
        except OSError:
            try:  # do not leave half a record in front of later ones
                os.ftruncate(self._log.fileno(), self.log_bytes)
            except OSError:
                pass
            raise
        self.seq += 1
        self.log_bytes += len(line)

    def maybe_checkpoint(self, db: Database) -> None:
        """Write a new snapshot and empty the log once the log outgrows the snapshot. Failing
        is harmless: everything is still in the log."""
        if self.log_bytes <= max(_MIN_LOG_BYTES, self.snapshot_bytes):
            return
        try:
            self._write_snapshot(db)
            os.ftruncate(self._log.fileno(), 0)
            self.log_bytes = 0
        except OSError:
            pass

    def _write_snapshot(self, db: Database) -> None:
        tables = [{"name": t.name, "columns": [column_spec(c) for c in t.columns],
                   "next_rid": t.next_rid,
                   "rows": [[rid, list(row)] for rid, row in t.scan_items()]}
                  for t in db.tables.values()]
        explicit = sorted((i for i in db.indexes.values() if not i.implicit),
                          key=lambda i: i.seq)
        indexes = [[i.name, i.table.name, i.column_name, i.unique] for i in explicit]
        data = MAGIC + json.dumps({"seq": self.seq, "tables": tables, "indexes": indexes},
                                  separators=(",", ":")).encode()
        with open(self.tmp_path, "wb") as f:
            f.write(data)
        os.replace(self.tmp_path, self.path)
        self.snapshot_bytes = len(data)

    def close(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None


def _decode(line: bytes) -> Any:
    """A log record, or None if the line is not a complete, intact record."""
    try:
        crc, payload = line.split(b" ", 1)
        if int(crc, 16) != zlib.crc32(payload):
            return None
        record = json.loads(payload)
        if not isinstance(record, dict) or not isinstance(record.get("seq"), int):
            return None
        return record
    except ValueError:
        return None
