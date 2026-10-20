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
class WindowFunc:
    name: str
    args: list
    star: bool
    partition: list
    order: list             # [OrderItem]


@dataclass
class InSubquery:
    operand: Any
    query: Any  # Select | SetOp
    negated: bool


@dataclass
class ScalarSubquery:
    query: Any


@dataclass
class Exists:
    query: Any


@dataclass
class Case:
    operand: Any            # None for a searched CASE
    whens: list             # [(condition or value, result)]
    else_: Any = None


@dataclass
class Cast:
    expr: Any
    type: str


# ------------------------------------------------------------------ queries


@dataclass
class TableRef:
    name: str | None        # None for a derived table
    alias: str | None
    query: Any = None       # derived table: Select | SetOp

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
    nulls_first: bool | None = None   # NULLS FIRST / NULLS LAST; None = by direction (CR-1)

    @property
    def null_first(self) -> bool:
        """CR-1: NULL is larger than every value unless NULLS FIRST/LAST says otherwise."""
        return self.desc if self.nulls_first is None else self.nulls_first


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


@dataclass
class SetOp:
    op: str                 # 'union', 'intersect', 'except'
    all: bool
    left: Any               # Select | SetOp
    right: Any
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
    if_not_exists: bool = False


@dataclass
class DropTable:
    name: str
    if_exists: bool = False


@dataclass
class Insert:
    table: str
    columns: list[str] | None
    rows: list[list] | None
    query: Any = None       # INSERT ... SELECT


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
    if_not_exists: bool = False


@dataclass
class DropIndex:
    name: str
    if_exists: bool = False


@dataclass
class Explain:
    query: Any


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
class AlterAddColumn:
    table: str
    column: ColumnDef


@dataclass
class AlterDropColumn:
    table: str
    column: str


@dataclass
class Cte:
    name: str
    columns: list[str] | None
    query: Any


@dataclass
class With:
    recursive: bool
    ctes: list[Cte]
    body: Any               # Select | SetOp


@dataclass
class CreateView:
    name: str
    columns: list[str] | None
    query: Any
    sql: str                # the query's text, for storage
    if_not_exists: bool = False


@dataclass
class DropView:
    name: str
    if_exists: bool = False
