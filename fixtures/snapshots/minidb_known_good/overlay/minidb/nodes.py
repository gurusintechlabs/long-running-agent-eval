"""AST node types produced by ``minidb.parser``."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ------------------------------------------------------------------ expressions


@dataclass
class Literal:
    value: Any


@dataclass
class ColumnRef:
    table: str | None
    name: str


@dataclass
class Star:
    table: str | None  # None for '*', else 't' for 't.*'


@dataclass
class Unary:
    op: str  # '-', '+', 'NOT'
    operand: Any


@dataclass
class Binary:
    op: str  # arithmetic, comparison, '||', 'AND', 'OR'
    left: Any
    right: Any


@dataclass
class IsNull:
    operand: Any
    negated: bool


@dataclass
class Between:
    operand: Any
    low: Any
    high: Any
    negated: bool


@dataclass
class InList:
    operand: Any
    items: list
    negated: bool


@dataclass
class InSubquery:
    operand: Any
    query: Select
    negated: bool


@dataclass
class Like:
    operand: Any
    pattern: Any
    negated: bool


@dataclass
class Func:
    name: str
    args: list
    distinct: bool = False
    star: bool = False  # COUNT(*)


@dataclass
class ScalarSubquery:
    query: Select


@dataclass
class Exists:
    query: Select


# ------------------------------------------------------------------ queries


@dataclass
class TableRef:
    name: str
    alias: str | None

    @property
    def exposed(self) -> str:
        return self.alias or self.name


@dataclass
class Join:
    kind: str  # 'inner', 'left', 'cross'
    table: TableRef
    on: Any


@dataclass
class SelectItem:
    expr: Any
    alias: str | None


@dataclass
class OrderItem:
    expr: Any
    desc: bool


@dataclass
class Select:
    items: list[SelectItem]
    distinct: bool = False
    from_: TableRef | None = None
    joins: list[Join] = field(default_factory=list)
    where: Any = None
    group_by: list[ColumnRef] = field(default_factory=list)
    having: Any = None
    order_by: list[OrderItem] = field(default_factory=list)
    limit: int | None = None
    offset: int = 0


# ------------------------------------------------------------------ statements


@dataclass
class ColumnDef:
    name: str
    type: str  # INTEGER, REAL, TEXT, BOOLEAN
    primary_key: bool = False
    not_null: bool = False
    unique: bool = False
    has_default: bool = False
    default: Any = None


@dataclass
class CreateTable:
    name: str
    columns: list[ColumnDef]


@dataclass
class DropTable:
    name: str


@dataclass
class Insert:
    table: str
    columns: list[str] | None
    rows: list[list]


@dataclass
class Update:
    table: str
    assignments: list[tuple[str, Any]]
    where: Any


@dataclass
class Delete:
    table: str
    where: Any


@dataclass
class CreateIndex:
    name: str
    table: str
    column: str
    unique: bool


@dataclass
class DropIndex:
    name: str


@dataclass
class CreateView:
    name: str
    query: Select
    sql: str


@dataclass
class DropView:
    name: str


@dataclass
class AlterAddColumn:
    table: str
    column: ColumnDef


@dataclass
class Explain:
    query: Select


@dataclass
class Begin:
    pass


@dataclass
class Commit:
    pass


@dataclass
class Rollback:
    pass


@dataclass
class Save:
    path: str


@dataclass
class Load:
    path: str
