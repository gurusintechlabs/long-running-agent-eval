"""Recursive-descent parser: one SQL statement -> AST (``minidb.nodes``)."""
from __future__ import annotations

from minidb import nodes as n
from minidb.lexer import Token, tokenize
from minidb.protocol import SQLSyntaxError

TYPE_NAMES = {"integer": "INTEGER", "int": "INTEGER", "real": "REAL", "text": "TEXT",
              "boolean": "BOOLEAN", "bool": "BOOLEAN"}
AGGREGATES = frozenset({"count", "sum", "avg", "min", "max"})
_CMP_OPS = ("=", "<>", "!=", "<", "<=", ">", ">=")


def parse(sql: str):
    return Parser(sql).statement()


class Parser:
    def __init__(self, sql: str) -> None:
        self.sql = sql
        self.toks = tokenize(sql)
        self.i = 0

    # ------------------------------------------------------------ token helpers

    @property
    def tok(self) -> Token:
        return self.toks[self.i]

    def peek(self, k: int = 1) -> Token:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def advance(self) -> Token:
        t = self.toks[self.i]
        if t.kind != "EOF":
            self.i += 1
        return t

    def error(self, what: str = "") -> SQLSyntaxError:
        t = self.tok
        near = "end of input" if t.kind == "EOF" else repr(self.sql[t.pos:t.pos + 20])
        return SQLSyntaxError(f"syntax error near {near}" + (f": {what}" if what else ""))

    def accept_kw(self, *words: str) -> bool:
        if self.tok.is_kw(*words):
            self.advance()
            return True
        return False

    def expect_kw(self, word: str) -> None:
        if not self.accept_kw(word):
            raise self.error(f"expected {word}")

    def accept_op(self, op: str) -> bool:
        if self.tok.is_op(op):
            self.advance()
            return True
        return False

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.error(f"expected '{op}'")

    def ident(self) -> str:
        if self.tok.kind != "IDENT":
            raise self.error("expected an identifier")
        return self.advance().value

    # ------------------------------------------------------------ statements

    def statement(self):
        t = self.tok
        if t.is_kw("SELECT", "WITH"):
            stmt = self.query()
        elif t.is_kw("CREATE"):
            stmt = self.create()
        elif t.is_kw("DROP"):
            self.advance()
            if self.accept_kw("INDEX"):
                if_exists = self.if_exists()
                stmt = n.DropIndex(self.ident(), if_exists)
            elif self.accept_kw("VIEW"):
                if_exists = self.if_exists()
                stmt = n.DropView(self.ident(), if_exists)
            else:
                self.expect_kw("TABLE")
                if_exists = self.if_exists()
                stmt = n.DropTable(self.ident(), if_exists)
        elif t.is_kw("EXPLAIN"):
            self.advance()
            if not self.tok.is_kw("SELECT", "WITH"):
                raise self.error("EXPLAIN supports only queries")
            stmt = n.Explain(self.query())
        elif t.is_kw("INSERT"):
            stmt = self.insert()
        elif t.is_kw("UPDATE"):
            stmt = self.update()
        elif t.is_kw("DELETE"):
            self.advance()
            self.expect_kw("FROM")
            table = self.ident()
            stmt = n.Delete(table, self.expr() if self.accept_kw("WHERE") else None)
        elif t.is_kw("BEGIN", "COMMIT", "ROLLBACK"):
            self.advance()
            if self.tok.kind == "IDENT" and self.tok.value == "transaction":
                self.advance()
            stmt = {"BEGIN": n.Begin, "COMMIT": n.Commit, "ROLLBACK": n.Rollback}[t.value]()
        elif t.is_kw("ALTER"):
            self.advance()
            self.expect_kw("TABLE")
            table = self.ident()
            if self.accept_kw("ADD"):
                self.accept_kw("COLUMN")
                col = self.column_def()
                if col.primary_key or col.unique:
                    raise SQLSyntaxError("ALTER TABLE ADD COLUMN does not support PRIMARY KEY or UNIQUE")
                stmt = n.AlterAddColumn(table, col)
            else:
                self.expect_kw("DROP")
                self.accept_kw("COLUMN")
                stmt = n.AlterDropColumn(table, self.ident())
        else:
            raise self.error("unknown statement")
        if self.tok.kind != "EOF":
            raise self.error("unexpected text after statement")
        return stmt

    def if_exists(self) -> bool:
        """``IF EXISTS`` (``IF`` is not a reserved word)."""
        if self.tok.kind == "IDENT" and self.tok.value == "if" and self.peek().is_kw("EXISTS"):
            self.advance()
            self.advance()
            return True
        return False

    def if_not_exists(self) -> bool:
        if self.tok.kind == "IDENT" and self.tok.value == "if" and self.peek().is_kw("NOT"):
            self.advance()
            self.advance()
            self.expect_kw("EXISTS")
            return True
        return False

    def create(self):
        self.expect_kw("CREATE")
        if self.accept_kw("VIEW"):
            if_not_exists = self.if_not_exists()
            name = self.ident()
            cols = None
            if self.accept_op("("):
                cols = [self.ident()]
                while self.accept_op(","):
                    cols.append(self.ident())
                self.expect_op(")")
            self.expect_kw("AS")
            if not self.tok.is_kw("SELECT", "WITH"):
                raise self.error("expected a query")
            start = self.tok.pos
            query = self.query()
            return n.CreateView(name, cols, query, self.sql[start:self.tok.pos].strip(), if_not_exists)
        unique = self.accept_kw("UNIQUE")
        if unique or self.tok.is_kw("INDEX"):
            self.expect_kw("INDEX")
            if_not_exists = self.if_not_exists()
            name = self.ident()
            self.expect_kw("ON")
            table = self.ident()
            self.expect_op("(")
            col = self.ident()
            self.expect_op(")")
            return n.CreateIndex(name, table, col, unique, if_not_exists)
        self.expect_kw("TABLE")
        if_not_exists = self.if_not_exists()
        name = self.ident()
        self.expect_op("(")
        cols = [self.column_def()]
        while self.accept_op(","):
            cols.append(self.column_def())
        self.expect_op(")")
        if sum(c.primary_key for c in cols) > 1:
            raise SQLSyntaxError("a table can have only one PRIMARY KEY column")
        return n.CreateTable(name, cols, if_not_exists)

    def column_def(self) -> n.ColumnDef:
        name = self.ident()
        t = self.tok
        if t.kind != "IDENT" or t.value not in TYPE_NAMES:
            raise self.error("expected a column type (INTEGER, REAL, TEXT, BOOLEAN)")
        self.advance()
        col = n.ColumnDef(name, TYPE_NAMES[t.value])
        seen: set[str] = set()
        while True:
            if self.tok.is_kw("PRIMARY"):
                self.advance()
                self.expect_kw("KEY")
                key = "pk"
                col.primary_key = col.not_null = col.unique = True
            elif self.tok.is_kw("NOT"):
                self.advance()
                self.expect_kw("NULL")
                key = "nn"
                col.not_null = True
            elif self.tok.is_kw("UNIQUE"):
                self.advance()
                key = "uq"
                col.unique = True
            elif self.tok.is_kw("DEFAULT"):
                self.advance()
                key = "df"
                col.has_default, col.default = True, self.default_literal()
            else:
                break
            if key in seen:
                raise SQLSyntaxError(f"duplicate constraint on column {name}")
            seen.add(key)
        return col

    def default_literal(self):
        neg = self.accept_op("-")
        t = self.tok
        if t.kind in ("INT", "REAL"):
            self.advance()
            return -t.value if neg else t.value
        if neg:
            raise self.error("expected a number after '-'")
        if t.kind == "STR":
            self.advance()
            return t.value
        if t.is_kw("TRUE", "FALSE", "NULL"):
            self.advance()
            return {"TRUE": True, "FALSE": False, "NULL": None}[t.value]
        raise self.error("DEFAULT needs a literal")

    def insert(self) -> n.Insert:
        self.expect_kw("INSERT")
        self.expect_kw("INTO")
        table = self.ident()
        cols = None
        if self.accept_op("("):
            cols = [self.ident()]
            while self.accept_op(","):
                cols.append(self.ident())
            self.expect_op(")")
            if len(set(cols)) != len(cols):
                raise SQLSyntaxError("a column is listed twice")
        if self.tok.is_kw("SELECT", "WITH"):
            return n.Insert(table, cols, None, self.query())
        self.expect_kw("VALUES")
        rows = [self.value_tuple()]
        while self.accept_op(","):
            rows.append(self.value_tuple())
        return n.Insert(table, cols, rows)

    def value_tuple(self) -> list:
        self.expect_op("(")
        vals = [self.expr()]
        while self.accept_op(","):
            vals.append(self.expr())
        self.expect_op(")")
        return vals

    def update(self) -> n.Update:
        self.expect_kw("UPDATE")
        table = self.ident()
        self.expect_kw("SET")
        assigns = []
        while True:
            col = self.ident()
            self.expect_op("=")
            assigns.append((col, self.expr()))
            if not self.accept_op(","):
                break
        if len({c for c, _ in assigns}) != len(assigns):
            raise SQLSyntaxError("a column is assigned twice")
        where = self.expr() if self.accept_kw("WHERE") else None
        return n.Update(table, assigns, where)

    # ------------------------------------------------------------ SELECT

    def query(self):
        """A SELECT or a set operation, with an optional trailing ORDER BY / LIMIT, optionally
        preceded by WITH."""
        if self.accept_kw("WITH"):
            recursive = False
            if self.tok.kind == "IDENT" and self.tok.value == "recursive" and self.peek().kind == "IDENT":
                self.advance()
                recursive = True
            ctes = []
            while True:
                name = self.ident()
                cols = None
                if self.accept_op("("):
                    cols = [self.ident()]
                    while self.accept_op(","):
                        cols.append(self.ident())
                    self.expect_op(")")
                self.expect_kw("AS")
                self.expect_op("(")
                if not self.tok.is_kw("SELECT", "WITH"):
                    raise self.error("expected a query")
                ctes.append(n.Cte(name, cols, self.query()))
                self.expect_op(")")
                if not self.accept_op(","):
                    break
            if not self.tok.is_kw("SELECT"):
                raise self.error("expected SELECT")
            return n.With(recursive, ctes, self.query())
        q = self.union_term()
        if q is None:
            raise self.error("expected SELECT")
        order, limit, offset = self.order_limit()
        if isinstance(q, n.Select) and q.from_ is None and (order or limit is not None):
            raise SQLSyntaxError("ORDER BY and LIMIT need a FROM clause")
        q.order_by, q.limit, q.offset = order, limit, offset
        return q

    def union_term(self):
        left = self.intersect_term()
        while self.tok.is_kw("UNION", "EXCEPT"):
            op = self.advance().value.lower()
            all_ = self.accept_kw("ALL") if op == "union" else False
            if self.tok.is_kw("ALL"):
                raise self.error("EXCEPT ALL is not supported")
            left = n.SetOp(op, all_, left, self.intersect_term())
        return left

    def intersect_term(self):
        left = self.select()
        while self.accept_kw("INTERSECT"):
            if self.tok.is_kw("ALL"):
                raise self.error("INTERSECT ALL is not supported")
            left = n.SetOp("intersect", False, left, self.select())
        return left

    def order_limit(self):
        order, limit, offset = [], None, 0
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            order.append(self.order_item())
            while self.accept_op(","):
                order.append(self.order_item())
        if self.accept_kw("LIMIT"):
            limit = self.int_literal()
            if self.accept_kw("OFFSET"):
                offset = self.int_literal()
        return order, limit, offset

    def select(self) -> n.Select:
        """One SELECT without ORDER BY / LIMIT (``query`` adds those)."""
        self.expect_kw("SELECT")
        q = n.Select(items=[], distinct=self.accept_kw("DISTINCT"))
        q.items.append(self.select_item())
        while self.accept_op(","):
            q.items.append(self.select_item())
        if not self.accept_kw("FROM"):
            if any(isinstance(it.expr, n.Star) for it in q.items):
                raise SQLSyntaxError("SELECT * needs a FROM clause")
            return q
        q.from_ = self.table_ref()
        while True:
            if self.accept_kw("CROSS"):
                self.expect_kw("JOIN")
                q.joins.append(n.Join("cross", self.table_ref(), None))
                continue
            if self.accept_kw("LEFT"):
                self.accept_kw("OUTER")
                kind = "left"
            elif self.accept_kw("INNER"):
                kind = "inner"
            elif self.tok.is_kw("JOIN"):
                kind = "inner"
            else:
                break
            self.expect_kw("JOIN")
            ref = self.table_ref()
            self.expect_kw("ON")
            q.joins.append(n.Join(kind, ref, self.expr()))
        if self.accept_kw("WHERE"):
            q.where = self.expr()
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            q.group_by.append(self.column_ref())
            while self.accept_op(","):
                q.group_by.append(self.column_ref())
        if self.accept_kw("HAVING"):
            q.having = self.expr()
        return q

    def int_literal(self) -> int:
        if self.tok.kind != "INT":
            raise self.error("expected a non-negative integer")
        return self.advance().value

    def select_item(self) -> n.SelectItem:
        if self.accept_op("*"):
            return n.SelectItem(n.Star(None), None)
        if self.tok.kind == "IDENT" and self.peek().is_op(".") and self.peek(2).is_op("*"):
            table = self.advance().value
            self.advance()
            self.advance()
            return n.SelectItem(n.Star(table), None)
        expr = self.expr()
        alias = self.ident() if self.accept_kw("AS") else None
        return n.SelectItem(expr, alias)

    def table_ref(self) -> n.TableRef:
        if self.accept_op("("):
            query = self.query()
            self.expect_op(")")
            self.accept_kw("AS")
            if self.tok.kind != "IDENT":
                raise self.error("a derived table needs an alias")
            return n.TableRef(None, self.advance().value, query)
        name = self.ident()
        if self.accept_kw("AS"):
            return n.TableRef(name, self.ident())
        if self.tok.kind == "IDENT":
            return n.TableRef(name, self.advance().value)
        return n.TableRef(name, None)

    def column_ref(self) -> n.ColumnRef:
        first = self.ident()
        if self.accept_op("."):
            return n.ColumnRef(first, self.ident())
        return n.ColumnRef(None, first)

    def order_item(self) -> n.OrderItem:
        expr = self.expr()
        desc = False
        if self.accept_kw("DESC"):
            desc = True
        else:
            self.accept_kw("ASC")
        nulls_first = None
        if self.tok.kind == "IDENT" and self.tok.value == "nulls":
            self.advance()
            t = self.tok
            if t.kind != "IDENT" or t.value not in ("first", "last"):
                raise self.error("expected FIRST or LAST after NULLS")
            self.advance()
            nulls_first = t.value == "first"
        return n.OrderItem(expr, desc, nulls_first)

    # ------------------------------------------------------------ expressions

    def expr(self):
        left = self.and_expr()
        while self.accept_kw("OR"):
            left = n.Binary("OR", left, self.and_expr())
        return left

    def and_expr(self):
        left = self.not_expr()
        while self.accept_kw("AND"):
            left = n.Binary("AND", left, self.not_expr())
        return left

    def not_expr(self):
        if self.accept_kw("NOT"):
            return n.Unary("NOT", self.not_expr())
        return self.comparison()

    def comparison(self):
        left = self.concat()
        t = self.tok
        if t.kind == "OP" and t.value in _CMP_OPS:
            self.advance()
            op = "<>" if t.value == "!=" else t.value
            return n.Binary(op, left, self.concat())
        if t.is_kw("IS"):
            self.advance()
            negated = self.accept_kw("NOT")
            self.expect_kw("NULL")
            return n.IsNull(left, negated)
        negated = False
        if t.is_kw("NOT") and self.peek().is_kw("BETWEEN", "IN", "LIKE"):
            self.advance()
            negated = True
        if self.accept_kw("BETWEEN"):
            low = self.concat()
            self.expect_kw("AND")
            return n.Between(left, low, self.concat(), negated)
        if self.accept_kw("IN"):
            self.expect_op("(")
            if self.tok.is_kw("SELECT", "WITH"):
                query = self.query()
                self.expect_op(")")
                return n.InSubquery(left, query, negated)
            items = [self.expr()]
            while self.accept_op(","):
                items.append(self.expr())
            self.expect_op(")")
            return n.InList(left, items, negated)
        if self.accept_kw("LIKE"):
            return n.Like(left, self.concat(), negated)
        return left

    def concat(self):
        left = self.additive()
        while self.accept_op("||"):
            left = n.Binary("||", left, self.additive())
        return left

    def additive(self):
        left = self.multiplicative()
        while self.tok.is_op("+", "-"):
            op = self.advance().value
            left = n.Binary(op, left, self.multiplicative())
        return left

    def multiplicative(self):
        left = self.unary()
        while self.tok.is_op("*", "/", "%"):
            op = self.advance().value
            left = n.Binary(op, left, self.unary())
        return left

    def unary(self):
        if self.tok.is_op("-", "+"):
            op = self.advance().value
            return n.Unary(op, self.unary())
        return self.primary()

    def primary(self):
        t = self.tok
        if t.kind in ("INT", "REAL", "STR"):
            self.advance()
            return n.Literal(t.value)
        if t.is_kw("TRUE", "FALSE", "NULL"):
            self.advance()
            return n.Literal({"TRUE": True, "FALSE": False, "NULL": None}[t.value])
        if t.is_kw("EXISTS"):
            self.advance()
            self.expect_op("(")
            query = self.query()
            self.expect_op(")")
            return n.Exists(query)
        if t.is_kw("CASE"):
            return self.case()
        if t.is_kw("CAST"):
            self.advance()
            self.expect_op("(")
            inner = self.expr()
            self.expect_kw("AS")
            ty = self.tok
            if ty.kind != "IDENT" or ty.value not in TYPE_NAMES:
                raise self.error("expected a type name")
            self.advance()
            self.expect_op(")")
            return n.Cast(inner, TYPE_NAMES[ty.value])
        if t.is_op("("):
            self.advance()
            if self.tok.is_kw("SELECT", "WITH"):
                query = self.query()
                self.expect_op(")")
                return n.ScalarSubquery(query)
            inner = self.expr()
            self.expect_op(")")
            return inner
        if t.kind == "IDENT":
            if self.peek().is_op("("):
                return self.function()
            return self.column_ref()
        raise self.error("expected an expression")

    def case(self) -> n.Case:
        self.expect_kw("CASE")
        operand = None if self.tok.is_kw("WHEN") else self.expr()
        whens = []
        while self.accept_kw("WHEN"):
            cond = self.expr()
            self.expect_kw("THEN")
            whens.append((cond, self.expr()))
        if not whens:
            raise self.error("CASE needs at least one WHEN")
        else_ = self.expr() if self.accept_kw("ELSE") else None
        self.expect_kw("END")
        return n.Case(operand, whens, else_)

    def function(self):
        name = self.advance().value
        self.expect_op("(")
        if self.accept_op("*"):
            self.expect_op(")")
            if name != "count":
                raise SQLSyntaxError(f"{name.upper()}(*) is not allowed")
            if self.tok.kind == "IDENT" and self.tok.value == "over" and self.peek().is_op("("):
                return self.window(name, [], True)
            return n.Func(name, [], star=True)
        distinct = self.accept_kw("DISTINCT")
        if distinct and name not in AGGREGATES:
            raise SQLSyntaxError("DISTINCT is only allowed in aggregates")
        args = []
        if not self.tok.is_op(")"):
            args.append(self.expr())
            while self.accept_op(","):
                args.append(self.expr())
        self.expect_op(")")
        if self.tok.kind == "IDENT" and self.tok.value == "over" and self.peek().is_op("("):
            if distinct:
                raise SQLSyntaxError("DISTINCT is not allowed in a window function")
            return self.window(name, args, False)
        return n.Func(name, args, distinct=distinct)

    def window(self, name: str, args: list, star: bool) -> n.WindowFunc:
        self.advance()  # OVER
        self.expect_op("(")
        partition, order = [], []
        if self.tok.kind == "IDENT" and self.tok.value == "partition":
            self.advance()
            self.expect_kw("BY")
            partition.append(self.expr())
            while self.accept_op(","):
                partition.append(self.expr())
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            order.append(self.order_item())
            while self.accept_op(","):
                order.append(self.order_item())
        self.expect_op(")")
        return n.WindowFunc(name, args, star, partition, order)
