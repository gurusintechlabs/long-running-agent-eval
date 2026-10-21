"""The minidb engine: executes one SQL statement at a time for ``minidb.protocol``.

``Engine.execute(sql)`` parses the statement and dispatches it. Every statement is atomic: DML
computes and validates all its changes before applying any of them, and DDL validates first.
UNIQUE and PRIMARY KEY constraints are checked through the indexes that back them, so a
single-row statement costs O(log n), not O(n).

Transactions are copy-on-write: BEGIN saves the catalog (O(number of tables)); the first change
to a table inside the transaction swaps in a copy of its row dict and index lists, keeping the
originals for ROLLBACK. Every applied change also produces redo records (``minidb.durable``),
written to the log per statement, or per transaction at COMMIT, when a ``--db`` path is set.
"""
from __future__ import annotations

from typing import Any

from minidb import durable
from minidb import nodes as n
from minidb.executor import Compiler, Env, Executor, Scope, Source
from minidb.parser import parse
from minidb.protocol import (
    ConstraintError,
    SQLIOError,
    SQLNameError,
    SQLSyntaxError,
    SQLTypeError,
    TransactionError,
)
from minidb.storage import Column, Database, Index, Table, View, same
from minidb.values import coerce, hash_key, truth, vector_dim


def _parse_query(sql: str):
    stmt = parse(sql)
    if not isinstance(stmt, (n.Select, n.SetOp, n.With)):
        raise ValueError("stored view is not a query")
    return stmt


class _Transaction:
    def __init__(self, db: Database) -> None:
        self.tables = db.tables.copy()
        self.indexes = db.indexes.copy()
        self.views = db.views.copy()
        self.next_rowid = db.next_rowid
        self.next_index_seq = db.next_index_seq
        self.saved_tables: dict[int, tuple] = {}
        self.saved_indexes: dict[int, tuple] = {}
        self.ops: list = []


