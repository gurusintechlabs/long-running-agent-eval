"""AST node classes produced by ``minidb.parser``."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union


# ---------------------------------------------------------------- expressions

class Expr:
    """Base class of expression nodes."""


@dataclass(eq=False)
class Literal(Expr):
    value: object  # None, bool, int, float or str


@dataclass(eq=False)
class ColumnRef(Expr):
    table: Optional[str]
    name: str


@dataclass(eq=False)
class Unary(Expr):
    op: str  # '-', '+'
    operand: Expr


@dataclass(eq=False)
class Not(Expr):
    operand: Expr


@dataclass(eq=False)
class Binary(Expr):
    op: str  # OR AND = <> < <= > >= || + - * / % LIKE  ('!=' is normalised to '<>')
    left: Expr
    right: Expr


@dataclass(eq=False)
class IsNull(Expr):
    operand: Expr
    negated: bool


@dataclass(eq=False)
class Between(Expr):
    operand: Expr
    low: Expr
    high: Expr
    negated: bool


@dataclass(eq=False)
class InList(Expr):
    operand: Expr
    items: list[Expr]
    negated: bool


@dataclass(eq=False)
class FuncCall(Expr):
    name: str            # lower case
    args: list[Expr]
    distinct: bool = False
    star: bool = False   # COUNT(*)


@dataclass(eq=False)
class Case(Expr):
    operand: Optional[Expr]          # None for a searched CASE
    whens: list[tuple[Expr, Expr]]   # (condition or value, result)
    else_: Optional[Expr]


@dataclass(eq=False)
class Cast(Expr):
    operand: Expr
    type: str  # INTEGER, REAL, TEXT, BOOLEAN


@dataclass(eq=False)
class Subquery(Expr):
    """A scalar subquery."""
    query: "Query"


@dataclass(eq=False)
class InSubquery(Expr):
    operand: Expr
    query: "Query"
    negated: bool


@dataclass(eq=False)
class Exists(Expr):
    query: "Query"


@dataclass(eq=False)
class WindowCall(Expr):
    """``name(args) OVER (PARTITION BY ... ORDER BY ...)``."""
    name: str            # lower case
    args: list[Expr]
    star: bool           # COUNT(*)
    distinct: bool       # (an error with OVER, reported by the compiler)
    partition: list[Expr]
    order: list["OrderItem"]


# ---------------------------------------------------------------- SELECT parts

@dataclass(eq=False)
class Star:
    table: Optional[str]  # None for '*', else the qualifier of 'x.*'


@dataclass(eq=False)
class SelectItem:
    expr: Expr
    alias: Optional[str]


@dataclass(eq=False)
class TableRef:
    name: Optional[str]               # None for a derived table
    alias: Optional[str]
    query: Optional["Query"] = None   # the query of a derived table

    @property
    def exposed(self) -> str:
        return self.alias or self.name


@dataclass(eq=False)
class Join:
    kind: str  # INNER, LEFT, CROSS
    table: TableRef
    on: Optional[Expr]


@dataclass(eq=False)
class FromClause:
    first: TableRef
    joins: list[Join] = field(default_factory=list)


@dataclass(eq=False)
class OrderItem:
    expr: Expr
    desc: bool
    nulls_first: bool  # where this item's NULLs go (by default: first only when descending)
    bare: bool  # the item was a single token (bare integer literal or bare identifier)


@dataclass(eq=False)
class Select:
    distinct: bool
    items: list[Union[SelectItem, Star]]
    from_: Optional[FromClause] = None
    where: Optional[Expr] = None
    group_by: list[ColumnRef] = field(default_factory=list)
    having: Optional[Expr] = None
    order_by: list[OrderItem] = field(default_factory=list)
    limit: Optional[int] = None
    offset: Optional[int] = None


@dataclass(eq=False)
class Compound:
    """A set operation: UNION [ALL], INTERSECT or EXCEPT. ORDER BY / LIMIT apply to the
    whole result and are only set on the outermost node."""
    op: str  # UNION, INTERSECT, EXCEPT
    all: bool
    left: "Query"
    right: "Query"
    order_by: list[OrderItem] = field(default_factory=list)
    limit: Optional[int] = None
    offset: Optional[int] = None


@dataclass(eq=False)
class Cte:
    name: str
    columns: Optional[list[str]]
    query: "Query"


@dataclass(eq=False)
class With:
    """``WITH [RECURSIVE] name AS (query), ... body``."""
    recursive: bool
    ctes: list[Cte]
    body: "Query"


Query = Union[Select, Compound, With]


# ---------------------------------------------------------------- other statements

@dataclass(eq=False)
class ColumnDef:
    name: str
    type: str  # INTEGER, REAL, TEXT, BOOLEAN
    primary_key: bool = False
    not_null: bool = False
    unique: bool = False
    has_default: bool = False
    default: object = None


@dataclass(eq=False)
class CreateTable:
    name: str
    columns: list[ColumnDef]
    if_not_exists: bool = False


@dataclass(eq=False)
class DropTable:
    name: str
    if_exists: bool = False


@dataclass(eq=False)
class Insert:
    table: str
    columns: Optional[list[str]]
    rows: Optional[list[list[Expr]]]  # VALUES rows, or None for INSERT ... query
    query: Optional[Query] = None


@dataclass(eq=False)
class Update:
    table: str
    assignments: list[tuple[str, Expr]]
    where: Optional[Expr]


@dataclass(eq=False)
class Delete:
    table: str
    where: Optional[Expr]


@dataclass(eq=False)
class CreateIndex:
    name: str
    table: str
    column: str
    unique: bool = False
    if_not_exists: bool = False


@dataclass(eq=False)
class DropIndex:
    name: str
    if_exists: bool = False


@dataclass(eq=False)
class Explain:
    query: Query


@dataclass(eq=False)
class CreateView:
    name: str
    columns: Optional[list[str]]
    query: Query
    sql: str  # the query's text, kept to store the view
    if_not_exists: bool = False


@dataclass(eq=False)
class DropView:
    name: str
    if_exists: bool = False


@dataclass(eq=False)
class AlterAddColumn:
    table: str
    column: ColumnDef


@dataclass(eq=False)
class AlterDropColumn:
    table: str
    column: str


@dataclass(eq=False)
class Transaction:
    """BEGIN, COMMIT or ROLLBACK."""
    action: str


Statement = Union[Select, Compound, CreateTable, DropTable, CreateIndex, DropIndex, Insert,
                  Update, Delete, Explain, AlterAddColumn, AlterDropColumn, Transaction,
                  CreateView, DropView, With]