class Engine:
    """One database session; state lives as long as the process (or in ``db_path``)."""

    db_path: str | None = None   # set by ``python -m minidb --db PATH`` (minidb/__main__.py)

    def __init__(self, db_path: str | None = None) -> None:
        self.db = Database()
        self.tx: _Transaction | None = None
        self.ops: list = []
        self.store: durable.Store | None = None
        self.broken: str | None = None
        self.replaying = False
        path = db_path if db_path is not None else type(self).db_path
        if path is not None:
            try:
                self._open(path)
            except (OSError, durable.NotADatabase, ValueError, KeyError, TypeError) as exc:
                self.broken = f"cannot open database {path}: {exc}"
                self.db, self.store = Database(), None

    # ------------------------------------------------------------ durability

    def _open(self, path: str) -> None:
        store = durable.Store(path)
        snapshot, records = store.open()
        if snapshot is not None:
            self.db, _ = durable.from_snapshot(snapshot, _parse_query)
        self.replaying = True
        try:
            for ops in records:
                self._replay(ops)
        finally:
            self.replaying = False
        durable.build_indexes(self.db)
        self.store = store

    def _replay(self, ops: list) -> None:
        db = self.db
        for op in ops:
            kind = op[0]
            if kind == "s":
                self.execute(op[1])
                continue
            table = db.tables[op[1]]
            rid = int(op[2])
            if kind == "d":
                del table.rows[rid]
            else:
                table.rows[rid] = [durable.decode_value(v) for v in op[3]]
                if rid >= db.next_rowid:
                    db.next_rowid = rid + 1

    def _persist(self, ops: list) -> None:
        if self.store is None or not ops:
            return
        try:
            self.store.append(ops)
            if self.store.wants_checkpoint():
                self.store.checkpoint(self.db)
        except OSError as exc:
            raise SQLIOError(f"cannot write the database: {exc}") from None

    # ------------------------------------------------------------ dispatch

    def execute(self, sql: str) -> dict:
        if self.broken is not None:
            raise SQLIOError(self.broken)
        stmt = parse(sql)
        handler = getattr(self, "_x_" + type(stmt).__name__)
        self.ops = []
        result = handler(stmt)
        if self.ops and not self.replaying:
            if isinstance(stmt, (n.CreateTable, n.DropTable, n.CreateIndex, n.DropIndex,
                                 n.AlterAddColumn, n.AlterDropColumn, n.CreateView, n.DropView)):
                self.ops = [["s", sql]]
            if self.tx is not None:
                self.tx.ops.extend(self.ops)
            else:
                self._persist(self.ops)
        self.ops = []
        return result

    @property
    def ex(self) -> Executor:
        return Executor(self.db)

    def _table(self, name: str) -> Table:
        if name in self.db.tables:
            return self.db.tables[name]
        if name in self.db.views:
            raise SQLNameError(f"{name} is a view, not a table")
        raise SQLNameError(f"no such table: {name}")

    def _touch(self, table: Table) -> None:
        """Inside a transaction, keep the pre-transaction rows and index entries of ``table``."""
        tx = self.tx
        if tx is None or id(table) in tx.saved_tables:
            return
        tx.saved_tables[id(table)] = (table, table.rows, table.columns)
        table.rows = dict(table.rows)
        table.columns = list(table.columns)
        for ix in self.db.table_indexes(table.name):
            if id(ix) not in tx.saved_indexes:
                tx.saved_indexes[id(ix)] = (ix, ix.entries)
                ix.entries = list(ix.entries)

    # ------------------------------------------------------------ queries

    def _x_Select(self, s: n.Select) -> dict:
        return self.ex.query(s)

    def _x_SetOp(self, s: n.SetOp) -> dict:
        return self.ex.query(s)

    def _x_With(self, s: n.With) -> dict:
        return self.ex.query(s)

    def _x_Explain(self, s: n.Explain) -> dict:
        return self.ex.explain(s.query)

    # ------------------------------------------------------------ transactions

    def _x_Begin(self, s: n.Begin) -> dict:
        if self.tx is not None:
            raise TransactionError("a transaction is already open")
        self.tx = _Transaction(self.db)
        return {}

    def _x_Commit(self, s: n.Commit) -> dict:
        if self.tx is None:
            raise TransactionError("no transaction is open")
        tx, self.tx = self.tx, None
        self._persist(tx.ops)
        return {}

    def _x_Rollback(self, s: n.Rollback) -> dict:
        if self.tx is None:
            raise TransactionError("no transaction is open")
        tx, self.tx = self.tx, None
        db = self.db
        db.tables, db.indexes, db.views = tx.tables, tx.indexes, tx.views
        db.next_rowid, db.next_index_seq = tx.next_rowid, tx.next_index_seq
        for table, rows, columns in tx.saved_tables.values():
            table.rows, table.columns = rows, columns
        for ix, entries in tx.saved_indexes.values():
            ix.entries = entries
        return {}

    # ------------------------------------------------------------ DDL

    def _column(self, d: n.ColumnDef) -> Column:
        default = coerce(d.default, d.type, d.name) if d.has_default else None
        return Column.from_def(d, default)

    def _x_CreateTable(self, s: n.CreateTable) -> dict:
        if self.db.relation_exists(s.name):
            if s.if_not_exists:
                return {}
            raise SQLNameError(f"{s.name} already exists")
        names = [c.name.lower() for c in s.columns]
        if len(set(names)) != len(names):
            raise SQLNameError(f"duplicate column name in table {s.name}")
        cols = [self._column(c) for c in s.columns]
        for c in cols:
            if c.unique and vector_dim(c.type) is not None:
                raise SQLTypeError(f"a VECTOR column cannot be UNIQUE or a PRIMARY KEY ({c.name})")
        implicit = [f"{s.name}_{c.name}_key" for c in cols if c.unique]
        for name in implicit:
            if name in self.db.indexes:
                raise SQLNameError(f"index {name} already exists")
        self.db.tables[s.name] = Table(s.name, cols)
        for c in cols:
            if c.unique:
                name = f"{s.name}_{c.name}_key"
                self.db.indexes[name] = Index(name, s.name, c.name, True, self.db.new_index_seq(),
                                              implicit=True)
        self.ops.append(None)
        return {}

    def _x_DropTable(self, s: n.DropTable) -> dict:
        if s.if_exists and not self.db.relation_exists(s.name):
            return {}
        self._table(s.name)
        del self.db.tables[s.name]
        for name in [i.name for i in self.db.indexes.values() if same(i.table, s.name)]:
            del self.db.indexes[name]
        self.ops.append(None)
        return {}

    def _x_CreateIndex(self, s: n.CreateIndex) -> dict:
        if s.name in self.db.indexes:
            if s.if_not_exists:
                return {}
            raise SQLNameError(f"index {s.name} already exists")
        table = self._table(s.table)
        ci = table.col_index(s.column)
        if ci is None:
            raise SQLNameError(f"no column {s.column} in table {s.table}")
        if vector_dim(table.columns[ci].type) is not None:
            raise SQLTypeError(f"cannot index the VECTOR column {s.column}")
        if s.unique:
            self._check_unique_values(s.column, [r[ci] for r in table.rows.values()])
        ix = Index(s.name, table.name, table.columns[ci].name, s.unique, self.db.new_index_seq())
        ix.build(table)
        self.db.indexes[s.name] = ix
        self.ops.append(None)
        return {}

    def _x_DropIndex(self, s: n.DropIndex) -> dict:
        ix = self.db.indexes.get(s.name)
        if ix is None:
            if s.if_exists:
                return {}
            raise SQLNameError(f"no such index: {s.name}")
        if ix.implicit:
            raise ConstraintError(f"index {s.name} enforces a constraint of {ix.table}")
        del self.db.indexes[s.name]
        self.ops.append(None)
        return {}

    def _x_CreateView(self, s: n.CreateView) -> dict:
        if self.db.relation_exists(s.name):
            if s.if_not_exists:
                return {}
            raise SQLNameError(f"{s.name} already exists")
        prepared = self.ex.prepare(s.query)  # validates every name now
        if s.columns is not None:
            if len(s.columns) != len(prepared.columns):
                raise SQLSyntaxError(f"view {s.name} lists {len(s.columns)} columns but its query "
                                     f"has {len(prepared.columns)}")
            if len({c.lower() for c in s.columns}) != len(s.columns):
                raise SQLNameError(f"view {s.name} lists a column twice")
        self.db.views[s.name] = View(s.name, s.sql, s.query, s.columns)
        self.ops.append(None)
        return {}

    def _x_DropView(self, s: n.DropView) -> dict:
        if s.name not in self.db.views:
            if s.name in self.db.tables:
                raise SQLNameError(f"{s.name} is a table, not a view")
            if s.if_exists:
                return {}
            raise SQLNameError(f"no such view: {s.name}")
        del self.db.views[s.name]
        self.ops.append(None)
        return {}

    def _x_AlterAddColumn(self, s: n.AlterAddColumn) -> dict:
        table = self._table(s.table)
        if table.col_index(s.column.name) is not None:
            raise SQLNameError(f"column {s.column.name} already exists in {s.table}")
        col = self._column(s.column)
        if col.unique and vector_dim(col.type) is not None:
            raise SQLTypeError(f"a VECTOR column cannot be UNIQUE ({col.name})")
        if col.not_null and col.default is None and table.rows:
            raise ConstraintError(f"cannot add NOT NULL column {col.name} without a default "
                                  "to a table that has rows")
        self._touch(table)
        table.columns = table.columns + [col]
        table.rows = {rid: row + [col.default] for rid, row in table.rows.items()}
        self.ops.append(None)
        return {}

    def _x_AlterDropColumn(self, s: n.AlterDropColumn) -> dict:
        table = self._table(s.table)
        ci = table.col_index(s.column)
        if ci is None:
            raise SQLNameError(f"no column {s.column} in table {s.table}")
        if table.columns[ci].primary_key:
            raise ConstraintError(f"cannot drop the PRIMARY KEY column {s.column}")
        if len(table.columns) == 1:
            raise ConstraintError(f"cannot drop the only column of {s.table}")
        self._touch(table)
        for ix in [ix for ix in self.db.table_indexes(table.name) if same(ix.column, s.column)]:
            del self.db.indexes[ix.name]
        table.columns = table.columns[:ci] + table.columns[ci + 1:]
        table.rows = {rid: row[:ci] + row[ci + 1:] for rid, row in table.rows.items()}
        self.ops.append(None)
        return {}

    # ------------------------------------------------------------ DML

    @staticmethod
    def _check_unique_values(column: str, values) -> None:
        seen = set()
        for v in values:
            if v is None:
                continue
            k = hash_key(v)
            if k in seen:
                raise ConstraintError(f"UNIQUE constraint failed: duplicate value {v!r} in {column}")
            seen.add(k)

    @staticmethod
    def _store(table: Table, row: list, values: list, positions: list[int]) -> list:
        """Type-check ``values`` into ``row`` at ``positions`` (in order), then NOT NULL checks."""
        for ci, v in zip(positions, values, strict=True):
            c = table.columns[ci]
            row[ci] = coerce(v, c.type, c.name)
        for c, v in zip(table.columns, row, strict=True):
            if v is None and c.not_null:
                raise ConstraintError(f"NOT NULL constraint failed: {table.name}.{c.name}")
        return row

    def _unique_columns(self, table: Table) -> list[tuple[int, Index]]:
        """(column index, an index on it) for every column that must hold unique values."""
        out: dict[int, Index] = {}
        for ix in self.db.table_indexes(table.name):
            ci = table.col_index(ix.column)
            if (ix.unique or table.columns[ci].unique) and ci not in out:
                out[ci] = ix
        return sorted(out.items())

    def _check_final_state(self, table: Table, changes: dict[int, list | None],
                           new_rows: list[list]) -> None:
        """UNIQUE / PRIMARY KEY against the state at the end of the statement."""
        for ci, ix in self._unique_columns(table):
            seen: set = set()
            pending = [(rid, row) for rid, row in changes.items() if row is not None]
            pending += [(None, row) for row in new_rows]
            for rid, row in pending:
                v = row[ci]
                if v is None:
                    continue
                k = hash_key(v)
                if k in seen:
                    raise ConstraintError(f"UNIQUE constraint failed: duplicate value {v!r} in "
                                          f"{table.name}.{table.columns[ci].name}")
                seen.add(k)
                for other in ix.eq(v):
                    if other != rid and other not in changes:
                        raise ConstraintError(f"UNIQUE constraint failed: duplicate value {v!r} in "
                                              f"{table.name}.{table.columns[ci].name}")

    def _apply(self, table: Table, changes: dict[int, list | None], new_rows: list[list]) -> None:
        """Apply validated changes: ``changes`` maps rowid -> new row (None = delete)."""
        if not changes and not new_rows:
            return
        self._touch(table)
        indexes = [(ix, table.col_index(ix.column)) for ix in self.db.table_indexes(table.name)]
        rows = table.rows
        ops = self.ops
        name = table.name
        enc = durable.encode_value
        for rid, new in changes.items():
            old = rows[rid]
            for ix, ci in indexes:
                if new is None or new[ci] != old[ci] or type(new[ci]) is not type(old[ci]):
                    ix.remove(old[ci], rid)
                    if new is not None:
                        ix.add(new[ci], rid)
            if new is None:
                del rows[rid]
                ops.append(["d", name, rid])
            else:
                rows[rid] = new
                ops.append(["u", name, rid, [enc(v) for v in new]])
        added = []
        for row in new_rows:
            rid = self.db.new_rowid()
            rows[rid] = row
            added.append(rid)
            ops.append(["i", name, rid, [enc(v) for v in row]])
        for ix, ci in indexes:
            ix.add_many([(rows[rid][ci], rid) for rid in added])

    def _x_Insert(self, s: n.Insert) -> dict:
        table = self._table(s.table)
        if s.columns is None:
            positions = list(range(len(table.columns)))
        else:
            positions = []
            for name in s.columns:
                ci = table.col_index(name)
                if ci is None:
                    raise SQLNameError(f"no column {name} in table {s.table}")
                positions.append(ci)
        if s.query is not None:
            prepared = self.ex.prepare(s.query)
            if len(prepared.columns) != len(positions):
                raise SQLSyntaxError(f"expected {len(positions)} columns, got {len(prepared.columns)}")
            source = prepared.run(None)
        else:
            for vals in s.rows:
                if len(vals) != len(positions):
                    raise SQLSyntaxError(f"expected {len(positions)} values, got {len(vals)}")
            comp = self.ex.compiler([])
            compiled = [[comp.compile(e) for e in vals] for vals in s.rows]
            env = Env(())
            source = ([f(env) for f in fns] for fns in compiled)
        defaults = [c.default for c in table.columns]
        new_rows = [self._store(table, list(defaults), values, positions) for values in source]
        self._check_final_state(table, {}, new_rows)
        self._apply(table, {}, new_rows)
        return {"rowcount": len(new_rows)}

    def _target_scope(self, table: Table) -> Scope:
        return Scope([Source(table.name, table.name, [c.name for c in table.columns],
                             table=table.name)])

    def _x_Update(self, s: n.Update) -> dict:
        table = self._table(s.table)
        targets = []
        for name, _ in s.assignments:
            ci = table.col_index(name)
            if ci is None:
                raise SQLNameError(f"no column {name} in table {s.table}")
            targets.append(ci)
        ex = self.ex
        scope = self._target_scope(table)
        comp = Compiler(ex, scope)
        fns = [comp.compile(e) for _, e in s.assignments]
        where = comp.compile(s.where) if s.where is not None else None
        changes: dict[int, list | None] = {}
        rows = table.rows
        for rid in ex.target_rowids(table.name, s.where, scope):
            row = rows[rid]
            env = Env((row,))
            if where is not None and truth(where(env), "WHERE condition") is not True:
                continue
            values = [f(env) for f in fns]
            changes[rid] = self._store(table, list(row), values, targets)
        self._check_final_state(table, changes, [])
        self._apply(table, changes, [])
        return {"rowcount": len(changes)}

    def _x_Delete(self, s: n.Delete) -> dict:
        table = self._table(s.table)
        ex = self.ex
        scope = self._target_scope(table)
        where = Compiler(ex, scope).compile(s.where) if s.where is not None else None
        rows = table.rows
        doomed = [rid for rid in ex.target_rowids(table.name, s.where, scope)
                  if where is None or truth(where(Env((rows[rid],))), "WHERE condition") is True]
        self._apply(table, dict.fromkeys(doomed), [])
        return {"rowcount": len(doomed)}


def run_sql(engine: Engine, script: str) -> list[Any]:
    """Convenience for tests: execute every statement of ``script``; return results/errors."""
    from minidb.protocol import DBError, split_statements
    out: list[Any] = []
    for stmt in split_statements(script):
        try:
            out.append(engine.execute(stmt))
        except DBError as exc:
            out.append(exc)
    return out
